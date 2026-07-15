"""SSE event ordering and PA routing for stream_agent_events."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.actions import (
    AskClarificationAction,
    CallToolAction,
    CallToolPayload,
    ClarificationPayload,
    FinishAction,
    FinishPayload,
    OutputPlanAction,
)
from app.agent.orchestrator import agent_react_step, stream_agent_events
from app.models.agent_models import AgentState, TableContext
from app.models.plan import Plan


def _agent_state() -> AgentState:
    return AgentState(
        tables=[
            TableContext(
                name="Sheet1",
                schema=[{"key": "a", "type": "string"}],
            )
        ],
        messages=[],
        user_prompt="test",
        max_turns=10,
    )


def _parse_sse_events(chunks: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for chunk in chunks:
        m_event = re.search(r"event: (\w+)", chunk)
        m_data = re.search(r"data: (.+)", chunk)
        if m_event and m_data:
            out.append((m_event.group(1), json.loads(m_data.group(1))))
    return out


def _terminal_events(names: list[str]) -> list[str]:
    terminals = {"plan_done", "preview_ready", "clarification", "finish"}
    return [n for n in names if n in terminals]


def _assert_tool_call_before_result(events: list[tuple[str, dict[str, Any]]]) -> None:
    pending_tool: str | None = None
    for name, data in events:
        if name == "tool_call":
            assert pending_tool is None, "nested tool_call without tool_result"
            pending_tool = data["tool"]
        elif name == "tool_result":
            assert pending_tool is not None, "tool_result without preceding tool_call"
            assert data["tool"] == pending_tool
            pending_tool = None
    assert pending_tool is None, "stream ended with open tool_call"


def _assert_terminal_exclusivity(events: list[tuple[str, dict[str, Any]]]) -> None:
    names = [n for n, _ in events]
    terminals = _terminal_events(names)
    if not terminals:
        return
    if "preview_ready" in terminals:
        idx = names.index("preview_ready")
        assert names[idx + 1 :] == ["plan_done"] or names[idx + 1 :] == []
        assert terminals == ["preview_ready", "plan_done"]
        return
    assert len(terminals) == 1


@pytest.mark.parametrize(
    "actions",
    [
        [
            CallToolAction(
                payload=CallToolPayload(
                    tool_name="get_table_schema",
                    tool_args={"table": "Sheet1"},
                )
            ),
            OutputPlanAction(
                payload=Plan.model_validate(
                    {
                        "intent": "ok",
                        "steps": [
                            {"action": "add_column", "name": "x", "expression": "1"},
                        ],
                    }
                )
            ),
        ],
        [
            AskClarificationAction(
                payload=ClarificationPayload(
                    question="Which sheet?",
                    options=["Sheet1"],
                    context="ambiguous",
                )
            ),
        ],
        [FinishAction(FinishPayload(reason="user_stop"))],
    ],
    ids=["tool_then_plan", "clarification", "finish"],
)
def test_stream_sse_ordering(actions: list) -> None:
    async def run() -> None:
        state = _agent_state()
        action_iter = iter(actions)

        async def mock_step(s: AgentState, *, use_tools: bool = True):
            return s, next(action_iter)

        chunks: list[str] = []
        with patch(
            "app.agent.orchestrator.agent_react_step",
            side_effect=mock_step,
        ):
            async for chunk in stream_agent_events(state, preview_lifecycle=False):
                chunks.append(chunk)

        events = _parse_sse_events(chunks)
        _assert_tool_call_before_result(events)
        _assert_terminal_exclusivity(events)

    asyncio.run(run())


def test_stream_agent_events_uses_pa_decision_step() -> None:
    async def run() -> None:
        state = _agent_state()
        plan = Plan.model_validate(
            {
                "intent": "ok",
                "steps": [{"action": "add_column", "name": "x", "expression": "1"}],
            }
        )

        async def mock_pa(s: AgentState, *, use_tools: bool = True):
            return s, OutputPlanAction(payload=plan)

        with patch(
            "app.agent.orchestrator.pa_decision_step",
            side_effect=mock_pa,
        ) as m_pa:
            chunks: list[str] = []
            async for chunk in stream_agent_events(state, preview_lifecycle=False):
                chunks.append(chunk)

        assert m_pa.await_count >= 1
        events = _parse_sse_events(chunks)
        assert any(name == "plan_done" for name, _ in events)

    asyncio.run(run())


def test_agent_react_step_delegates_to_pa_decision_step() -> None:
    state = _agent_state()
    plan = Plan.model_validate(
        {"intent": "x", "steps": [{"action": "add_column", "name": "c", "expression": "1"}]}
    )

    async def run() -> None:
        with patch(
            "app.agent.orchestrator.pa_decision_step",
            new=AsyncMock(return_value=(state, OutputPlanAction(payload=plan))),
        ) as m_pa:
            await agent_react_step(state, use_tools=True)
        m_pa.assert_awaited_once()

    asyncio.run(run())
