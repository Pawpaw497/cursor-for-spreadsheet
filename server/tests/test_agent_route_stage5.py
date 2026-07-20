"""Stage 5 路径统一：legacy plan 路由已删；单表统一走 upload → tableRef → /api/agent。"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.agent.pa_decision import PaTurnResult
from app.models.plan import Plan


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_legacy_plan_routes_removed(client: TestClient) -> None:
    for path in ("/api/plan", "/api/plan-project", "/api/projects/p1/plan"):
        resp = client.post(path, json={})
        assert resp.status_code in (404, 405), f"{path} still routed: {resp.status_code}"


def test_single_table_agent_flow_includes_full_data_profile(client: TestClient) -> None:
    rows = [{"a": f"v{i}"} for i in range(30)]
    upload = client.post(
        "/api/data/upload",
        json={"name": "Sheet1", "schema": [{"key": "a", "type": "string"}], "rows": rows},
    )
    assert upload.status_code == 200, upload.text
    table_ref = upload.json()["tableId"]

    plan = Plan.model_validate(
        {
            "intent": "x",
            "steps": [{"action": "add_column", "name": "c", "expression": "1"}],
        }
    )
    captured: list[list[Any]] = []

    async def fake_turn(agent: Any, *, user_prompt: Any, message_history: Any, deps: Any) -> PaTurnResult:
        captured.append(list(message_history))
        return PaTurnResult(tool_parts=[], text="", structured_plan=plan)

    body = {
        "prompt": "add column",
        "tables": [
            {
                "name": "Sheet1",
                "schema": [{"key": "a", "type": "string"}],
                "tableRef": table_ref,
            }
        ],
        "modelSource": "cloud",
        "previewLifecycle": False,
    }
    with patch("app.agent.pa_decision._run_pa_single_turn", new=fake_turn):
        resp = client.post("/api/agent", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"]["steps"]

    assert captured, "PA turn not invoked"
    texts = [str(m) for m in captured[0]]
    profile_texts = [t for t in texts if "Data profile" in t]
    assert profile_texts, "Data profile message missing from LLM history"
    assert any("30 rows" in t for t in profile_texts), "total_row_count should be full-table (30)"
    assert not any("Sample rows" in t or "Column statistics" in t for t in texts)
