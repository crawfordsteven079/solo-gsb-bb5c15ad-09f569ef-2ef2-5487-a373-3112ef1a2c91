"""判定引擎核心规则测试。"""
import pytest

from app.engine import FieldError, evaluate
from app.seed import _content_v1


def eval_payload(weight=1000, items=None, content=None):
    content = content or _content_v1()
    payload = {"batch_no": "B1", "region": "EAST_CN", "weight_kg": weight,
               "items": items if items is not None else [{"material_code": "PET", "contamination_kg": 10}]}
    return evaluate(payload, content, "v2026.1")


def test_grade_a_accept_no_fee():
    # 1% 污染率 => A，PET 10kg 扣费仍会计算（A 也扣污染费）
    r = eval_payload(items=[{"material_code": "PET", "contamination_kg": 10}])
    assert r["grade"] == "A"
    assert r["conclusion_code"] == "ACCEPT"
    assert r["net_payable"] == round(2.5 * 1000 - 10 * 1.2, 2)
    assert any("v2026.1" in e for e in r["evidence"])


def test_grade_b_accept_fee():
    r = eval_payload(items=[{"material_code": "PET", "contamination_kg": 50}])
    assert r["grade"] == "B"
    assert r["conclusion_code"] == "ACCEPT_FEE"
    assert r["deductions"][0]["amount"] == 60.0


def test_total_rate_over_limit_rejects():
    # 35% > 30% 上限 => REJECT，零结算
    r = eval_payload(items=[{"material_code": "ORGANIC", "contamination_kg": 350}])
    assert r["conclusion_code"] == "REJECT"
    assert r["net_payable"] == 0
    assert any("超过规则上限" in e for e in r["evidence"])


def test_single_material_threshold_rejects():
    # 总污染率 6% 不高，但 PET 6% < 8% 不触发；调到 9% 触发单类别拒收
    r = eval_payload(items=[{"material_code": "PET", "contamination_kg": 90}])
    assert r["conclusion_code"] == "REJECT"
    assert r["rejected_materials"][0]["material_code"] == "PET"


def test_unknown_material_rejected_with_field_error():
    with pytest.raises(FieldError) as exc:
        eval_payload(items=[{"material_code": "XXXX", "contamination_kg": 1}])
    fields = {e["field"] for e in exc.value.errors}
    assert "items.material_code" in fields


def test_negative_weight_rejected():
    with pytest.raises(FieldError) as exc:
        eval_payload(weight=-5)
    assert any(e["field"] == "weight_kg" for e in exc.value.errors)


def test_negative_contamination_rejected():
    with pytest.raises(FieldError) as exc:
        eval_payload(items=[{"material_code": "PET", "contamination_kg": -1}])
    assert any("contamination_kg" in e["field"] for e in exc.value.errors)


def test_contamination_exceeds_weight_rejected():
    with pytest.raises(FieldError) as exc:
        eval_payload(weight=100, items=[{"material_code": "PET", "contamination_kg": 150}])
    assert any("超过来料重量" in e["message"] for e in exc.value.errors)


def test_same_material_rows_aggregated():
    r = eval_payload(items=[
        {"material_code": "pet", "contamination_kg": 10},
        {"material_code": "PET", "contamination_kg": 20},
    ])
    assert r["total_contamination_kg"] == 30.0
    assert len(r["per_material"]) == 1


def test_reject_deduction_covers_gross():
    r = eval_payload(items=[{"material_code": "GLASS", "contamination_kg": 200}])
    assert r["conclusion_code"] == "REJECT"
    assert r["total_deduction"] == r["gross_amount"]
    assert r["net_payable"] == 0
