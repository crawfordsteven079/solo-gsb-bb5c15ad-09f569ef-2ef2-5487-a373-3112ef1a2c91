"""接收规则 API：版本化管理与区域切换。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import RegionActiveRule, RuleSetCreate
from ..services import rule_service

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _serialize(rs) -> dict:
    return {
        "id": rs.id,
        "version": rs.version,
        "region": rs.region,
        "content": json.loads(rs.content_json),
        "note": rs.note,
        "is_active": rs.is_active,
        "created_at": rs.created_at.isoformat() + "Z",
    }


@router.get("/regions", summary="区域及其当前生效规则")
def regions(db: Session = Depends(get_db)):
    result = []
    for region in rule_service.list_regions(db):
        active = rule_service.get_active_for_region(db, region)
        result.append(RegionActiveRule(
            region=region,
            active_version=active.version if active else None,
            rule_set_id=active.id if active else None,
        ).model_dump())
    return {"items": result}


@router.get("", summary="规则版本列表（可按区域过滤）")
def list_rules(region: str | None = None, db: Session = Depends(get_db)):
    return {"items": [_serialize(rs) for rs in rule_service.list_rules(db, region)]}


@router.post("", status_code=201, summary="创建新规则版本")
def create_rule(payload: RuleSetCreate, request: Request, db: Session = Depends(get_db)):
    operator = request.headers.get("X-Operator", "system")
    rs = rule_service.create_rule(
        db, payload.version, payload.region.strip(), payload.content,
        payload.note, payload.activate, operator=operator,
    )
    return _serialize(rs)


@router.get("/{rule_id}", summary="查看规则版本内容（含历史版本）")
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    rs = rule_service.get_rule_or_none(db, rule_id)
    if rs is None:
        raise HTTPException(status_code=404, detail="规则版本不存在")
    return _serialize(rs)


@router.post("/{rule_id}/activate", summary="在规则所属区域激活该版本（区域规则切换）")
def activate_rule(rule_id: int, request: Request, db: Session = Depends(get_db)):
    operator = request.headers.get("X-Operator", "system")
    rs = rule_service.activate_rule(db, rule_id, operator=operator)
    return _serialize(rs)
