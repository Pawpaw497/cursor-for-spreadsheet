"""Shared Agent turn helpers (clarification, state bumps, tool transcript)."""
from __future__ import annotations

import json

from app.agent.actions import CallToolAction
from app.agent.clarification import maybe_need_clarification
from app.agent.state import AgentState
from app.agent.user_context import build_initial_user_message

# Re-export for tests and legacy imports.
__all__ = [
    "maybe_need_clarification",
    "run_tool_and_append_messages",
    "state_after_turn",
    "state_with_user_feedback",
]


def state_after_turn(state: AgentState) -> AgentState:
    """Return state with ``current_turn`` incremented."""
    return state.model_copy(update={"current_turn": state.current_turn + 1})


def state_with_user_feedback(state: AgentState, feedback: str) -> AgentState:
    """Bump turn and append user feedback (e.g. malformed tool args retry)."""
    next_state = state_after_turn(state)
    base_messages = list(next_state.messages)
    if not base_messages:
        base_messages = [build_initial_user_message(state)]
    return next_state.model_copy(
        update={
            "messages": base_messages + [{"role": "user", "content": feedback}],
        }
    )


def run_tool_and_append_messages(
    state: AgentState, action: CallToolAction
) -> AgentState:
    """Run spreadsheet tool and append assistant(tool_calls) + tool rows to messages."""
    from app.services.tools import run_tool

    payload = action.payload
    result = run_tool(
        tool_name=payload.tool_name,
        tool_args=payload.tool_args,
        tables=state.tables,
        data_context=state.data_context,
    )
    tid = payload.tool_call_id or "tool-0"
    assistant_tool_calls = [
        {
            "id": tid,
            "type": "function",
            "function": {
                "name": payload.tool_name,
                "arguments": json.dumps(payload.tool_args),
            },
        }
    ]
    base_messages = list(state.messages)
    if not base_messages:
        base_messages = [build_initial_user_message(state)]
    new_messages = base_messages + [
        {"role": "assistant", "content": "", "tool_calls": assistant_tool_calls},
        {"role": "tool", "tool_call_id": tid, "content": result},
    ]
    return state.model_copy(
        update={
            "messages": new_messages,
            "current_turn": state.current_turn + 1,
        }
    )
