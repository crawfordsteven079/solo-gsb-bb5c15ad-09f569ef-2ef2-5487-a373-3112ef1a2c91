"""ORM 模型：规则集（可版本化）、判定单（固化快照）、审计记录。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class RuleSet(Base):
    """一个可版本化的接收规则集。

    规则内容（materials/levels/conclusions/base_price…）以 JSON 整体存储，
    判定单保存时复制一份快照，因此规则后续更新不会影响历史结论。
    """

    __tablename__ = "rule_sets"
    __table_args__ = (UniqueConstraint("version", "region", name="uq_rule_version_region"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    region: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Decision(Base):
    """来料污染判定单（一经出具即不可变）。"""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_no: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    region: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)

    rule_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    rule_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)

    input_items_json: Mapped[str] = mapped_column(Text, nullable=False)
    total_contamination_kg: Mapped[float] = mapped_column(Float, nullable=False)
    contamination_rate: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    conclusion_code: Mapped[str] = mapped_column(String(32), nullable=False)
    conclusion: Mapped[str] = mapped_column(String(256), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True, nullable=False)


class AuditLog(Base):
    """审计记录：所有关键操作留痕。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(128), default="", index=True, nullable=False)
    operator: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True, nullable=False)
