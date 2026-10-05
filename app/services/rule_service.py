"""规则集服务：版本管理、区域生效切换。"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..engine import FieldError, validate_rule_content
from ..models import RuleSet


def get_rule_or_none(db: Session, rule_id: int) -> RuleSet | None:
    return db.get(RuleSet, rule_id)


def get_by_version(db: Session, version: str, region: str | None = None) -> RuleSet | None:
    stmt = select(RuleSet).where(RuleSet.version == version)
    if region is not None:
        stmt = stmt.where(RuleSet.region == region)
    return db.scalars(stmt).first()


def list_rules(db: Session, region: str | None = None) -> list[RuleSet]:
    stmt = select(RuleSet).order_by(RuleSet.region.asc(), RuleSet.created_at.desc())
    if region:
        stmt = stmt.where(RuleSet.region == region)
    return list(db.scalars(stmt))


def get_active_for_region(db: Session, region: str) -> RuleSet | None:
    return db.scalars(
        select(RuleSet).where(RuleSet.region == region, RuleSet.is_active.is_(True))
    ).first()


def list_regions(db: Session) -> list[str]:
    rows = db.scalars(select(RuleSet.region).distinct()).all()
    return sorted(set(rows))


def resolve_rule(db: Session, region: str, version: str | None) -> RuleSet:
    """解析本次判定使用的规则：指定版本优先，否则取区域当前生效版本。"""
    if version:
        rs = get_by_version(db, version, region)
        if rs is None:
            # 版本可能跨区域存在
            any_rs = get_by_version(db, version)
            if any_rs is None:
                raise FieldError([{"field": "rule_version",
                                   "message": f"规则版本 {version} 不存在"}])
            raise FieldError([{"field": "rule_version",
                               "message": f"规则版本 {version} 不属于区域 {region}（该版本属于 {any_rs.region}）"}])
        return rs
    rs = get_active_for_region(db, region)
    if rs is None:
        raise FieldError([{"field": "region",
                           "message": f"区域 {region} 没有生效中的规则版本，请先配置并激活规则"}])
    return rs


def create_rule(db: Session, version: str, region: str, content: dict,
                note: str, activate: bool, operator: str = "system") -> RuleSet:
    if get_by_version(db, version, region) is not None:
        raise FieldError([{"field": "version",
                           "message": f"规则版本 {version} 在区域 {region} 已存在"}])
    validate_rule_content(content)
    rs = RuleSet(
        version=version,
        region=region,
        content_json=json.dumps(content, ensure_ascii=False),
        note=note,
        is_active=False,
    )
    db.add(rs)
    db.flush()
    audit.record(db, "rule.create", "rule_set", rs.version,
                 {"version": version, "region": region, "activate": activate}, operator)
    if activate:
        _activate(db, rs, operator, already_flushed=True)
    db.commit()
    db.refresh(rs)
    return rs


def activate_rule(db: Session, rule_id: int, operator: str = "system") -> RuleSet:
    rs = get_rule_or_none(db, rule_id)
    if rs is None:
        raise FieldError([{"field": "rule_set_id", "message": "规则集不存在"}])
    _activate(db, rs, operator)
    db.commit()
    db.refresh(rs)
    return rs


def _activate(db: Session, rs: RuleSet, operator: str, already_flushed: bool = False) -> None:
    """同一区域内仅一个生效版本（事务内切换）。"""
    if not already_flushed:
        db.flush()
    others = db.scalars(
        select(RuleSet).where(RuleSet.region == rs.region, RuleSet.is_active.is_(True))
    ).all()
    previous = [o.version for o in others if o.id != rs.id]
    for o in others:
        o.is_active = False
    rs.is_active = True
    audit.record(db, "rule.activate", "rule_set", rs.version,
                 {"region": rs.region, "previous_versions": previous}, operator)
