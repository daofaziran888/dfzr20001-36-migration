"""锅温日志与揉捻接料路由：迁移回查、设备日志、接料证明、切换/回滚。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.pan import pan_service
from app.store import store

router = APIRouter(prefix="/api/pan", tags=["锅温日志与接料"])


def _body(values: dict[str, Any] | None) -> dict[str, Any]:
    return dict(values or {})


@router.get("/state")
def get_state() -> dict[str, Any]:
    """当前部署口径（new / legacy）与各类计数。"""
    return {"ok": True, "state": pan_service.state()}


@router.post("/mode")
def set_mode(values: dict[str, Any] | None = None,
             mode: str = Query(default="")) -> dict[str, Any]:
    """部署切换 / 回滚：new 或 legacy。"""
    desired = mode or str(_body(values).get("mode") or "")
    try:
        state, message = pan_service.set_mode(desired)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "message": message, "state": state}


@router.post("/migrate")
def migrate(values: dict[str, Any] | None = None) -> dict[str, Any]:
    """把旧环境已存的锅温设定迁移成旧版告知来源（可重复执行）。"""
    payload = _body(values)
    fixing_ids = payload.get("fixing_ids")
    if isinstance(fixing_ids, str) and fixing_ids.strip():
        fixing_ids = [int(x) for x in fixing_ids.split(",") if x.strip()]
    result = pan_service.migrate_legacy(fixing_ids)
    return {"ok": True, **result}


@router.get("/legacy")
def legacy_query(confirmed_only: bool = Query(default=True)) -> dict[str, Any]:
    """按旧口径回查已确认的锅温设定与出料重量。"""
    return {"ok": True, **pan_service.legacy_query(confirmed_only=confirmed_only)}


@router.get("/proofs/{pot}")
def get_proof(pot: str) -> dict[str, Any]:
    """查看某口锅的有效接料证明、两种告知来源与核对结论。"""
    return {"ok": True, **pan_service.get_proof(pot)}


@router.get("/logs")
def list_logs(pot: str = Query(default=""),
              source: str = Query(default="")) -> dict[str, Any]:
    """列出锅温日志（新格式设备日志 + 迁移出的旧版告知来源）。"""
    items = list(store.pan_logs)
    if pot:
        items = [x for x in items if x.get("锅号") == pot]
    if source:
        items = [x for x in items if x.get("来源") == source]
    return {"ok": True, "total": len(items), "items": [dict(x) for x in items]}


@router.post("/logs")
def upload_log(values: dict[str, Any] | None = None) -> dict[str, Any]:
    """设备上报锅温日志；补传相同日志不会重复登记。"""
    log, message = pan_service.upload_device_log(_body(values))
    if log is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "log": log}


@router.post("/logs/{log_id}/confirm")
def confirm_log(log_id: int) -> dict[str, Any]:
    """确认设备锅温日志；缺测量时间不能确认成实测合格。"""
    log, message = pan_service.confirm_log(log_id)
    if log is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "log": log}


@router.get("/pending-receiving")
def pending_receiving() -> dict[str, Any]:
    """还没办成接料的锅（回切后仍可查）。"""
    items = pan_service.pending_receiving()
    return {"ok": True, "total": len(items), "items": items}


@router.get("/receipts/{rolling_id}")
def receipt_history(rolling_id: int) -> dict[str, Any]:
    """已办成的接料凭据历史（回切后保持原版本）。"""
    items = pan_service.receipts_for_rolling(rolling_id)
    return {"ok": True, "total": len(items), "items": items}
