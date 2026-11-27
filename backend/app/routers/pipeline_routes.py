"""跨模块流水线路由：批次追溯、工序推进、门禁、重量守恒、含水率回算。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services.pipeline import pipeline

router = APIRouter(prefix="/api/pipeline", tags=["批次流水线"])


@router.get("/{batch_no}/trace")
def get_trace(batch_no: str) -> dict[str, Any]:
    """获取批次完整追溯链，按工序顺序排列。"""
    chain = pipeline.get_trace_chain(batch_no)
    if not chain.get("chain"):
        raise HTTPException(status_code=404, detail=f"批次 {batch_no} 尚无溯源记录")
    return chain


@router.post("/{batch_no}/advance")
def advance_batch(
    batch_no: str,
    current_module: str = Query(...),
    current_entry_id: int = Query(...),
    request_id: str = Query(default=""),
    values: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    """将指定批次从当前工序推进到下一道工序。"""
    return _advance_impl(batch_no, current_module, current_entry_id, request_id, values)


def _advance_impl(batch_no: str, current_module: str, current_entry_id: int,
                  request_id: str, values: dict[str, Any] | None) -> dict[str, Any]:
    entry, message = pipeline.advance_batch(
        current_module, current_entry_id, batch_no, request_id, values)
    if entry is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "entry": entry}


@router.get("/{batch_no}/gate")
def check_gate(batch_no: str) -> dict[str, Any]:
    """获取批次门禁检查结论。"""
    detail = pipeline.get_gate_detail(batch_no)
    return {"ok": detail["passed"], "detail": detail}


@router.get("/{batch_no}/weight-conservation")
def weight_conservation(batch_no: str) -> dict[str, Any]:
    """检查批次的重量守恒。"""
    result = pipeline.check_weight_conservation(batch_no)
    return {"ok": result["conservation_ok"], "detail": result}


@router.post("/{batch_no}/moisture-recalc")
def recalc_moisture(batch_no: str, process_module: str = Query(...)) -> dict[str, Any]:
    """回算指定工序节点的含水率。"""
    result = pipeline.recalc_moisture_at_node(batch_no, process_module)
    if result is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_no} 在工序 {process_module} 无记录")
    return {"ok": True, "detail": result}


@router.post("/{batch_no}/freeze-downstream")
def freeze_downstream(
    batch_no: str,
    defect_entry_id: int = Query(...),
    reason: str = Query(default="不合格处置"),
) -> dict[str, Any]:
    """冻结批次中不合格发现点之后的所有下游记录。"""
    count, keys = pipeline.freeze_batch_downstream(batch_no, defect_entry_id, reason)
    return {"ok": True, "frozen_count": count, "frozen_keys": keys}


@router.post("/sample/{sample_entry_id}/link")
def link_sample(
    sample_entry_id: int,
    process_module: str = Query(...),
    process_entry_id: int = Query(...),
) -> dict[str, Any]:
    """将样品留样关联到具体工序记录。"""
    sample, message = pipeline.link_sample_to_node(sample_entry_id, process_module, process_entry_id)
    if sample is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "sample": sample}


@router.post("/audit/{audit_entry_id}/review")
def update_audit_review(
    audit_entry_id: int,
    review_conclusion: str = Query(...),
) -> dict[str, Any]:
    """回写内审巡查的复查结论并同步关联整改事项。"""
    entry, message = pipeline.update_audit_review(audit_entry_id, review_conclusion)
    if entry is None:
        raise HTTPException(status_code=404, detail=message)
    return {"ok": True, "message": message, "entry": entry}


@router.get("/events")
def list_events(
    module: str | None = Query(default=None),
    entry_id: int | None = Query(default=None),
) -> dict[str, Any]:
    """获取事件日志。"""
    events = store().get_events(module=module, entry_id=entry_id)
    return {"ok": True, "events": events}


def store():
    from app.store import store as _store
    return _store