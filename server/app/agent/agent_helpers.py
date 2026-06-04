"""Shared Agent turn helpers (clarification, state bumps, tool transcript)."""
from __future__ import annotations

import json

from app.agent.actions import (
    AskClarificationAction,
    CallToolAction,
    ClarificationPayload,
)
from app.agent.state import AgentState
from app.agent.user_context import build_initial_user_message
from app.models.plan import Plan


def state_after_turn(state: AgentState) -> AgentState:
    """Return state with ``current_turn`` incremented."""
    return AgentState(
        tables=state.tables,
        messages=state.messages,
        applied_plans_summary=state.applied_plans_summary,
        conversation=state.conversation,
        preview_history=state.preview_history,
        revision_count=state.revision_count,
        last_execution_error=state.last_execution_error,
        current_turn=state.current_turn + 1,
        max_turns=state.max_turns,
        user_prompt=state.user_prompt,
        model_source=state.model_source,
        cloud_model_id=state.cloud_model_id,
        local_model_id=state.local_model_id,
    )


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


def maybe_need_clarification(
    state: AgentState,
    plan: Plan,
) -> AskClarificationAction | None:
    """Multi-table: ask when add_column/transform_column steps omit ``table``."""
    table_names = [t.name for t in state.tables]
    if len(table_names) <= 1:
        return None

    ambiguous_steps: list[str] = []
    for idx, step in enumerate(plan.steps):
        action = getattr(step, "action", None)
        table = getattr(step, "table", None)
        if action in ("add_column", "transform_column") and not table:
            desc = f"#{idx}: {action}"
            col = getattr(step, "column", None) or getattr(step, "name", None)
            if col:
                desc += f" on {col}"
            ambiguous_steps.append(desc)

    if not ambiguous_steps:
        return None

    question = (
        "Multiple tables detected, but some steps do not specify which table "
        "to apply to. Which table should these steps target?"
    )
    context = (
        "Ambiguous steps:\n- " + "\n- ".join(ambiguous_steps)
        + "\nAvailable tables: " + ", ".join(table_names)
    )
    payload = ClarificationPayload(
        question=question,
        options=table_names,
        context=context,
    )
    return AskClarificationAction(payload=payload)


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
    return AgentState(
        tables=state.tables,
        messages=new_messages,
        applied_plans_summary=state.applied_plans_summary,
        conversation=state.conversation,
        preview_history=state.preview_history,
        revision_count=state.revision_count,
        last_execution_error=state.last_execution_error,
        current_turn=state.current_turn + 1,
        max_turns=state.max_turns,
        user_prompt=state.user_prompt,
        model_source=state.model_source,
        cloud_model_id=state.cloud_model_id,
        local_model_id=state.local_model_id,
    )
