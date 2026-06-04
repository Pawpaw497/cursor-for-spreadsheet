"""AgentState ↔ LangGraph / Pydantic AI message adapters (Phase 2)."""
from __future__ import annotations

import json
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agent.memory_context import append_memory_to_system_prompt
from app.models.agent_models import AgentState
from app.agent.user_context import build_initial_user_message
from app.services.prompts import ProjectPrompt, SpreadsheetPrompt

# Mirrors orchestrator.AgentGraphState without importing orchestrator (avoid cycles).
AgentGraphDict = dict[str, Any]


def agent_to_graph(agent: AgentState, *, scratch: dict[str, Any] | None = None) -> AgentGraphDict:
    """Serialize AgentState into LangGraph node input."""
    return {"agent": agent.model_dump(), "scratch": dict(scratch or {})}


def graph_to_agent(graph: AgentGraphDict) -> AgentState:
    """Restore AgentState from LangGraph node output."""
    return AgentState.model_validate(graph["agent"])


def system_instructions_for_state(state: AgentState) -> str:
    """System prompt aligned with legacy SpreadsheetPrompt / ProjectPrompt usage."""
    if len(state.tables) == 1:
        base = SpreadsheetPrompt().system
    else:
        base = ProjectPrompt().system
    return append_memory_to_system_prompt(base, state)


def build_pa_message_history(state: AgentState) -> list[ModelMessage]:
    """Convert OpenAI-shaped ``state.messages`` to Pydantic AI ``message_history``.

    System text is supplied via ``Agent`` instructions, not duplicated here.
    """
    if not state.messages:
        return []
    return dict_messages_to_pa_history(state.messages)


def dict_messages_to_pa_history(messages: list[dict[str, Any]]) -> list[ModelMessage]:
    """Map user / assistant / tool dict transcript to PA ``ModelMessage`` list."""
    out: list[ModelMessage] = []
    tool_id_to_name: dict[str, str] = {}

    for m in messages:
        role = m.get("role", "user")
        if role == "user":
            out.append(
                ModelRequest(
                    parts=[UserPromptPart(content=str(m.get("content") or ""))]
                )
            )
            continue

        if role == "assistant":
            parts: list[Any] = []
            content = m.get("content") or ""
            if content:
                parts.append(TextPart(content=str(content)))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                name = str(fn.get("name", ""))
                tid = str(tc.get("id") or "")
                if tid:
                    tool_id_to_name[tid] = name
                raw_args = fn.get("arguments", "{}")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args) if raw_args.strip() else {}
                    except json.JSONDecodeError:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                parts.append(
                    ToolCallPart(
                        tool_name=name,
                        args=args,
                        tool_call_id=tid or None,
                    )
                )
            if parts:
                out.append(ModelResponse(parts=parts))
            continue

        if role == "tool":
            tid = str(m.get("tool_call_id") or "")
            tool_name = tool_id_to_name.get(tid, "unknown_tool")
            out.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=tool_name,
                            content=str(m.get("content") or ""),
                            tool_call_id=tid,
                        )
                    ]
                )
            )

    return out


def user_prompt_for_pa_run(state: AgentState) -> str | None:
    """When transcript is empty, PA ``iter`` needs an explicit user prompt."""
    if state.messages:
        return None
    initial = build_initial_user_message(state)
    return str(initial.get("content") or "")
