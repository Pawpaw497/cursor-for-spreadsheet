"""LangGraph 编排：context_analyzer → intent_analyzer → ReAct（llm_decide ↔ tool_exec）。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from app.agent.actions import (
    AskClarificationAction,
    CallToolAction,
    CallToolPayload,
    ClarificationPayload,
    FinishAction,
    FinishPayload,
    OutputPlanAction,
    PreviewReadyAction,
    PreviewReadyPayload,
    AgentAction,
    action_kind,
)
from app.agent.agent_helpers import run_tool_and_append_messages
from app.agent.memory_compaction import apply_message_compaction
from app.agent.pa_decision import pa_decision_step
from app.agent.state import AgentState
from app.logging_config import get_logger
from app.models.plan import Plan, plan_to_wire_dict, preview_record_to_wire_dict
from app.services.agent_preview import (
    PreviewEvaluationCap,
    PreviewEvaluationReady,
    PreviewEvaluationRevise,
    evaluate_output_plan_preview,
)
from app.services.plan_executor import TableData
from app.agent.sub_agents.context_analyzer import analyze_context
from app.agent.sub_agents.intent_analyzer import analyze_intent

log = get_logger("agent.orchestrator")


async def agent_react_step(
    state: AgentState,
    *,
    use_tools: bool = True,
) -> tuple[AgentState, AgentAction]:
    """Single ReAct LLM turn shared by sync graph ``llm_decide`` and SSE stream."""
    state = apply_message_compaction(state)
    return await pa_decision_step(state, use_tools=use_tools)


class AgentGraphState(TypedDict, total=False):
    """编排器跨节点状态；`scratch` 存路由与终端动作。"""

    agent: dict
    scratch: dict


def _serialize_terminal_action(action: AgentAction) -> dict[str, Any]:
    """将终端动作（非 call_tool）序列化为可放入 GraphState 的 dict。"""
    k = action_kind(action)
    if k == "output_plan":
        a = cast(OutputPlanAction, action)
        return {
            "kind": k,
            "plan": a.payload.model_dump(),
        }
    if k == "ask_clarification":
        a = cast(AskClarificationAction, action)
        p = a.payload
        return {
            "kind": k,
            "question": p.question,
            "options": p.options,
            "context": p.context,
        }
    if k == "finish":
        a = cast(FinishAction, action)
        reason = a.payload.reason if a.payload else "done"
        return {"kind": k, "reason": reason}
    raise ValueError(f"unexpected terminal action: {k}")


def _deserialize_terminal_action(ser: dict[str, Any]) -> AgentAction:
    """从 scratch.ser_action 恢复 AgentAction。"""
    k = ser.get("kind")
    if k == "output_plan":
        return OutputPlanAction(payload=Plan.model_validate(ser["plan"]))
    if k == "ask_clarification":
        p = ClarificationPayload(
            question=ser.get("question", ""),
            options=ser.get("options"),
            context=ser.get("context"),
        )
        return AskClarificationAction(payload=p)
    if k == "finish":
        return FinishAction(FinishPayload(reason=ser.get("reason", "unknown")))
    raise ValueError(f"cannot deserialize action kind {k!r}")


def _node_context(s: AgentGraphState) -> AgentGraphState:
    """context_analyzer：从 store 计算 DataContext 并注入 Data profile 消息。"""
    agent = AgentState.model_validate(s["agent"])
    out = analyze_context(agent)
    return {"agent": out.model_dump(), "scratch": dict(s.get("scratch") or {})}


async def _node_intent(s: AgentGraphState) -> AgentGraphState:
    """intent_analyzer：批量分类回填语义字段并刷新 Data profile 消息。"""
    agent = AgentState.model_validate(s["agent"])
    out = await analyze_intent(agent)
    return {"agent": out.model_dump(), "scratch": dict(s.get("scratch") or {})}


async def _node_llm_decide(s: AgentGraphState) -> AgentGraphState:
    """llm 决策（invoke_llm）：委托共享 ``agent_react_step``。"""
    agent = AgentState.model_validate(s["agent"])
    new_agent, act = await agent_react_step(agent, use_tools=True)
    k = action_kind(act)
    scratch: dict = {}
    if k == "call_tool":
        cta = cast(CallToolAction, act)
        scratch["route"] = "tool"
        scratch["pending_ct"] = {
            "tool_name": cta.payload.tool_name,
            "tool_args": cta.payload.tool_args,
            "tool_call_id": cta.payload.tool_call_id,
        }
    else:
        scratch["route"] = "end"
        scratch["ser_action"] = _serialize_terminal_action(act)
    return {"agent": new_agent.model_dump(), "scratch": scratch}


def _after_llm(s: AgentGraphState) -> str:
    r = s.get("scratch", {}).get("route")
    if r == "tool":
        return "continue"
    return "end"


def _node_tool(s: AgentGraphState) -> AgentGraphState:
    """tool_exec：执行工具并回灌 messages。"""
    agent = AgentState.model_validate(s["agent"])
    p = s.get("scratch", {}).get("pending_ct") or {}
    cta = CallToolAction(
        payload=CallToolPayload(
            tool_name=str(p.get("tool_name", "")),
            tool_args=cast(Any, p.get("tool_args") or {}),
            tool_call_id=cast(Any, p.get("tool_call_id")),
        )
    )
    st2 = run_tool_and_append_messages(agent, cta)
    return {"agent": st2.model_dump(), "scratch": {}}


def build_agent_graph() -> StateGraph:
    """构建并返回未编译的 StateGraph。"""
    g = StateGraph(AgentGraphState)  # type: ignore[valid-type]
    g.add_node("context_analyzer", _node_context)
    g.add_node("intent_analyzer", _node_intent)
    g.add_node("llm_decide", _node_llm_decide)
    g.add_node("tool_exec", _node_tool)
    g.add_edge(START, "context_analyzer")
    g.add_edge("context_analyzer", "intent_analyzer")
    g.add_edge("intent_analyzer", "llm_decide")
    g.add_conditional_edges(
        "llm_decide",
        _after_llm,
        {"continue": "tool_exec", "end": END},
    )
    g.add_edge("tool_exec", "llm_decide")
    return g


_compiled: Optional[Any] = None


def get_compiled_agent_graph() -> Any:
    """单例已编译图。"""
    global _compiled
    if _compiled is None:
        _compiled = build_agent_graph().compile()
    return _compiled


async def run_agent_orchestrated(
    initial: AgentState,
    *,
    preview_lifecycle: bool = False,
    execution_tables: Optional[Dict[str, TableData]] = None,
) -> tuple[AgentState, AgentAction]:
    """运行 LangGraph 编排；可选在 ``output_plan`` 后做服务端 dry-run 并返回 ``preview_ready``。

    当 ``preview_lifecycle`` 为真且提供 ``execution_tables`` 时，在隔离副本上执行 Plan；
    若 dry-run 失败或校验未通过，则在 ``messages`` 中追加反馈并重跑编排直至达到
    ``MAX_AGENT_PREVIEW_REVISIONS``。

    @param initial: 初始 Agent 状态。
    @param preview_lifecycle: 是否启用预览就绪终端动作。
    @param execution_tables: 用于 dry-run 的已提交表快照；缺省时保持 ``output_plan`` 行为。
    @return: 终止状态与终端 ``AgentAction``。
    """
    graph = get_compiled_agent_graph()
    working = initial
    while True:
        init: AgentGraphState = {
            "agent": working.model_dump(),
            "scratch": {},
        }
        final = await graph.ainvoke(init)
        agent_out = AgentState.model_validate(final["agent"])
        ser = (final.get("scratch") or {}).get("ser_action")
        if not ser:
            log.error("orchestrator: missing ser_action in final state %s", final)
            return (
                agent_out,
                FinishAction(FinishPayload(reason="internal_orchestrator_state")),
            )
        action = _deserialize_terminal_action(ser)
        k = action_kind(action)

        if (
            preview_lifecycle
            and k == "output_plan"
            and execution_tables is not None
        ):
            opa = cast(OutputPlanAction, action)
            plan = opa.payload
            preview_eval = evaluate_output_plan_preview(
                agent_out, plan, execution_tables
            )
            if isinstance(preview_eval, PreviewEvaluationRevise):
                working = preview_eval.working_agent
                continue
            if isinstance(preview_eval, PreviewEvaluationCap):
                return (
                    preview_eval.agent,
                    FinishAction(
                        FinishPayload(reason=preview_eval.finish_reason)
                    ),
                )
            ready = cast(PreviewEvaluationReady, preview_eval)
            return (
                ready.agent,
                PreviewReadyAction(
                    PreviewReadyPayload(
                        plan=ready.plan,
                        preview=ready.record,
                        warnings=list(ready.warnings) if ready.warnings else None,
                    )
                ),
            )

        return (agent_out, action)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_agent_events(
    state: AgentState,
    *,
    preview_lifecycle: bool = False,
    execution_tables: Optional[Dict[str, TableData]] = None,
) -> AsyncIterator[str]:
    """SSE via LangGraph ``astream_events``; event names and payloads match the legacy contract.

    Graph nodes ``context_analyzer`` / ``intent_analyzer`` run on each invocation, aligned
    with ``run_agent_orchestrated``. An outer loop handles preview revision the same way as sync.

    @param state: 初始 Agent 状态。
    @param preview_lifecycle: 为真且提供 ``execution_tables`` 时，在 ``plan_done`` 之外额外发送 ``preview_ready``。
    @param execution_tables: 与 ``run_agent_orchestrated`` 相同的 dry-run 表快照。
    """
    graph = get_compiled_agent_graph()
    working = state

    while True:
        if working.current_turn >= working.max_turns:
            yield _sse("finish", {"reason": "max_turns", "state": working.to_dict()})
            return

        init: AgentGraphState = {
            "agent": working.model_dump(),
            "scratch": {},
        }
        terminal_action: AgentAction | None = None
        agent_out = working
        last_tool_name: str | None = None

        async for event in graph.astream_events(init, version="v2"):
            if event.get("event") != "on_chain_end":
                continue
            ev_name = event.get("name")
            if ev_name not in ("llm_decide", "tool_exec"):
                continue

            output = (event.get("data") or {}).get("output") or {}
            if not isinstance(output, dict) or "agent" not in output:
                continue

            agent_out = AgentState.model_validate(output["agent"])
            scratch = output.get("scratch") or {}

            if ev_name == "llm_decide":
                route = scratch.get("route")
                if route == "tool":
                    pending = scratch.get("pending_ct") or {}
                    last_tool_name = str(pending.get("tool_name", ""))
                    yield _sse(
                        "tool_call",
                        {
                            "tool": last_tool_name,
                            "args": pending.get("tool_args"),
                            "state": agent_out.to_dict(),
                        },
                    )
                elif route == "end":
                    ser = scratch.get("ser_action")
                    if ser:
                        terminal_action = _deserialize_terminal_action(ser)
            elif ev_name == "tool_exec" and last_tool_name is not None:
                yield _sse(
                    "tool_result",
                    {"tool": last_tool_name, "state": agent_out.to_dict()},
                )
                last_tool_name = None
                await asyncio.sleep(0)

        if terminal_action is None:
            log.error(
                "stream_agent_events: missing terminal action after graph stream"
            )
            yield _sse(
                "finish",
                {
                    "reason": "internal_orchestrator_state",
                    "state": agent_out.to_dict(),
                },
            )
            return

        kind = action_kind(terminal_action)

        if kind == "output_plan":
            opa = cast(OutputPlanAction, terminal_action)
            plan_obj = opa.payload
            plan_dump = plan_to_wire_dict(plan_obj)
            if preview_lifecycle and execution_tables is not None:
                preview_eval = evaluate_output_plan_preview(
                    agent_out, plan_obj, execution_tables
                )
                if isinstance(preview_eval, PreviewEvaluationRevise):
                    working = preview_eval.working_agent
                    continue
                if isinstance(preview_eval, PreviewEvaluationCap):
                    yield _sse(
                        "finish",
                        {
                            "reason": preview_eval.finish_reason,
                            "state": preview_eval.agent.to_dict(),
                        },
                    )
                    return
                ready = cast(PreviewEvaluationReady, preview_eval)
                agent_out = ready.agent
                preview_payload: dict[str, Any] = {
                    "plan": plan_dump,
                    "preview": preview_record_to_wire_dict(ready.record),
                    "previewHistory": [
                        preview_record_to_wire_dict(h)
                        for h in agent_out.preview_history
                    ],
                    "state": agent_out.to_dict(),
                }
                if ready.warnings:
                    preview_payload["warnings"] = list(ready.warnings)
                yield _sse("preview_ready", preview_payload)
            yield _sse(
                "plan_done",
                {"plan": plan_dump, "state": agent_out.to_dict()},
            )
            return

        if kind == "finish":
            fa = cast(FinishAction, terminal_action)
            reason = (fa.payload and fa.payload.reason) or "unknown"
            yield _sse("finish", {"reason": reason, "state": agent_out.to_dict()})
            return

        if kind == "ask_clarification":
            ap = cast(AskClarificationAction, terminal_action)
            p = ap.payload
            yield _sse(
                "clarification",
                {
                    "question": p.question,
                    "options": p.options,
                    "context": p.context,
                    "state": agent_out.to_dict(),
                },
            )
            return

        log.error("stream_agent_events: unexpected terminal action %s", kind)
        yield _sse(
            "finish",
            {
                "reason": "internal_orchestrator_state",
                "state": agent_out.to_dict(),
            },
        )
        return
