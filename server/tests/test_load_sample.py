"""Smoke tests for lean test-data/sample.xlsx used by /api/load-sample."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_load_sample_returns_three_lean_tables() -> None:
    client = TestClient(app)
    resp = client.get("/api/load-sample")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("projectId")
    tables = {t["name"]: t for t in data["tables"]}
    assert set(tables) == {"销售订单", "产品信息", "部门预算"}

    sales = tables["销售订单"]
    assert len(sales["rows"]) == 14
    assert len(sales["schema"]) == 6
    dup_o1 = [r for r in sales["rows"] if r["订单号"] == "O1"]
    assert len(dup_o1) == 2
    assert any(r["客户"].strip() != r["客户"] for r in sales["rows"])
    assert any("2024" in str(r["订单日期"]) for r in sales["rows"])
    assert any("2024" not in str(r["订单日期"]) for r in sales["rows"])

    products = {r["产品名称"] for r in tables["产品信息"]["rows"]}
    order_products = {r["产品"] for r in sales["rows"]}
    assert order_products <= products

    budget = tables["部门预算"]
    assert len(budget["rows"]) == 5
    assert len(budget["rows"]) <= 10
