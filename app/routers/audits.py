"""审计记录 API。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@router.get("", summary="查询审计记录")
def list_audit_logs(
    db: Session = Depends(get_db),
    action: str | None = None,
    entity_type: str | None = None,
    entity_ref: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_ref:
        stmt = stmt.where(AuditLog.entity_ref == entity_ref)
    total = len(db.scalars(stmt).all())
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit).offset(offset)
    ).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_ref": r.entity_ref,
                "operator": r.operator,
                "detail": json.loads(r.detail_json),
                "created_at": r.created_at.isoformat() + "Z",
            }
            for r in rows
        ],
    }
