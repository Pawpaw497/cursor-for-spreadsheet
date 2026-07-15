"""Structured Plan output path in pa_decision (final_result / output_type=Plan)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from pydantic_ai.messages import ToolCallPart

from app.agent.actions import AskClarificationAction, FinishAction, OutputPlanAction
from app.agent.pa_decision import PaTurnResult, pa_decision_step, partition_tool_calls
from app.agent.pa_tools import PA_OUTPUT_TOOL_NAME
from app.models.agent_models import AgentState, TableContext
from app.models.plan import Plan


def _plan() -> Plan:
    return Plan.model_validate(
        {
            "intent": "add x",
            "steps": [{"action": "add_column", "name": "x", "expression": "1"}],
        }
    )


def _state(*, tables_count: int = 1) -> AgentState:
    tables = [
        TableContext(
            name="Sheet1",
            schema=[{"key": "a", "type": "string"}],
        )
    ]
    if tables_count > 1:
        tables.append(
            TableContext(name="Sheet2", schema=[{"key": "b", "type": "string"}])
        )
    return AgentState(
        tables=tables,
        messages=[],
        user_prompt="Add column",
        model_source="cloud",
    )


def test_partition_tool_calls_splits_final_result() -> None:
    plan = _plan()
    regular, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args=plan.model_dump(),
                tool_call_id="out1",
            ),
            ToolCallPart(
                tool_name="get_schema",
                args={},
                tool_call_id="tc1",
            ),
        ]
    )
    assert len(regular) == 1
    assert regular[0].tool_name == "get_schema"
    assert parsed is not None
    assert parsed.intent == "add x"
    assert err is None


def test_partition_tool_calls_final_result_string_args() -> None:
    plan = _plan()
    _, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args=json.dumps(plan.model_dump()),
                tool_call_id="out1",
            ),
        ]
    )
    assert parsed is not None
    assert parsed.intent == "add x"
    assert err is None


def test_partition_tool_calls_final_result_invalid_string() -> None:
    _, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args="not valid json {{{",
                tool_call_id="out1",
            ),
        ]
    )
    assert parsed is None
    assert err
    assert len(err) > 0


def test_pa_decision_structured_plan_output() -> None:
    state = _state()
    turn = PaTurnResult(tool_parts=[], text="", structured_plan=_plan())

    async def run() -> None:
        with patch("app.agent.pa_decision._run_pa_single_turn", return_value=turn):
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, OutputPlanAction)
        assert action.payload.intent == "add x"

    asyncio.run(run())


def test_pa_decision_structured_clarification_multi_table() -> None:
    state = _state(tables_count=2)
    turn = PaTurnResult(
        tool_parts=[],
        text="",
        structured_plan=Plan.model_validate(
            {
                "intent": "ambiguous",
                "steps": [{"action": "add_column", "name": "x", "expression": "1"}],
            }
        ),
    )

    async def run() -> None:
        with patch("app.agent.pa_decision._run_pa_single_turn", return_value=turn):
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, AskClarificationAction)

    asyncio.run(run())


def test_pa_decision_json_fallback_when_enabled() -> None:
    from app.config import settings

    state = _state()
    plan_json = json.dumps(_plan().model_dump())
    turn = PaTurnResult(tool_parts=[], text=plan_json, structured_plan=None)

    async def run() -> None:
        with (
            patch.object(settings, "AGENT_PA_PLAN_JSON_FALLBACK", True),
            patch("app.agent.pa_decision._run_pa_single_turn", return_value=turn),
        ):
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, OutputPlanAction)

    asyncio.run(run())


def test_pa_decision_missing_structured_without_fallback() -> None:
    from app.config import settings

    state = _state()
    turn = PaTurnResult(tool_parts=[], text='{"intent":"x","steps":[]}', structured_plan=None)

    async def run() -> None:
        with (
            patch.object(settings, "AGENT_PA_PLAN_JSON_FALLBACK", False),
            patch("app.agent.pa_decision._run_pa_single_turn", return_value=turn),
        ):
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, FinishAction)
        assert action.payload
        assert "structured_plan_missing" in (action.payload.reason or "")

    asyncio.run(run())
