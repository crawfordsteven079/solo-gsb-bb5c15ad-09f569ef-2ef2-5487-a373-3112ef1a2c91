"""判定单服务：试算、出具（固化快照）、查询、导出。"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from .rule_service import resolve_rule
from ..engine import evaluate
from ..models import Decision, RuleSet


def generate_decision_no() -> str:
    return f"RC{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]}"


def _payload_from_schema(payload) -> dict:
    return payload.model_dump()


def calculate(db: Session, payload, save: bool, operator: str = "system") -> dict:
    """核心入口：解析规则 -> 引擎计算 -> （可选）落库固化。

    payload 为 DecisionCreate。save=False 即 dry-run。
    """
    rs: RuleSet = resolve_rule(db, payload.region.strip(), payload.rule_version)

    content = json.loads(rs.content_json)
    raw = _payload_from_schema(payload)
    raw["region"] = raw["region"].strip()
    raw["batch_no"] = raw["batch_no"].strip()

    result = evaluate(raw, content, rs.version)

    if not save:
        result["persisted"] = False
        result["rule_set_id"] = rs.id
        audit.record(db, "decision.dry_run", "decision", raw["batch_no"],
                     {"batch_no": raw["batch_no"], "region": raw["region"],
                      "rule_version": rs.version, "grade": result["grade"],
                      "conclusion": result["conclusion_code"]},
                     operator, commit=True)
        return result

    decision_no = generate_decision_no()
    decision = Decision(
        decision_no=decision_no,
        batch_no=raw["batch_no"],
        region=raw["region"],
        weight_kg=raw["weight_kg"],
        rule_version=rs.version,
        # 关键：保存规则内容整体快照，历史结论不受后续规则更新影响
        rule_snapshot_json=rs.content_json,
        input_items_json=json.dumps(raw["items"], ensure_ascii=False),
        total_contamination_kg=result["total_contamination_kg"],
        contamination_rate=result["contamination_rate"],
        grade=result["grade"],
        conclusion_code=result["conclusion_code"],
        conclusion=result["conclusion"],
        result_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(decision)
    db.flush()
    result["persisted"] = True
    result["decision_no"] = decision_no
    result["id"] = decision.id
    # 回写 decision_no 到结果快照
    result_obj = json.loads(decision.result_json)
    result_obj["decision_no"] = decision_no
    result_obj["persisted"] = True
    decision.result_json = json.dumps(result_obj, ensure_ascii=False)

    audit.record(db, "decision.create", "decision", decision_no,
                 {"decision_no": decision_no, "batch_no": raw["batch_no"],
                  "region": raw["region"], "rule_version": rs.version,
                  "grade": result["grade"], "conclusion": result["conclusion_code"],
                  "rule_snapshot_fixed": True}, operator)
    db.commit()
    db.refresh(decision)
    return serialize(decision)


def serialize(d: Decision) -> dict:
    return {
        "id": d.id,
        "persisted": True,
        "decision_no": d.decision_no,
        "batch_no": d.batch_no,
        "region": d.region,
        "weight_kg": d.weight_kg,
        "rule_version": d.rule_version,
        "total_contamination_kg": d.total_contamination_kg,
        "contamination_rate": d.contamination_rate,
        "grade": d.grade,
        "conclusion_code": d.conclusion_code,
        "conclusion": d.conclusion,
        "created_at": d.created_at.isoformat() + "Z",
        "items": json.loads(d.input_items_json),
        "result": json.loads(d.result_json),
        # 快照回传，便于核对当时规则
        "rule_snapshot": json.loads(d.rule_snapshot_json),
    }


def get_by_no(db: Session, decision_no: str) -> Decision | None:
    return db.scalars(
        select(Decision).where(Decision.decision_no == decision_no)
    ).first()


def list_decisions(db: Session, batch_no: str | None = None,
                   region: str | None = None, grade: str | None = None,
                   limit: int = 50, offset: int = 0) -> tuple[list[Decision], int]:
    stmt = select(Decision)
    if batch_no:
        stmt = stmt.where(Decision.batch_no == batch_no)
    if region:
        stmt = stmt.where(Decision.region == region)
    if grade:
        stmt = stmt.where(Decision.grade == grade)
    total = len(db.scalars(stmt).all())
    rows = db.scalars(
        stmt.order_by(Decision.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), total


CSV_HEADER = [
    "decision_no", "batch_no", "region", "weight_kg",
    "total_contamination_kg", "contamination_rate",
    "grade", "conclusion_code", "conclusion",
    "gross_amount", "total_deduction", "net_payable",
    "rule_version", "created_at", "evidence",
]


def export_csv(db: Session, decisions: list[Decision], operator: str = "system") -> str:
    buf = io.StringIO()
    buf.write("﻿")  # BOM，Excel 正确识别 UTF-8
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for d in decisions:
        r = json.loads(d.result_json)
        writer.writerow([
            d.decision_no, d.batch_no, d.region, d.weight_kg,
            d.total_contamination_kg, d.contamination_rate,
            d.grade, d.conclusion_code, d.conclusion,
            r.get("gross_amount", ""), r.get("total_deduction", ""),
            r.get("net_payable", ""), d.rule_version,
            d.created_at.isoformat() + "Z",
            " | ".join(r.get("evidence", [])),
        ])
    audit.record(db, "decision.export", "decision",
                 ",".join(d.decision_no for d in decisions),
                 {"count": len(decisions), "format": "csv"}, operator, commit=True)
    return buf.getvalue()
