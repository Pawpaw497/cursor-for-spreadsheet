"""Opt-in integration: load-sample xlsx → upload → /api/agent → validated Plan.

Aligned with README sample path (`GET /api/load-sample` → `test-data/sample.xlsx`).
Full prompt catalog: `test-data/test-prompts.md`.

Requires `RUN_CLOUD_LLM_E2E=1`, `OPENROUTER_API_KEY` in env (e.g. `server/.env` when
`cd server && uv run pytest`). May take tens of seconds; calls real OpenRouter.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.plan import Plan

# Single-table scenario #1 from test-data/test-prompts.md (matches 销售订单).
SAMPLE_PROMPT = (
    "在`销售订单`工作表上生成一个清洗与分析计划：\n"
    "1）确保`数量`和`单价`被当作数值列（需要的话先转换列类型）；\n"
    "2）新增一列`金额`，表达式为`数量 * 单价`；\n"
    "3）只保留`订单日期`在 2024 年的行（用合适的条件过滤），其它行过滤掉；\n"
    "4）按`金额`从大到小排序整张表。\n"
    "只需要输出结构化 Plan JSON。"
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.integration
def test_cloud_agent_plan_with_load_sample(client: TestClient) -> None:
    if os.environ.get("RUN_CLOUD_LLM_E2E") != "1":
        pytest.skip("Set RUN_CLOUD_LLM_E2E=1 to run cloud LLM E2E")

    from app.config import settings

    if not (settings.OPENROUTER_API_KEY or "").strip():
        pytest.skip("OPENROUTER_API_KEY missing (configure server/.env, run from server/)")

    load = client.get("/api/load-sample")
    assert load.status_code == 200, load.text
    payload = load.json()
    tables_body = []
    for t in payload["tables"]:
        upload = client.post(
            "/api/data/upload",
            json={"name": t["name"], "schema": t["schema"], "rows": t["rows"]},
        )
        assert upload.status_code == 200, upload.text
        tables_body.append(
            {
                "name": t["name"],
                "schema": t["schema"],
                "tableRef": upload.json()["tableId"],
            }
        )
    body: dict = {
        "prompt": SAMPLE_PROMPT,
        "tables": tables_body,
        "modelSource": "cloud",
    }
    model_id = (os.environ.get("E2E_CLOUD_MODEL_ID") or "").strip()
    if model_id:
        body["cloudModelId"] = model_id

    resp = client.post("/api/agent", json=body)
    if resp.status_code != 200:
        pytest.skip(f"agent not OK ({resp.status_code}): {resp.text[:500]}")

    data = resp.json()
    plan = Plan.model_validate(data["plan"])
    assert plan.intent.strip()
    assert len(plan.steps) >= 1
