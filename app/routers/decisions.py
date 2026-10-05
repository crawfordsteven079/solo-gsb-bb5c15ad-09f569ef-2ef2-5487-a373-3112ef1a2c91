"""判定单 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import DecisionCreate
from ..services import decision_service

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.post("", status_code=201, summary="出具/试算污染判定")
def create_decision(payload: DecisionCreate, request: Request, db: Session = Depends(get_db)):
    """根据当前（或指定版本）接收规则计算判定结果。

    - 默认落库出具判定单并固化规则快照；`dry_run=true` 仅试算。
    - 校验失败返回 422，body 中 `errors` 为字段级错误列表。
    """
    operator = request.headers.get("X-Operator", "system")
    return decision_service.calculate(db, payload, save=not payload.dry_run, operator=operator)


@router.get("", summary="查询判定单列表")
def list_decisions(
    db: Session = Depends(get_db),
    batch_no: str | None = None,
    region: str | None = None,
    grade: str | None = Query(None, description="按等级过滤 A/B/C/D"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows, total = decision_service.list_decisions(
        db, batch_no=batch_no, region=region, grade=grade, limit=limit, offset=offset
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [decision_service.serialize(d) for d in rows],
    }


@router.get("/{decision_no}", summary="按判定单号查询")
def get_decision(decision_no: str, db: Session = Depends(get_db)):
    d = decision_service.get_by_no(db, decision_no)
    if d is None:
        raise HTTPException(status_code=404, detail=f"判定单 {decision_no} 不存在")
    return decision_service.serialize(d)


@router.get("/export/csv", summary="按筛选条件导出 CSV")
def export_csv(
    request: Request,
    db: Session = Depends(get_db),
    batch_no: str | None = None,
    region: str | None = None,
    grade: str | None = None,
):
    operator = request.headers.get("X-Operator", "system")
    rows, _ = decision_service.list_decisions(
        db, batch_no=batch_no, region=region, grade=grade, limit=10000, offset=0
    )
    csv_text = decision_service.export_csv(db, rows, operator=operator)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=decisions.csv"},
    )
