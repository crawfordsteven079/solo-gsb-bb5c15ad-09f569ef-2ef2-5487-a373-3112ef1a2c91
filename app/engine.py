"""污染判定引擎：纯函数、可单测、与存储无关。

规则内容（dict）结构：
{
  "base_price_per_kg": 2.5,        # 基准结算价(元/kg)
  "currency": "CNY",
  "reject_pays_zero": true,        # REJECT 结论结算价为 0
  "max_total_contamination_rate": 0.30,  # 总污染率超过该值直接拒收
  "materials": {
    "PET": {"name": "PET瓶", "deduct_price_per_kg": 1.2, "max_allowable_rate": 0.08,
            "level_rates": {"A": 0.02, "B": 0.05}},
    ...
  },
  "levels": [   # 按 max_rate 升序
    {"code": "A", "name": "轻微", "max_rate": 0.03},
    {"code": "B", "name": "一般", "max_rate": 0.08},
    {"code": "C", "name": "严重", "max_rate": 0.15},
    {"code": "D", "name": "高危", "max_rate": 1.0}
  ],
  "conclusions": {
    "ACCEPT":       {"code": "ACCEPT",       "label": "合格接收",  "grades": ["A"]},
    "ACCEPT_FEE":   {"code": "ACCEPT_FEE",   "label": "接收扣费",  "grades": ["B", "C"]},
    "CONDITIONAL":  {"code": "CONDITIONAL",  "label": "有条件接收/人工复核", "grades": ["D"]},
    "REJECT":       {"code": "REJECT",       "label": "拒收",      "grades": []}
  }
}
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import config

D0 = Decimal("0")
MONEY_Q = Decimal(config.MONEY_QUANT)
RATE_Q = Decimal(config.RATE_QUANT)


class FieldError(Exception):
    """字段级校验错误：errors 为 [{'field': ..., 'message': ...}]。"""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))


def _money(d: Decimal) -> Decimal:
    return d.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def _rate(d: Decimal) -> Decimal:
    return d.quantize(RATE_Q, rounding=ROUND_HALF_UP)


REQUIRED_CONTENT_KEYS = (
    "base_price_per_kg",
    "materials",
    "levels",
    "conclusions",
)


def validate_rule_content(content: dict[str, Any]) -> None:
    """校验规则内容结构，不合法抛 FieldError。"""
    errors: list[dict[str, str]] = []
    for key in REQUIRED_CONTENT_KEYS:
        if key not in content:
            errors.append({"field": f"content.{key}", "message": "缺少必填项"})
    if errors:
        raise FieldError(errors)

    materials = content["materials"]
    levels = content["levels"]
    if not isinstance(materials, dict) or not materials:
        errors.append({"field": "content.materials", "message": "至少需要定义一个物料类别"})
    if not isinstance(levels, list) or not levels:
        errors.append({"field": "content.levels", "message": "至少需要定义一个污染等级"})

    for code, m in (materials or {}).items():
        if not isinstance(m, dict) or "deduct_price_per_kg" not in m:
            errors.append({"field": f"content.materials.{code}",
                           "message": "物料规则必须包含 deduct_price_per_kg"})
    rates = []
    for i, lv in enumerate(levels or []):
        if "code" not in lv or "max_rate" not in lv:
            errors.append({"field": f"content.levels[{i}]", "message": "等级需包含 code 与 max_rate"})
        else:
            rates.append(Decimal(str(lv["max_rate"])))
    if rates and rates != sorted(rates):
        errors.append({"field": "content.levels", "message": "等级 max_rate 必须升序排列"})
    if errors:
        raise FieldError(errors)


def evaluate(payload: dict[str, Any], content: dict[str, Any],
             rule_version: str) -> dict[str, Any]:
    """按规则计算判定结果。

    payload: DecisionCreate 的 dict（batch_no/region/weight_kg/items）
    返回完整结果 dict；输入不合法抛 FieldError。
    """
    errors: list[dict[str, str]] = []
    materials_def: dict[str, dict] = content["materials"]
    base_price = Decimal(str(content.get("base_price_per_kg", 0)))
    reject_pays_zero = bool(content.get("reject_pays_zero", True))
    max_total_rate = Decimal(str(content.get("max_total_contamination_rate", 1)))
    levels = sorted(content["levels"], key=lambda lv: Decimal(str(lv["max_rate"])))
    conclusions_def = content["conclusions"]

    # ---------- 1. 输入校验 ----------
    weight = payload.get("weight_kg")
    if weight is None:
        errors.append({"field": "weight_kg", "message": "重量为必填项"})
        weight_dec = None
    else:
        weight_dec = Decimal(str(weight))
        if weight_dec < 0:
            errors.append({"field": "weight_kg", "message": "重量不能为负数"})
        elif weight_dec == 0:
            errors.append({"field": "weight_kg", "message": "重量必须大于 0"})

    items = payload.get("items") or []
    if not items:
        errors.append({"field": "items", "message": "至少需要一条检验明细"})

    # 同类别聚合
    agg: dict[str, Decimal] = {}
    unknown: set[str] = set()
    for idx, item in enumerate(items):
        code = (item.get("material_code") or "").strip().upper()
        raw_amount = item.get("contamination_kg")
        if not code:
            errors.append({"field": f"items[{idx}].material_code", "message": "物料类别代码不能为空"})
            continue
        if code not in materials_def:
            unknown.add(code)
        amount = Decimal(str(raw_amount)) if raw_amount is not None else None
        if amount is None:
            errors.append({"field": f"items[{idx}].contamination_kg", "message": "污染量为必填项"})
        elif amount < 0:
            errors.append({"field": f"items[{idx}].contamination_kg", "message": "污染量不能为负数"})
        else:
            agg[code] = agg.get(code, D0) + amount

    for code in sorted(unknown):
        errors.append({"field": "items.material_code",
                       "message": f"未知物料类别: {code}（规则 {rule_version} 未定义）"})

    # 污染量超过重量（以总污染量判定；重量合法时才检查）
    if weight_dec is not None and weight_dec > 0 and agg:
        total_contam = sum(agg.values(), D0)
        if total_contam > weight_dec:
            errors.append({
                "field": "items.contamination_kg",
                "message": f"污染量合计 {total_contam}kg 超过来料重量 {weight_dec}kg",
            })

    if errors:
        raise FieldError(errors)

    # ---------- 2. 污染率与等级 ----------
    total_contam = sum(agg.values(), D0)
    raw_rate = total_contam / weight_dec
    rate = _rate(raw_rate)

    def grade_of(r: Decimal) -> dict[str, Any]:
        for lv in levels:
            if r <= Decimal(str(lv["max_rate"])):
                return lv
        return levels[-1]

    level = grade_of(raw_rate)

    # 单类别触发：超限 或 超过总污染率上限
    rejected_materials: list[dict[str, Any]] = []
    per_material: list[dict[str, Any]] = []
    for code, amount in agg.items():
        mdef = materials_def[code]
        mrate = _rate(amount / weight_dec)
        row: dict[str, Any] = {
            "material_code": code,
            "name": mdef.get("name", code),
            "contamination_kg": float(amount),
            "rate": float(mrate),
            "deduct_price_per_kg": float(Decimal(str(mdef["deduct_price_per_kg"]))),
        }
        max_allow = mdef.get("max_allowable_rate")
        if max_allow is not None and mrate > Decimal(str(max_allow)):
            rejected_materials.append({
                "material_code": code,
                "name": mdef.get("name", code),
                "rate": float(mrate),
                "max_allowable_rate": float(Decimal(str(max_allow))),
                "reason": f"{code} 污染率 {mrate} 超过单类别允许上限 {Decimal(str(max_allow))}",
            })
        per_material.append(row)

    total_over_limit = raw_rate > max_total_rate

    # ---------- 3. 结论 ----------
    if rejected_materials or total_over_limit:
        conclusion_key = "REJECT"
    else:
        conclusion_key = next(
            (key for key, c in conclusions_def.items()
             if key != "REJECT" and level["code"] in c.get("grades", [])),
            "CONDITIONAL",
        )
    conclusion_def = conclusions_def[conclusion_key]

    # ---------- 4. 扣费与结算 ----------
    gross = base_price * weight_dec
    deductions: list[dict[str, Any]] = []
    if conclusion_key == "REJECT":
        if reject_pays_zero:
            settlement_price = D0
            deductions.append({
                "type": "REJECT_ZERO_SETTLEMENT",
                "name": "拒收零结算",
                "amount": float(_money(gross)),
                "basis": "拒收批次不予结算，扣除全部货值",
            })
        else:
            settlement_price = base_price
    else:
        total_penalty = D0
        for row in per_material:
            penalty = Decimal(str(row["contamination_kg"])) * Decimal(str(row["deduct_price_per_kg"]))
            total_penalty += penalty
            deductions.append({
                "type": "CONTAMINATION_FEE",
                "name": f"{row['name']}({row['material_code']}) 污染扣费",
                "material_code": row["material_code"],
                "contamination_kg": row["contamination_kg"],
                "unit_price": row["deduct_price_per_kg"],
                "amount": float(_money(penalty)),
                "basis": f"{row['contamination_kg']}kg × {row['deduct_price_per_kg']} 元/kg",
            })
        settlement_price = max(gross - total_penalty, D0)

    gross_q = _money(gross)
    total_deduction = _money(sum((Decimal(str(d["amount"])) for d in deductions), D0))
    net = _money(settlement_price)

    # ---------- 5. 证据说明 ----------
    evidence: list[str] = [
        f"依据规则版本 {rule_version}（区域 {payload['region']}）计算，结论出具时已固化该版本快照。",
        f"来料重量 {weight_dec}kg，污染量合计 {total_contam}kg，总污染率 {rate}（原始 {_rate(raw_rate)}）。",
        f"总污染率判定等级：{level['code']}（{level.get('name', '')}），阈值上限 {level['max_rate']}。",
    ]
    if total_over_limit:
        evidence.append(f"总污染率 {rate} 超过规则上限 {max_total_rate}，触发拒收。")
    for rm in rejected_materials:
        evidence.append(rm["reason"] + "，触发拒收。")
    if not rejected_materials and not total_over_limit:
        evidence.append(f"结论 {conclusion_def['code']}（{conclusion_def['label']}）"
                        f"对应等级 {conclusion_def.get('grades', [])}。")
    evidence.append(
        f"货值 {gross_q} 元（{weight_dec}kg × {base_price} 元/kg），"
        f"扣费合计 {total_deduction} 元，应付 {net} 元。"
    )

    return {
        "decision_input": {
            "batch_no": payload["batch_no"],
            "region": payload["region"],
            "weight_kg": float(weight_dec),
            "items": [
                {
                    "material_code": (it.get("material_code") or "").strip().upper(),
                    "contamination_kg": float(Decimal(str(it.get("contamination_kg")))),
                    **({"note": it["note"]} if it.get("note") else {}),
                }
                for it in items
            ],
        },
        "rule_version": rule_version,
        "per_material": sorted(per_material, key=lambda r: r["material_code"]),
        "total_contamination_kg": float(total_contam),
        "contamination_rate": float(rate),
        "grade": level["code"],
        "grade_name": level.get("name", level["code"]),
        "conclusion_code": conclusion_def["code"],
        "conclusion": conclusion_def["label"],
        "rejected_materials": rejected_materials,
        "gross_amount": float(gross_q),
        "deductions": deductions,
        "total_deduction": float(total_deduction),
        "net_payable": float(net),
        "currency": content.get("currency", "CNY"),
        "base_price_per_kg": float(base_price),
        "evidence": evidence,
    }
