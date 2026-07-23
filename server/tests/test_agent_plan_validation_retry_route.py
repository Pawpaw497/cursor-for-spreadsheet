"""E2E: final_result Plan validation failure retries within a turn (no real LLM).

Mirrors test_agent_clarification_route.py — real orchestrator + real pa_decision_step,
only ``_run_pa_single_turn`` is mocked. Locks that retrying a malformed final_result
does not change the SSE event sequence / terminal HTTP response shape versus the
non-retry baseline.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent.pa_decision import MAX_PLAN_VALIDATION_RETRIES, PaTurnResult
from app.main import app
from app.models.plan import Plan


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _single_table_agent_body() -> dict:
    return {
        "prompt": "add a column named x",
        "tables": [
            {
                "name": "Sheet1",
                "schema": [{"key": "a", "type": "string"}],
                "sampleRows": [{"a": "x"}],
            }
        ],
        "history": [],
        "previewLifecycle": False,
    }


def _plan() -> Plan:
    return Plan.model_validate(
        {
            "intent": "add x",
            "steps": [{"action": "add_column", "name": "x", "expression": "1"}],
        }
    )


def _null_steps_turn(*, null_count: int = 5) -> PaTurnResult:
    """null_count varies the pydantic error text (index enumeration) so that
    repeated calls in the exhausted-retry test don't collide with the
    same-error short-circuit, which is covered separately in
    test_pa_structured_plan.py."""
    from app.agent.pa_decision import partition_tool_calls
    from pydantic_ai.messages import ToolCallPart

    _, _, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name="final_result",
                args={"intent": "add x", "steps": [None] * null_count},
                tool_call_id="out1",
            )
        ]
    )
    assert err is not None
    return PaTurnResult(tool_parts=[], text="", structured_plan=None, final_result_error=err)


def test_retry_recovers_and_returns_plan_like_no_retry_baseline(
    client: TestClient,
) -> None:
    good_turn = PaTurnResult(tool_parts=[], text="", structured_plan=_plan())

    with patch(
        "app.agent.pa_decision._run_pa_single_turn",
        new=AsyncMock(side_effect=[_null_steps_turn(), good_turn]),
    ) as mock_run:
        resp = client.post("/api/agent", json=_single_table_agent_body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"]["intent"] == "add x"
    assert mock_run.await_count == 2

    with patch(
        "app.agent.pa_decision._run_pa_single_turn",
        new=AsyncMock(return_value=good_turn),
    ):
        baseline_resp = client.post("/api/agent", json=_single_table_agent_body())

    assert baseline_resp.status_code == 200
    assert baseline_resp.json() == data


def test_retry_exhausted_returns_422_plan_validation_failed(
    client: TestClient,
) -> None:
    bad_turns = [
        _null_steps_turn(null_count=5 - i)
        for i in range(1 + MAX_PLAN_VALIDATION_RETRIES)
    ]

    with patch(
        "app.agent.pa_decision._run_pa_single_turn",
        new=AsyncMock(side_effect=bad_turns),
    ) as mock_run:
        resp = client.post("/api/agent", json=_single_table_agent_body())

    assert resp.status_code == 422
    data = resp.json()
    assert data["detail"]["kind"] == "error"
    assert "plan_validation_failed" in data["detail"]["reason"]
    assert mock_run.await_count == 1 + MAX_PLAN_VALIDATION_RETRIES
