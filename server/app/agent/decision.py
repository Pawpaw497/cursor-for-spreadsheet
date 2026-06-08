"""Legacy OpenAI-shaped message assembly for Agent LLM calls.

Production Agent decisions use ``pa_decision``; this module keeps
``_build_messages_dict_from_state`` for JSON fallback paths and tests.
"""
from __future__ import annotations

from typing import Any

from app.agent.context_assembler import selection_context_user_message
from app.agent.memory_context import append_memory_to_system_prompt
from app.agent.user_context import build_initial_user_message_from_tables
from app.models.agent_models import AgentState
from app.services.prompts import ProjectPrompt, SpreadsheetPrompt


def _system_content_for_state(state: AgentState) -> str:
    if len(state.tables) == 1:
        base = SpreadsheetPrompt().system
    else:
        base = ProjectPrompt().system
    return append_memory_to_system_prompt(base, state)


def _build_messages_dict_from_state(state: AgentState) -> list[dict[str, Any]]:
    """Build OpenAI-compatible messages with memory injected into system content."""
    system_content = _system_content_for_state(state)
    out: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    if not state.messages:
        selection_msg = selection_context_user_message(state.request_context)
        if selection_msg is not None:
            out.append(selection_msg)
        out.append(build_initial_user_message_from_tables(state.user_prompt, state.tables))
        return out

    for m in state.messages:
        msg: dict[str, Any] = {
            "role": m.get("role", "user"),
            "content": m.get("content", "") or "",
        }
        if m.get("tool_calls") is not None:
            msg["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id") is not None:
            msg["tool_call_id"] = m["tool_call_id"]
        out.append(msg)
    return out
