"""POST /api/agent maps ask_clarification to clarification JSON (no real LLM)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent import initial_state_from_agent_project_request
from app.agent.actions import AskClarificationAction, ClarificationPayload
from app.main import app
from app.models.plan import AgentProjectPlanRequest


@pytest.fixture()
def client() -> TestClient:
    """提供同步 HTTP 客户端。"""
    return TestClient(app)


def _two_table_agent_body() -> dict:
    table = {
        "schema": [{"key": "a", "type": "string"}],
        "sampleRows": [{"a": "x"}],
    }
    return {
        "prompt": "add a column named x",
        "tables": [
            {"name": "Sheet1", **table},
            {"name": "Sheet2", **table},
        ],
        "history": [],
        "previewLifecycle": False,
    }


def test_agent_returns_clarification_kind(client: TestClient) -> None:
    """_map_agent_result_to_response exposes kind=clarification without plan."""
    body = _two_table_agent_body()
    req = AgentProjectPlanRequest.model_validate(body)
    state = initial_state_from_agent_project_request(req)
    question = "Which table should receive the new column?"
    action = AskClarificationAction(
        payload=ClarificationPayload(
            question=question,
            options=["Sheet1", "Sheet2"],
            context="Ambiguous steps: add_column missing table",
        )
    )

    async def mock_run(*_args, **_kwargs):
        return state, action

    with patch(
        "app.api.routes.agent.run_agent_orchestrated",
        new=AsyncMock(side_effect=mock_run),
    ):
        resp = client.post("/api/agent", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "clarification"
    assert data.get("plan") is None
    assert data["clarification"]["question"] == question
    assert data["clarification"]["options"] == ["Sheet1", "Sheet2"]
    ctx = data["clarification"].get("context")
    assert ctx
    assert "Ambiguous" in ctx
