"""Pydantic AI single-step agent decision (Approach A — LangGraph owns tool execution).

Uses ``Agent.iter()`` and stops at ``CallToolsNode`` before PA executes spreadsheet tools.
Structured ``Plan`` output uses pydantic-ai ``output_type=Plan`` (``final_result`` tool part).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from app.agent.actions import (
    AgentAction,
    AskClarificationAction,
    CallToolAction,
    CallToolPayload,
    ClarificationPayload,
    FinishAction,
    FinishPayload,
    OutputPlanAction,
)
from app.agent.agent_helpers import state_after_turn, state_with_user_feedback
from app.agent.clarification import maybe_need_clarification
from app.agent.clarification_telemetry import log_clarification_issued
from app.agent.pa_state import (
    build_pa_message_history,
    system_instructions_for_state,
    user_prompt_for_pa_run,
)
from app.agent.pa_tools import (
    ASK_USER_TOOL_NAME,
    PA_OUTPUT_TOOL_NAME,
    PaAgentDeps,
    register_pa_agent_tools,
)
from app.agent.tool_call_args import coerce_tool_call_args
from app.agent.state import AgentState
from app.config import settings
from app.logging_config import get_logger
from app.models.plan import Plan
from app.services.audit_log import schedule_record_llm_call
from app.services.llm_debug_log import build_error_payload, build_result_payload
from app.services.llm_pydantic_ai import create_pa_agent, resolve_pa_model
from app.services.prompts import Message, ProjectPrompt, SpreadsheetPrompt, extract_json

log = get_logger("agent.pa_decision")


@dataclass(frozen=True, slots=True)
class PaTurnResult:
    """One PA model turn before LangGraph tool execution."""

    tool_parts: list[ToolCallPart]
    text: str
    structured_plan: Plan | None
    final_result_error: str | None = None


def _coerce_plan_from_final_result_args(args: Any) -> Plan:
    """Accept Plan | dict | JSON string from pydantic-ai final_result."""
    if isinstance(args, Plan):
        return args
    if isinstance(args, dict):
        return Plan.model_validate(args)
    if isinstance(args, str):
        json_text = extract_json(args.strip())
        parsed = json.loads(json_text)
        return Plan.model_validate(parsed)
    return Plan.model_validate(args)


def _truncate_for_log(text: str, limit: int = 200) -> str:
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _pa_audit_messages(
    history: list[Any],
    user_prompt: str | None,
) -> list[dict[str, Any]]:
    from app.services.llm_debug_log import prepare_messages_for_log

    msgs: list[Any] = list(history or [])
    if user_prompt:
        msgs.append({"role": "user", "content": user_prompt})
    return prepare_messages_for_log(msgs)


def _pa_turn_result_payload(turn: PaTurnResult) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if turn.text.strip():
        payload.update(build_result_payload(content=turn.text))
    if turn.structured_plan is not None:
        plan = turn.structured_plan
        payload["structured_plan"] = {
            "step_count": len(plan.steps),
            "goal": getattr(plan, "goal", None),
        }
    if turn.tool_parts:
        payload["tool_calls"] = [
            {"name": p.tool_name, "id": p.tool_call_id} for p in turn.tool_parts
        ]
    if turn.final_result_error:
        payload["final_result_error"] = turn.final_result_error
    return payload or {"status": "ok"}


def _schedule_pa_turn_audit(
    *,
    state: AgentState,
    duration_ms: float,
    messages: list[dict[str, Any]],
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    resolved = resolve_pa_model(
        state.model_source,
        cloud_model_id=state.cloud_model_id,
        local_model_id=state.local_model_id,
    )
    schedule_record_llm_call(
        call_kind="pa_turn",
        model_source=resolved.source,
        model=resolved.model,
        duration_ms=duration_ms,
        messages=messages,
        result=result,
        error=error,
    )


def partition_tool_calls(
    parts: list[ToolCallPart],
) -> tuple[list[ToolCallPart], Plan | None, str | None]:
    """Split spreadsheet tools from pydantic-ai ``final_result`` (structured Plan)."""
    regular: list[ToolCallPart] = []
    plan: Plan | None = None
    final_result_error: str | None = None
    for part in parts:
        if part.tool_name == PA_OUTPUT_TOOL_NAME:
            try:
                plan = _coerce_plan_from_final_result_args(part.args)
            except Exception as e:
                log.warning("pa_decision final_result validation failed err=%s", e)
                if plan is None:
                    final_result_error = _truncate_for_log(str(e))
        else:
            regular.append(part)
    if plan is not None:
        final_result_error = None
    return regular, plan, final_result_error


def _extract_model_turn(run: Any) -> PaTurnResult:
    """Read tool calls, text, and structured plan from the latest model response."""
    for message in reversed(run.all_messages()):
        if isinstance(message, ModelResponse):
            tools = [p for p in message.parts if isinstance(p, ToolCallPart)]
            text = "".join(
                p.content for p in message.parts if isinstance(p, TextPart)
            )
            regular, plan, final_result_error = partition_tool_calls(tools)
            return PaTurnResult(
                tool_parts=regular,
                text=text,
                structured_plan=plan,
                final_result_error=final_result_error,
            )
    return PaTurnResult(tool_parts=[], text="", structured_plan=None)


async def _run_pa_single_turn(
    agent: Agent[PaAgentDeps, Plan],
    *,
    user_prompt: str | None,
    message_history: list[Any],
    deps: PaAgentDeps,
) -> PaTurnResult:
    """One model generation; stop at CallToolsNode without executing tools (Approach A)."""
    async with agent.iter(
        user_prompt,
        message_history=message_history or None,
        deps=deps,
    ) as run:
        async for node in run:
            if Agent.is_call_tools_node(node):
                return _extract_model_turn(run)
    return _extract_model_turn(run)


def _build_pa_agent(state: AgentState, *, use_tools: bool) -> Agent[PaAgentDeps, Plan]:
    agent = create_pa_agent(
        state.model_source,
        cloud_model_id=state.cloud_model_id,
        local_model_id=state.local_model_id,
        instructions=system_instructions_for_state(state),
        result_type=Plan,
    )
    if use_tools:
        register_pa_agent_tools(agent)
    return agent


async def _finish_from_structured_plan(
    state: AgentState, plan: Plan
) -> tuple[AgentState, AgentAction]:
    """Terminal path when pydantic-ai returns ``final_result`` / ``Plan`` output."""
    try:
        validated = Plan.model_validate(plan.model_dump())
    except Exception as e:
        log.error("pa_decision structured plan validation failed err=%s", e)
        return (
            state,
            FinishAction(FinishPayload(reason=f"plan_validation_failed: {e!s}")),
        )

    clarify = maybe_need_clarification(state, validated)
    if clarify is not None:
        log_clarification_issued(clarify.payload, source="post_plan_rule")
        next_state = state_after_turn(state)
        return (next_state, clarify)

    next_state = state_after_turn(state)
    return (next_state, OutputPlanAction(payload=validated))


async def _finish_from_plan_text(
    state: AgentState, content: str
) -> tuple[AgentState, AgentAction]:
    """Legacy JSON text fallback when ``AGENT_PA_PLAN_JSON_FALLBACK`` is enabled."""
    retry_user_suffix = "\nReturn ONLY JSON."
    if not (content or "").strip():
        return (state, FinishAction(FinishPayload(reason="empty_response")))

    json_text = extract_json(content)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        preview = (json_text[:200] + "…") if len(json_text) > 200 else json_text
        log.warning(
            "pa_decision json parse failed first_try err=%s preview=%s", e, preview
        )
        if len(state.tables) == 1:
            prompt = SpreadsheetPrompt()
            t = state.tables[0]
            user_content = (
                prompt.build_user_content(
                    state.user_prompt, t.schema, t.sample_rows
                )
                + retry_user_suffix
            )
        else:
            prompt = ProjectPrompt()
            tables_data = [
                {
                    "name": t.name,
                    "schema": t.schema,
                    "sampleRows": t.sample_rows,
                }
                for t in state.tables
            ]
            user_content = (
                prompt.build_user_content(state.user_prompt, tables_data)
                + retry_user_suffix
            )
        retry_messages = [
            Message.system(prompt.system),
            Message.user(user_content),
        ]
        from app.services.llm import call_llm

        try:
            retry_content = await call_llm(
                model_source=state.model_source,
                messages=[m.to_dict() for m in retry_messages],
                cloud_model_id=state.cloud_model_id,
                local_model_id=state.local_model_id,
            )
        except (ValueError, RuntimeError) as err:
            return (
                state,
                FinishAction(FinishPayload(reason=f"llm_retry_error: {err!s}")),
            )
        json_text = extract_json(retry_content or "")
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as err:
            log.error(
                "pa_decision json parse failed after_retry err=%s raw_preview=%s",
                err,
                _truncate_for_log(retry_content or ""),
            )
            return (
                state,
                FinishAction(FinishPayload(reason=f"invalid_json: {err!s}")),
            )

    try:
        plan = Plan.model_validate(parsed)
    except Exception as e:
        log.error("pa_decision plan validation failed err=%s", e)
        return (
            state,
            FinishAction(FinishPayload(reason=f"plan_validation_failed: {e!s}")),
        )

    return await _finish_from_structured_plan(state, plan)


async def _finish_terminal_turn(
    state: AgentState,
    turn: PaTurnResult,
) -> tuple[AgentState, AgentAction]:
    if turn.structured_plan is not None:
        return await _finish_from_structured_plan(state, turn.structured_plan)
    if turn.final_result_error:
        return (
            state,
            FinishAction(
                FinishPayload(
                    reason=f"plan_validation_failed: {turn.final_result_error}"
                )
            ),
        )
    if turn.text.strip() and settings.AGENT_PA_PLAN_JSON_FALLBACK:
        return await _finish_from_plan_text(state, turn.text)
    if not turn.text.strip():
        return (state, FinishAction(FinishPayload(reason="empty_response")))
    return (
        state,
        FinishAction(
            FinishPayload(
                reason="structured_plan_missing: enable AGENT_PA_PLAN_JSON_FALLBACK"
            )
        ),
    )


async def pa_decision_step(
    state: AgentState,
    *,
    use_tools: bool = True,
) -> tuple[AgentState, AgentAction]:
    """PA-backed single ReAct step for LangGraph ``llm_decide`` and SSE."""
    if state.current_turn >= state.max_turns:
        return (state, FinishAction(FinishPayload(reason="max_turns")))

    deps = PaAgentDeps(tables=list(state.tables))
    agent = _build_pa_agent(state, use_tools=use_tools)
    history = build_pa_message_history(state)
    user_prompt = user_prompt_for_pa_run(state)
    audit_messages = _pa_audit_messages(history, user_prompt)
    t0 = time.perf_counter()

    try:
        turn = await _run_pa_single_turn(
            agent,
            user_prompt=user_prompt,
            message_history=history,
            deps=deps,
        )
    except (ValueError, RuntimeError) as e:
        _schedule_pa_turn_audit(
            state=state,
            duration_ms=(time.perf_counter() - t0) * 1000,
            messages=audit_messages,
            error=build_error_payload(e),
        )
        return (state, FinishAction(FinishPayload(reason=f"llm_error: {e!s}")))
    except Exception as e:
        log.exception("pa_decision unexpected error err=%s", e)
        _schedule_pa_turn_audit(
            state=state,
            duration_ms=(time.perf_counter() - t0) * 1000,
            messages=audit_messages,
            error=build_error_payload(e),
        )
        return (state, FinishAction(FinishPayload(reason=f"llm_error: {e!s}")))

    _schedule_pa_turn_audit(
        state=state,
        duration_ms=(time.perf_counter() - t0) * 1000,
        messages=audit_messages,
        result=_pa_turn_result_payload(turn),
    )

    if turn.tool_parts:
        tc = turn.tool_parts[0]
        tool_name = tc.tool_name or ""
        tool_call_id = tc.tool_call_id

        if tool_name == ASK_USER_TOOL_NAME:
            args = coerce_tool_call_args(tool_name, tc.args)
            if args is None:
                log.warning(
                    "pa_decision ask_user arguments invalid id=%s raw_type=%s",
                    tool_call_id,
                    type(tc.args).__name__,
                )
                if state.current_turn + 1 >= state.max_turns:
                    return (
                        state,
                        FinishAction(
                            FinishPayload(
                                reason=(
                                    "invalid_tool_arguments: ask_user: "
                                    "question required"
                                )
                            )
                        ),
                    )
                feedback = (
                    "Tool call ask_user had invalid arguments. "
                    'Use {"question": "...", "options": ["..."], "context": "..."} '
                    "with a non-empty question string."
                )
                retry_state = state_with_user_feedback(state, feedback)
                return await pa_decision_step(retry_state, use_tools=use_tools)

            payload = ClarificationPayload(
                question=str(args["question"]),
                options=args.get("options"),
                context=args.get("context"),
            )
            log_clarification_issued(payload, source="ask_user")
            return (
                state_after_turn(state),
                AskClarificationAction(payload=payload),
            )

        args = coerce_tool_call_args(tool_name, tc.args)
        if args is None:
            log.warning(
                "pa_decision tool arguments invalid tool=%s id=%s raw_type=%s",
                tool_name,
                tool_call_id,
                type(tc.args).__name__,
            )
            if state.current_turn + 1 >= state.max_turns:
                return (
                    state,
                    FinishAction(
                        FinishPayload(
                            reason=f"invalid_tool_arguments: {tool_name}: not a JSON object"
                        )
                    ),
                )
            feedback = (
                f"Tool call {tool_name!r} had invalid arguments. "
                "Use a single JSON object with the required fields from the tool schema; "
                "for validate_expression use exact column keys from the user message "
                '(e.g. {"expression": "row[\'单价\'] * row[\'数量\']"}).'
            )
            retry_state = state_with_user_feedback(state, feedback)
            return await pa_decision_step(retry_state, use_tools=use_tools)

        next_state = state_after_turn(state)
        return (
            next_state,
            CallToolAction(
                payload=CallToolPayload(
                    tool_name=tool_name,
                    tool_args=args,
                    tool_call_id=tool_call_id,
                )
            ),
        )

    return await _finish_terminal_turn(state, turn)
