"""模块服务基类：共享查询、登记、动作、统计骨架，以及跨模块联动能力。

每个子类必须重写 MODULE/ENTITY/OPERATION_TERM/LIST_FIELDS/REQUIRED_FIELDS/
STATUS_ORDER/ACTION_RULES/NEGATIVE_ACTIONS 并提供自定义的 validate_entry/on_confirm/
on_withdraw 等业务钩子。
"""
from __future__ import annotations

from typing import Any

from app.store import store


class BaseModuleService:
    MODULE = ""
    ENTITY = ""
    OPERATION_TERM = ""
    LIST_FIELDS: list[str] = []
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER: list[str] = []
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []

    # ── 通用 CRUD ──

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(self.MODULE))
        for field, expected in (filters or {}).items():
            if field in self.LIST_FIELDS:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        if keyword and self.LIST_FIELDS:
            field = self.LIST_FIELDS[0]
            rows = [row for row in rows if keyword.casefold() in str(row.get(field, "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(self.MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing

        # 业务层自定义校验
        validation_errors = self.validate_entry(values)
        if validation_errors:
            return None, validation_errors

        rows = store.rows(self.MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 存储 LIST_FIELDS 中的标准字段
        entry.update({field: values.get(field) for field in self.LIST_FIELDS})
        # 也存储跨模块关联的额外字段（不在 LIST_FIELDS 中但在 values 中提供的）
        extra_fields = ["garden_id", "garden_name", "grading_ids", "process_module",
                        "process_entry_id", "packing_id", "packing_name", "defect_ids",
                        "shipment_id", "shipment_no", "upstream_module", "upstream_id",
                        "fermentation_warning", "moisture_warning", "linked_defects",
                        "audit_ref", "上游工序", "上游记录ID", "批次号", "登记编号",
                        "序号", "锅号", "锅温日志", "锅温日志编号", "接料凭据编号",
                        "接料凭据版本", "接料已扣料", "接料锅号", "接料核对结论"]
        for ef in extra_fields:
            if ef in values:
                entry[ef] = values[ef]
        entry["status"] = self.STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["frozen"] = False
        rows.append(entry)

        store.log_event(self.MODULE, entry["id"], "create", {"module": self.MODULE})
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        # 冻结检查
        if entry.get("frozen"):
            reason = entry.get("freeze_reason", "未知")
            return None, f"{self.ENTITY} {entry_id} 已被冻结（原因：{reason}），不允许操作"

        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

        # 状态跳级拦截
        current = entry.get("status", "")
        if current == "已确认" and action not in ("提交确认",):
            return None, f"{self.ENTITY}已确认，不允许{action}"

        # 幂等：已处于目标状态则跳过
        if current == target:
            return entry, f"{self.ENTITY}已处于「{target}」状态，无需重复操作"

        # 正向操作钩子
        if target != "已撤回":
            before, after = self.on_confirm(entry, action)
            if before is False:
                return None, after if isinstance(after, str) else "确认操作被业务规则拒绝"

        # 撤回操作钩子
        if target == "已撤回":
            hook_result = self.on_withdraw(entry, action)
            if hook_result is False:
                return None, f"{self.ENTITY}撤回操作被业务规则拒绝"

        entry["status"] = target
        entry["pending"] = target != self.STATUS_ORDER[-1]
        entry["abnormal"] = action in self.NEGATIVE_ACTIONS

        store.log_event(self.MODULE, entry_id, action, {"from": current, "to": target})
        return entry, f"{self.ENTITY}已{action}"

    def domain_snapshot(self) -> dict[str, Any]:
        """返回本模块的状态统计与业务对象，供其他模块读取。"""
        rows = store.rows(self.MODULE)
        by_status = {
            status: sum(1 for row in rows if row.get("status") == status)
            for status in self.STATUS_ORDER
        }
        return {
            "module": self.MODULE,
            "entity": self.ENTITY,
            "artifact": f"{self.ENTITY}状态记录",
            "count": len(rows),
            "by_status": by_status,
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
            "frozen": sum(1 for row in rows if row.get("frozen")),
        }

    # ── 业务钩子（子类重写）──

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        """登记时自定义校验，返回错误信息列表。"""
        return []

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        """确认操作前置处理，返回 (通过, 拒绝原因)。"""
        return True, None

    def on_withdraw(self, entry: dict[str, Any], action: str) -> bool:
        """撤回操作前置处理，返回是否允许。"""
        return True

    # ── 跨模块共享方法 ──

    def get_confirmed_by_batch(self, batch_no: str) -> list[dict[str, Any]]:
        """获取本模块中指定批次号的已确认记录。"""
        rows = store.rows(self.MODULE)
        return [
            row for row in rows
            if row.get("批次号") == batch_no and row.get("status") == "已确认"
        ]

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        """获取本模块中指定状态的记录。"""
        rows = store.rows(self.MODULE)
        return [row for row in rows if row.get("status") == status]