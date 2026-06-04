"""Agent message / LLM payload contracts (tool roles, history seeding)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.state import initial_state_from_agent_project_request
from app.models.plan import AgentProjectPlanRequest, ConversationTurn, TableInfo
from app.services import llm as llm_mod


def test_call_llm_dict_openrouter_payload_omits_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_MODEL", "test/model")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}

    client_inst = MagicMock()
    client_inst.post = AsyncMock(return_value=fake_resp)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    async def run() -> None:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=cm):
            await llm_mod.call_llm(
                "cloud",
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [],
                    },
                    {"role": "tool", "tool_call_id": "t1", "content": "hi"},
                ],
            )

    asyncio.run(run())

    body = client_inst.post.call_args.kwargs["json"]
    assert isinstance(body, dict)
    assert "tools" not in body
    assert "tool_choice" not in body
    marshalled = body["messages"]
    assert isinstance(marshalled, list)
    roles = [m.get("role") for m in marshalled]
    assert "tool" in roles


def test_agent_initial_state_appends_current_user_after_history() -> None:
    req = AgentProjectPlanRequest(
        prompt="Add column total_price = price * quantity",
        tables=[
            TableInfo(
                name="Sheet1",
                schema=[
                    {"key": "price", "type": "number"},
                    {"key": "quantity", "type": "number"},
                ],
                sampleRows=[{"price": 10, "quantity": 2}],
            )
        ],
        history=[
            ConversationTurn(role="user", content="prior question"),
            ConversationTurn(role="assistant", content="prior answer"),
        ],
    )
    state = initial_state_from_agent_project_request(req)
    assert len(state.messages) == 3
    assert state.messages[0]["content"] == "prior question"
    assert state.messages[1]["content"] == "prior answer"
    last = state.messages[-1]
    assert last["role"] == "user"
    assert "Spreadsheet schema:" in last["content"]
    assert "total_price" in last["content"]
