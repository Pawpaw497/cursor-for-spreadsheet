"""AgentProjectPlanRequest.clarificationReply merges into AgentState.messages."""
from __future__ import annotations

from app.agent import initial_state_from_agent_project_request
from app.models.plan import AgentProjectPlanRequest, ConversationTurn, TableInfo


def _single_table_request(**overrides) -> AgentProjectPlanRequest:
    base = {
        "prompt": "add total column",
        "tables": [
            {
                "name": "Sheet1",
                "schema": [{"key": "a", "type": "string"}],
                "sampleRows": [{"a": "1"}],
            }
        ],
        "history": [],
        "modelSource": "cloud",
    }
    base.update(overrides)
    return AgentProjectPlanRequest.model_validate(base)


def test_clarification_reply_appended_before_current_user_message() -> None:
    req = _single_table_request(
        prompt="add total column",
        history=[
            ConversationTurn(
                role="assistant",
                content="[Clarification] Which table?\nctx",
            )
        ],
        clarificationReply="Sheet2",
    )
    state = initial_state_from_agent_project_request(req)
    roles = [m["role"] for m in state.messages]
    contents = [m["content"] for m in state.messages]
    assert roles == ["assistant", "user", "user"]
    assert contents[1] == "Sheet2"
    assert "add total column" in contents[-1]
    assert state.user_prompt == "add total column"


def test_clarification_reply_strips_prompt_suffix() -> None:
    req = _single_table_request(
        prompt="add total\n\n[Clarification]\nSheet2",
        clarificationReply="Sheet2",
    )
    state = initial_state_from_agent_project_request(req)
    assert state.user_prompt == "add total"
    assert "add total" in state.messages[-1]["content"]


def test_clarification_reply_skips_duplicate_trailing_history_user() -> None:
    req = _single_table_request(
        prompt="add total",
        history=[ConversationTurn(role="user", content="Sheet2")],
        clarificationReply="Sheet2",
    )
    state = initial_state_from_agent_project_request(req)
    user_turns = [m for m in state.messages if m["role"] == "user"]
    assert len(user_turns) == 2
    assert user_turns[0]["content"] == "Sheet2"


def test_clarification_turn_id_accepted_without_effect() -> None:
    """Optional turn id is stored on request only; state build unchanged."""
    req = _single_table_request(
        clarificationReply="Sheet1",
        clarificationTurnId="turn-abc-123",
    )
    state = initial_state_from_agent_project_request(req)
    assert req.clarificationTurnId == "turn-abc-123"
    assert any(m.get("content") == "Sheet1" for m in state.messages)
