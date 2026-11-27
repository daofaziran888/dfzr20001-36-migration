"""揉捻工序领域服务：记录揉捻参数，评估成条率与碎茶比例，校验上游杀青。

升级后揉捻工位要凭「接料证明」接料：先查该锅唯一的有效证明，再完成接料。
同一个锅、同一份日志重复补传或重复进入工位都不会重新扣料；切换/回滚期间已确认
的揉捻保留当时实际使用的凭据版本。
"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class RollingService(BaseModuleService):
    MODULE = "rolling"
    ENTITY = "揉捻记录"
    OPERATION_TERM = "记录揉捻"
    LIST_FIELDS = ["压力档位", "揉捻时长", "成条率", "碎茶比例", "锅号", "接料凭据编号", "接料凭据版本", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["压力档位", "揉捻时长", "成条率"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"记录揉捻": "已确认", "提交确认": "待确认", "撤回记录": "已撤回", "完成接料": "已确认"}
    NEGATIVE_ACTIONS = []

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        twig_rate = store.parse_weight(values.get("成条率", "0"))
        if twig_rate <= 0 or twig_rate > 100:
            errors.append("成条率应在1-100%之间")
        debris = store.parse_weight(values.get("碎茶比例", "0"))
        if debris < 0 or debris > 50:
            errors.append("碎茶比例应在0-50%之间")
        # 上游工序校验
        upstream_module = values.get("上游工序")
        upstream_id = values.get("上游记录ID")
        if upstream_module and upstream_id is not None:
            upstream = store.find(upstream_module, int(upstream_id))
            if upstream is None:
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 不存在")
            elif upstream.get("status") != "已确认":
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 未确认，不能进行揉捻")
        return errors

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        if action in ("记录揉捻", "完成接料"):
            batch_no = entry.get("批次号", "")
            if batch_no:
                lineage = store.get_lineage(batch_no)
                weight_from_upstream = store.parse_weight(entry.get("上游重量", "0"))
                if weight_from_upstream > 0:
                    debris = store.parse_weight(entry.get("碎茶比例", "0")) / 100.0
                    entry["产出重量"] = round(weight_from_upstream * (1.0 - debris), 3)
        return True, None

    def evaluate_quality(self, twig_rate: float, debris_rate: float) -> str:
        """根据成条率和碎茶率评估揉捻质量等级。"""
        if twig_rate >= 90 and debris_rate <= 5:
            return "优"
        elif twig_rate >= 75 and debris_rate <= 15:
            return "良"
        else:
            return "需改进"

    def pot_key(self, entry: dict[str, Any]) -> str:
        """揉捻记录对应的锅号：优先上游杀青记录的锅号。"""
        explicit = str(entry.get("锅号") or "").strip()
        if explicit:
            return explicit
        upstream_module = entry.get("上游工序")
        upstream_id = entry.get("上游记录ID")
        if upstream_id not in (None, ""):
            try:
                if upstream_module in ("fixing", None):
                    fixing = store.find("fixing", int(upstream_id))
                    if fixing is not None:
                        from app.services.pan import pan_service
                        return pan_service.pot_key_for_fixing(fixing)
            except (TypeError, ValueError):
                pass
        return f"ROLLING#{entry.get('id')}"

    def receive_plan(self, entry_id: int) -> dict[str, Any] | None:
        """揉捻工位查询接料证明：该锅的有效证明、两种告知来源与核对结论。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        pot = self.pot_key(entry)
        from app.services.pan import pan_service
        plan = pan_service.get_proof(pot)
        plan["揉捻记录ID"] = entry_id
        plan["已接料"] = pan_service.receipt_for_rolling(entry_id)
        return plan

    def receive(self, entry_id: int, pot: str | None = None,
                request_id: str = "") -> tuple[dict[str, Any] | None, str]:
        """完成接料：查证明并办理；重复办理幂等，不会重新扣料。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"揉捻记录 {entry_id} 不存在"
        pot = pot or self.pot_key(entry)
        from app.services.pan import pan_service
        receipt, message, reconcile = pan_service.receive(entry_id, pot, request_id=request_id)
        if receipt is not None:
            entry["锅号"] = pot
            entry["接料凭据编号"] = receipt.get("凭据编号")
            entry["接料凭据版本"] = receipt.get("凭据版本")
            entry["接料已扣料"] = True
        entry["接料核对结论"] = reconcile.get("说明", "")
        # 失败时返回 None，让接口 ok=false；核对结论仍留在揉捻记录上可查。
        return receipt, message

    def receive_history(self, entry_id: int) -> list[dict[str, Any]]:
        """回滚后仍能查询已办成接料的历史凭据。"""
        from app.services.pan import pan_service
        return pan_service.receipts_for_rolling(entry_id)
