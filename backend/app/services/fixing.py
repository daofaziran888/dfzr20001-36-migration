"""杀青工序领域服务：记录杀青参数，校验锅温与投叶量范围，校验上游萎凋。

锅温有两个口径：
* 旧口径「锅温设定」——升级前就存在，只能按旧口径受理，不是设备实测温度；
* 新口径「锅温日志」——设备按实际测量时间上报，由 pan 域统一登记、确认、出证。
"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class FixingService(BaseModuleService):
    MODULE = "fixing"
    ENTITY = "杀青记录"
    OPERATION_TERM = "记录杀青"
    LIST_FIELDS = ["锅温设定", "锅温日志", "锅号", "杀青时长", "投叶量", "失重率", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["杀青时长", "投叶量"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"记录杀青": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        setting = values.get("锅温设定")
        device_log = values.get("锅温日志")
        device_temp = values.get("实测锅温")
        if setting not in (None, ""):
            temp = store.parse_weight(setting)
            if temp < 180:
                errors.append("锅温设定不得低于180℃")
            elif temp > 350:
                errors.append("锅温设定不得高于350℃")
        elif not (str(device_log or "").strip() or device_temp not in (None, "")):
            errors.append("杀青记录必须提供锅温设定（旧口径）或锅温日志（新口径）")
        leaf_weight = store.parse_weight(values.get("投叶量", "0"))
        if leaf_weight <= 0:
            errors.append("投叶量必须大于0")
        weight_loss = store.parse_weight(values.get("失重率", "0"))
        if weight_loss < 0 or weight_loss > 50:
            errors.append("杀青失重率应在0-50%之间")
        # 上游工序校验
        upstream_module = values.get("上游工序")
        upstream_id = values.get("上游记录ID")
        if upstream_module and upstream_id is not None:
            upstream = store.find(upstream_module, int(upstream_id))
            if upstream is None:
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 不存在")
            elif upstream.get("status") != "已确认":
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 未确认，不能进行杀青")
        return errors

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记杀青记录；新口径锅温日志同步登记为设备日志，旧口径只存原文。"""
        entry, errors = super().create_entry(values)
        if entry is None:
            return None, errors
        if not str(entry.get("锅号") or "").strip():
            entry["锅号"] = self.pot_key(entry)
        raw_log = str(values.get("锅温日志") or "").strip()
        if raw_log or values.get("实测锅温") not in (None, ""):
            if raw_log:
                # 兼容「220|2026-11-27 09:00」「220@2026-11-27 09:00」和只有温度的写法
                temp_text, _, time_text = (
                    raw_log.replace("@", "|").replace("℃", "").partition("|"))
                temp_text = temp_text.strip()
                time_text = time_text.strip()
            else:
                temp_text = str(values.get("实测锅温") or "").strip()
                time_text = str(values.get("测温时间") or "").strip()
            from app.services.pan import pan_service
            log, message = pan_service.upload_device_log({
                "杀青记录ID": entry["id"],
                "实测锅温": temp_text,
                "测温时间": time_text,
            })
            if log is None:
                # 日志不合规：撤销已建的杀青记录，避免留下没有锅温来源的半成品。
                store.rows(self.MODULE).remove(entry)
                return None, [message]
            entry["锅温日志"] = raw_log or temp_text
            entry["锅温日志编号"] = log.get("日志编号")
            entry["实测锅温"] = log.get("实测锅温")
            entry["测温时间"] = log.get("测温时间")
        return entry, errors

    def pot_key(self, entry: dict[str, Any]) -> str:
        explicit = str(entry.get("锅号") or "").strip()
        if explicit:
            return explicit
        return f"FIXING#{entry['id']}"

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        """杀青确认后计算重量和产出。"""
        if action == "记录杀青":
            upstream_weight = store.parse_weight(entry.get("上游重量", "0"))
            loss_rate = store.parse_weight(entry.get("失重率", "0")) / 100.0
            if upstream_weight > 0 and loss_rate > 0:
                entry["产出重量"] = round(upstream_weight * (1.0 - loss_rate), 3)
            # 旧口径记录确认后，其锅温设定才能继续作为原旧凭据受理。
            if str(entry.get("锅温设定") or "").strip():
                entry["旧口径可受理"] = True
        return True, None

    def calc_weight_after_fixing(self, input_weight: float, loss_rate: float) -> float:
        """根据投入重量和失重率计算杀青后重量。"""
        return round(input_weight * (1.0 - loss_rate / 100.0), 3)

    def get_upstream_withering(self, entry_id: int) -> dict[str, Any] | None:
        """获取杀青记录的上游萎凋记录。"""
        row = store.find(self.MODULE, entry_id)
        if row is None:
            return None
        upstream_module = row.get("上游工序")
        upstream_id = row.get("上游记录ID")
        if upstream_module and upstream_id is not None:
            return store.find(upstream_module, int(upstream_id))
        return None
