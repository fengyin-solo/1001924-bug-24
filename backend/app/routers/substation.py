"""升压站接口：维护升压站，覆盖确认检修、登记负荷越限、停运升压站等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.substation import SubstationService

router = APIRouter(prefix="/api/substation", tags=["升压站"])

service = SubstationService()

LIST_FIELDS = ["站区编号", "主变容量", "电压等级", "所属场站", "上次检修日", "值班班组", "负荷率", "升压站状态"]
STATUSES = ["待检修", "运行正常", "负荷越限", "已停运"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按站区编号检索"),
    status: str | None = Query(default=None, description="待检修、运行正常、负荷越限、已停运"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按站区编号与状态过滤升压站列表；没有数据时返回空页，不报错。

    返回的 summary 与列表同一份数据、同一口径，页头统计直接取用。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total, summary = service.list_entries(keyword=keyword, status=status,
                                                  page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size, summary=summary)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出升压站清单：返回当前过滤条件下的全量数据。"""
    items, total, summary = service.list_entries(page=1, size=10000)
    return {"module": "substation", "total": total, "summary": summary, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条升压站明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"升压站 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条升压站，缺字段或站区编号重复时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="升压站已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条升压站执行确认检修、登记负荷越限、停运升压站。

    不允许的动作/已停运记录会被拦下并说明原因；重复执行同一结论幂等，不重复计数。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message, changed = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
