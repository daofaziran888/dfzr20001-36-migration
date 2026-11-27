"""内存数据仓库：支持批次血缘、事件日志、状态冻结与幂等校验。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import copy
import time
from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 批次号 -> 跨模块记录引用列表，每项 {"module": str, "entry_id": int}
        self._lineage: dict[str, list[dict[str, Any]]] = {}
        # 事件日志：每项 {"ts": float, "module": str, "entry_id": int, "action": str, "detail": dict}
        self._events: list[dict[str, Any]] = []
        # 幂等请求缓存：request_id -> 上次执行结果
        self._idempotency: dict[str, dict[str, Any]] = {}
        # 冻结标记：被不合格处置关联的记录 id -> True
        self._frozen: dict[tuple[str, int], str] = {}
        # 锅温日志 / 接料凭据领域状态。
        # 旧环境只有单个「锅温设定」；升级后设备按实际测量时间上报「锅温日志」。
        # 这些结构独立于业务表，避免把旧设定行改写成实测数据。
        self.pan_legacy_logs: list[dict[str, Any]] = []   # 由旧记录迁移出的告知来源
        self.pan_logs: list[dict[str, Any]] = []          # 设备/新格式锅温日志
        self.pan_proofs: list[dict[str, Any]] = []        # 每锅至多一份「有效」接料证明
        self.pan_receipts: list[dict[str, Any]] = []      # 已接料凭据快照（回滚后保留）
        self.pan_state: dict[str, Any] = {
            "mode": "new",            # new / legacy：部署切换与回滚开关
            "rollback_at": None,
            "seq": {"log": 0, "proof": 0, "receipt": 0},
        }
        # 初始化建种子血缘索引
        self._build_lineage_from_seed()

    # ── 锅温日志序号 ──

    def next_pan_id(self, kind: str) -> int:
        seq = self.pan_state["seq"]
        seq[kind] = int(seq.get(kind, 0)) + 1
        return int(seq[kind])

    # ── 表操作 ──

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    # ── 概览 ──

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
                "frozen": sum(1 for row in rows if row.get("frozen")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
            {"label": "冻结数", "value": sum(int(item["frozen"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}

    # ── 事件日志 ──

    def log_event(self, module: str, entry_id: int, action: str, detail: dict[str, Any] | None = None) -> None:
        self._events.append({
            "ts": time.time(),
            "module": module,
            "entry_id": entry_id,
            "action": action,
            "detail": detail or {},
        })

    def get_events(self, module: str | None = None, entry_id: int | None = None) -> list[dict[str, Any]]:
        result = self._events
        if module:
            result = [e for e in result if e["module"] == module]
        if entry_id is not None:
            result = [e for e in result if e["entry_id"] == entry_id]
        return result

    # ── 批次血缘 ──

    def register_lineage(self, batch_no: str, module: str, entry_id: int) -> None:
        if batch_no not in self._lineage:
            self._lineage[batch_no] = []
        # 避免重复注册
        if not any(e["module"] == module and e["entry_id"] == entry_id for e in self._lineage[batch_no]):
            self._lineage[batch_no].append({"module": module, "entry_id": entry_id})

    def get_lineage(self, batch_no: str) -> list[dict[str, Any]]:
        """返回批次的完整血缘链，包含每条记录的当前数据。"""
        entries = self._lineage.get(batch_no, [])
        result = []
        for entry in entries:
            row = self.find(entry["module"], entry["entry_id"])
            if row:
                result.append({
                    "module": entry["module"],
                    "entry_id": entry["entry_id"],
                    "data": dict(row),
                })
        return result

    def get_batch_lineage_nodes(self, batch_no: str) -> list[dict[str, Any]]:
        """返回批次血缘链中所有原始记录引用（不含当前数据副本）。"""
        return [dict(e) for e in self._lineage.get(batch_no, [])]

    # ── 幂等 ──

    def check_idempotent(self, request_id: str) -> dict[str, Any] | None:
        return self._idempotency.get(request_id)

    def record_idempotent(self, request_id: str, result: dict[str, Any]) -> None:
        self._idempotency[request_id] = dict(result)

    # ── 冻结 ──

    def freeze_entry(self, module: str, entry_id: int, reason: str) -> bool:
        row = self.find(module, entry_id)
        if row is None:
            return False
        row["frozen"] = True
        row["freeze_reason"] = reason
        self._frozen[(module, entry_id)] = reason
        return True

    def is_frozen(self, module: str, entry_id: int) -> bool:
        return self._frozen.get((module, entry_id)) is not None

    def get_frozen_reason(self, module: str, entry_id: int) -> str | None:
        return self._frozen.get((module, entry_id))

    # ── 重量/损耗计算辅助 ──

    def parse_weight(self, val: Any) -> float:
        """将业务字段值转为公斤数。"""
        try:
            return float(str(val).replace("kg", "").replace("斤", "").strip())
        except (ValueError, TypeError):
            return 0.0

    def record_weight_after_loss(self, row: dict[str, Any], input_weight_field: str,
                                  loss_field: str) -> float:
        """根据投入重量和损耗率计算产出重量并写入记录。"""
        input_weight = self.parse_weight(row.get(input_weight_field, 0))
        loss_rate = self.parse_weight(row.get(loss_field, 0)) / 100.0
        output_weight = round(input_weight * (1.0 - loss_rate), 3)
        row["产出重量"] = output_weight
        return output_weight

    # ── 种子血缘初始化 ──

    def _build_lineage_from_seed(self) -> None:
        """从种子数据中提取批次号并建立初始血缘索引。"""
        batch_modules = ["picking", "withering", "fixing", "rolling",
                         "fermentation", "drying", "grading", "blending",
                         "packing", "trace_code", "shipment"]
        for mod in batch_modules:
            for row in self.rows(mod):
                batch_no = row.get("批次号") or row.get("登记编号", "")
                if batch_no and "BATCH-" in str(batch_no):
                    self.register_lineage(batch_no, mod, int(row["id"]))


store = Store()