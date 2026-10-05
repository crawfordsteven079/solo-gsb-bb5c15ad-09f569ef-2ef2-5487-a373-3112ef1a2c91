"""API 端到端测试：出具、错误、版本固化、切换、导出、审计。"""
import io
import csv


def test_health(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_full_flow_create_and_get(client):
    resp = client.post("/api/decisions", json={
        "batch_no": "BATCH-E2E-1", "region": "EAST_CN", "weight_kg": 1000,
        "items": [{"material_code": "PET", "contamination_kg": 50}],
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["persisted"] is True
    assert data["grade"] == "B"
    assert data["conclusion_code"] == "ACCEPT_FEE"
    assert data["result"]["rule_version"] == "v2026.1"
    # 规则快照已固化
    assert data["rule_snapshot"]["materials"]["PET"]["deduct_price_per_kg"] == 1.2

    no = data["decision_no"]
    got = client.get(f"/api/decisions/{no}")
    assert got.status_code == 200
    assert got.json()["batch_no"] == "BATCH-E2E-1"

    lst = client.get("/api/decisions", params={"batch_no": "BATCH-E2E-1"})
    assert lst.json()["total"] == 1


def test_validation_error_shape(client):
    resp = client.post("/api/decisions", json={
        "batch_no": "BATCH-BAD", "region": "EAST_CN", "weight_kg": -10,
        "items": [{"material_code": "UNKNOWN", "contamination_kg": 999},
                  {"material_code": "PET", "contamination_kg": -3}],
    })
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    fields = {e["field"] for e in errors}
    assert "weight_kg" in fields
    assert "items.material_code" in fields
    assert "items[1].contamination_kg" in fields


def test_missing_body_field_is_422(client):
    resp = client.post("/api/decisions", json={"batch_no": "X"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "request_validation_failed"


def test_dry_run_not_persisted(client):
    resp = client.post("/api/decisions", json={
        "batch_no": "BATCH-DRY", "region": "EAST_CN", "weight_kg": 100,
        "items": [{"material_code": "PAPER", "contamination_kg": 1}],
        "dry_run": True,
    })
    assert resp.status_code == 201
    assert resp.json()["persisted"] is False
    assert client.get("/api/decisions", params={"batch_no": "BATCH-DRY"}).json()["total"] == 0


def test_rule_switch_and_history_immutability(client):
    # 先用 v2026.1 出具一张判定单
    r1 = client.post("/api/decisions", json={
        "batch_no": "BATCH-VER-1", "region": "EAST_CN", "weight_kg": 1000,
        "items": [{"material_code": "PET", "contamination_kg": 50}],
    }).json()
    assert r1["rule_version"] == "v2026.1"
    net_v1 = r1["result"]["net_payable"]

    # 切换到更严格的 v2026.2-draft（PET 扣费 1.44，阈值 0.064）
    rules = client.get("/api/rules", params={"region": "EAST_CN"}).json()["items"]
    draft = next(r for r in rules if r["version"] == "v2026.2-draft")
    activated = client.post(f"/api/rules/{draft['id']}/activate")
    assert activated.status_code == 200
    regions = client.get("/api/rules/regions").json()["items"]
    east = next(r for r in regions if r["region"] == "EAST_CN")
    assert east["active_version"] == "v2026.2-draft"

    # 新判定单使用新版本
    r2 = client.post("/api/decisions", json={
        "batch_no": "BATCH-VER-2", "region": "EAST_CN", "weight_kg": 1000,
        "items": [{"material_code": "PET", "contamination_kg": 50}],
    }).json()
    assert r2["rule_version"] == "v2026.2-draft"
    assert r2["result"]["per_material"][0]["deduct_price_per_kg"] == 1.44
    assert r2["result"]["net_payable"] != net_v1

    # 历史判定单结论与快照不变
    old = client.get(f"/api/decisions/{r1['decision_no']}").json()
    assert old["rule_version"] == "v2026.1"
    assert old["rule_snapshot"]["materials"]["PET"]["deduct_price_per_kg"] == 1.2
    assert old["result"]["net_payable"] == net_v1

    # 仍可显式指定历史版本出具
    r3 = client.post("/api/decisions", json={
        "batch_no": "BATCH-VER-3", "region": "EAST_CN", "weight_kg": 1000,
        "items": [{"material_code": "PET", "contamination_kg": 50}],
        "rule_version": "v2026.1",
    }).json()
    assert r3["rule_version"] == "v2026.1"


def test_region_without_active_rule(client):
    resp = client.post("/api/decisions", json={
        "batch_no": "BATCH-NOREG", "region": "MARS", "weight_kg": 100,
        "items": [{"material_code": "PET", "contamination_kg": 1}],
    })
    assert resp.status_code == 422
    assert any("没有生效中的规则" in e["message"] for e in resp.json()["errors"])


def test_create_rule_validation_and_duplicate(client):
    body = {"version": "v2027.1", "region": "SOUTH_CN",
            "content": {"base_price_per_kg": 3.0, "materials": {}, "levels": [], "conclusions": {}},
            "note": "bad"}
    resp = client.post("/api/rules", json=body)
    assert resp.status_code == 422

    ok = client.post("/api/rules", json={
        "version": "v2099.1", "region": "SOUTH_CN",
        "content": {
            "base_price_per_kg": 2.8, "currency": "CNY", "reject_pays_zero": True,
            "max_total_contamination_rate": 0.25,
            "materials": {"PET": {"name": "PET瓶", "deduct_price_per_kg": 1.5,
                                  "max_allowable_rate": 0.07, "level_rates": {}}},
            "levels": [{"code": "A", "name": "轻微", "max_rate": 0.05},
                       {"code": "B", "name": "一般", "max_rate": 1.0}],
            "conclusions": {"ACCEPT": {"code": "ACCEPT", "label": "接收", "grades": ["A"]},
                            "ACCEPT_FEE": {"code": "ACCEPT_FEE", "label": "扣费", "grades": ["B"]},
                            "REJECT": {"code": "REJECT", "label": "拒收", "grades": []}},
        },
        "note": "测试新版本", "activate": False,
    })
    assert ok.status_code == 201, ok.text

    dup = client.post("/api/rules", json=ok.json() | {"note": "dup"})
    assert dup.status_code == 422


def test_csv_export(client):
    client.post("/api/decisions", json={
        "batch_no": "BATCH-CSV", "region": "SOUTH_CN", "weight_kg": 500,
        "items": [{"material_code": "GLASS", "contamination_kg": 2}],
    })
    resp = client.get("/api/decisions/export/csv", params={"batch_no": "BATCH-CSV"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    rows = list(csv.reader(io.StringIO(resp.text.lstrip("﻿"))))
    assert rows[0][0] == "decision_no"
    assert len(rows) >= 2
    assert rows[1][1] == "BATCH-CSV"


def test_audit_logs_present(client):
    resp = client.get("/api/audit-logs", params={"action": "decision.create", "limit": 5})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    switch_logs = client.get("/api/audit-logs", params={"action": "rule.activate"}).json()
    assert switch_logs["total"] >= 1
