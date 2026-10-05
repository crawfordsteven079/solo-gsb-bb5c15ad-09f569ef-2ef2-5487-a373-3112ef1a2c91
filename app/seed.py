"""初始规则数据：首次启动幂等写入。

- EAST_CN（华东）: v2026.1 当前生效；v2026.2 为更严格草案，可手动切换
- SOUTH_CN（华南）: v2026.1 当前生效
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import validate_rule_content
from .models import RuleSet

_MATERIALS_V1 = {
    "PET":  {"name": "PET瓶",       "deduct_price_per_kg": 1.2, "max_allowable_rate": 0.08,
             "level_rates": {"A": 0.02, "B": 0.05}},
    "HDPE": {"name": "HDPE硬塑料",  "deduct_price_per_kg": 1.0, "max_allowable_rate": 0.08,
             "level_rates": {"A": 0.02, "B": 0.05}},
    "PP":   {"name": "PP塑料",      "deduct_price_per_kg": 0.9, "max_allowable_rate": 0.10,
             "level_rates": {"A": 0.03, "B": 0.06}},
    "PAPER": {"name": "废纸",       "deduct_price_per_kg": 0.6, "max_allowable_rate": 0.12,
              "level_rates": {"A": 0.03, "B": 0.07}},
    "GLASS": {"name": "玻璃",       "deduct_price_per_kg": 0.4, "max_allowable_rate": 0.05,
              "level_rates": {"A": 0.01, "B": 0.03}},
    "METAL": {"name": "金属",       "deduct_price_per_kg": 1.5, "max_allowable_rate": 0.05,
              "level_rates": {"A": 0.01, "B": 0.03}},
    "ALU":   {"name": "铝制包装物", "deduct_price_per_kg": 2.0, "max_allowable_rate": 0.05,
              "level_rates": {"A": 0.01, "B": 0.03}},
    "ORGANIC": {"name": "有机物/厨余", "deduct_price_per_kg": 0.8, "max_allowable_rate": 0.15,
                "level_rates": {"A": 0.05, "B": 0.10}},
}

_LEVELS = [
    {"code": "A", "name": "轻微", "max_rate": 0.03},
    {"code": "B", "name": "一般", "max_rate": 0.08},
    {"code": "C", "name": "严重", "max_rate": 0.15},
    {"code": "D", "name": "高危", "max_rate": 1.0},
]

_CONCLUSIONS = {
    "ACCEPT":      {"code": "ACCEPT",      "label": "合格接收",            "grades": ["A"]},
    "ACCEPT_FEE":  {"code": "ACCEPT_FEE",  "label": "接收扣费",            "grades": ["B", "C"]},
    "CONDITIONAL": {"code": "CONDITIONAL", "label": "有条件接收/人工复核", "grades": ["D"]},
    "REJECT":      {"code": "REJECT",      "label": "拒收",                "grades": []},
}


def _content_v1() -> dict:
    return {
        "base_price_per_kg": 2.5,
        "currency": "CNY",
        "reject_pays_zero": True,
        "max_total_contamination_rate": 0.30,
        "materials": {k: dict(v) for k, v in _MATERIALS_V1.items()},
        "levels": [dict(v) for v in _LEVELS],
        "conclusions": {k: dict(v) for k, v in _CONCLUSIONS.items()},
    }


def _content_v2() -> dict:
    """v2026.2：华东更严格草案——上限下调、扣费上浮 20%。"""
    content = _content_v1()
    content["max_total_contamination_rate"] = 0.20
    content["base_price_per_kg"] = 2.5
    for code, m in content["materials"].items():
        m["deduct_price_per_kg"] = round(float(m["deduct_price_per_kg"]) * 1.2, 2)
        m["max_allowable_rate"] = round(float(m["max_allowable_rate"]) * 0.8, 4)
    return content


SEED_RULES = [
    ("v2026.1", "EAST_CN", _content_v1(), "2026 年度接收规则（华东）", True),
    ("v2026.2-draft", "EAST_CN", _content_v2(), "华东更严格草案：总污染率上限 20%，扣费上浮 20%", False),
    ("v2026.1", "SOUTH_CN", _content_v1(), "2026 年度接收规则（华南）", True),
]


def seed_rules(db: Session) -> int:
    """幂等写入；返回新增数量。"""
    created = 0
    for version, region, content, note, activate in SEED_RULES:
        validate_rule_content(content)
        exists = db.scalar(
            select(RuleSet).where(RuleSet.version == version, RuleSet.region == region)
        )
        if exists:
            continue
        rs = RuleSet(
            version=version,
            region=region,
            content_json=json.dumps(content, ensure_ascii=False),
            note=note,
            is_active=activate,
        )
        db.add(rs)
        created += 1
    if created:
        db.commit()
    return created
