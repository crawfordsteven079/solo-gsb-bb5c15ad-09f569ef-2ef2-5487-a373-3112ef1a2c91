"""审计日志辅助。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def record(db: Session, action: str, entity_type: str, entity_ref: str = "",
           detail: dict[str, Any] | None = None, operator: str = "system",
           commit: bool = False) -> AuditLog:
    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_ref=str(entity_ref),
        operator=operator,
        detail_json=json.dumps(detail or {}, ensure_ascii=False, default=str),
    )
    db.add(log)
    db.flush()
    if commit:
        db.commit()
    return log
