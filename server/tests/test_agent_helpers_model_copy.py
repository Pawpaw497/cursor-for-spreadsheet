"""Stage 0: agent_helpers must use model_copy so optional state fields survive turns."""
from __future__ import annotations

from unittest.mock import patch

from app.agent.actions import CallToolAction, CallToolPayload
from app.agent.agent_helpers import run_tool_and_append_messages, state_after_turn
from app.models.agent_models import AgentState, TableContext


def _state_with_request_context() -> AgentState:
    return AgentState(
        tables=[
            TableContext(
                name="Sheet1",
                schema=[{"key": "a", "type": "string"}],
            )
        ],
        messages=[{"role": "user", "content": "hello"}],
        user_prompt="hello",
        request_context={"selection": {"table": "Sheet1", "cells": ["A1"]}},
    )


def test_state_after_turn_preserves_request_context() -> None:
    state = _state_with_request_context()
    next_state = state_after_turn(state)
    assert next_state.current_turn == state.current_turn + 1
    assert next_state.request_context == state.request_context


def test_run_tool_and_append_messages_preserves_request_context() -> None:
    state = _state_with_request_context()
    action = CallToolAction(
        payload=CallToolPayload(
            tool_name="get_schema",
            tool_args={"table_name": "Sheet1"},
        )
    )
    with patch("app.services.tools.run_tool", return_value="[]"):
        next_state = run_tool_and_append_messages(state, action)

    assert next_state.current_turn == state.current_turn + 1
    assert next_state.request_context == state.request_context
    assert len(next_state.messages) == len(state.messages) + 2
