"""Structured Plan output path in pa_decision (final_result / output_type=Plan)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart

from app.agent.actions import AskClarificationAction, FinishAction, OutputPlanAction
from app.agent.pa_decision import (
    MAX_PLAN_VALIDATION_RETRIES,
    PaTurnResult,
    pa_decision_step,
    partition_tool_calls,
)
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


def test_partition_tool_calls_stringified_steps() -> None:
    """模型把 steps 元素输出为 JSON 字符串（eval sales case 422 的根因）→ 宽容解析。"""
    plan = _plan()
    raw = plan.model_dump()
    raw["steps"] = [json.dumps(s) for s in raw["steps"]]
    _, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args=raw,
                tool_call_id="out1",
            ),
        ]
    )
    assert err is None
    assert parsed is not None
    assert parsed.intent == "add x"
    assert parsed.steps[0].action == "add_column"


def test_partition_tool_calls_stringified_steps_in_string_args() -> None:
    """整个 args 是字符串且内部 steps 元素也是字符串（双层）→ 宽容解析。"""
    plan = _plan()
    raw = plan.model_dump()
    raw["steps"] = [json.dumps(s) for s in raw["steps"]]
    _, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args=json.dumps(raw),
                tool_call_id="out1",
            ),
        ]
    )
    assert err is None
    assert parsed is not None
    assert parsed.steps[0].action == "add_column"


def test_partition_tool_calls_unparseable_step_still_errors() -> None:
    """不可解析的 steps 元素（如 None / 坏字符串）保留原样 → 仍报 validation 错误。"""
    _, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args={"intent": "x", "steps": [None, "not json {{{"]},
                tool_call_id="out1",
            ),
        ]
    )
    assert parsed is None
    assert err is not None


def test_partition_tool_calls_all_null_steps() -> None:
    """openrouter/auto 实测畸形：intent 完好，steps 全为 null（无法宽容解析）。"""
    _, parsed, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args={
                    "intent": "filter and sort by amount",
                    "steps": [None, None, None, None, None],
                },
                tool_call_id="out1",
            ),
        ]
    )
    assert parsed is None
    assert err is not None
    assert "None" in err


def _null_steps_turn() -> PaTurnResult:
    _, _, err = partition_tool_calls(
        [
            ToolCallPart(
                tool_name=PA_OUTPUT_TOOL_NAME,
                args={"intent": "x", "steps": [None] * 5},
                tool_call_id="out1",
            ),
        ]
    )
    assert err is not None
    return PaTurnResult(tool_parts=[], text="", structured_plan=None, final_result_error=err)


def test_pa_decision_retries_on_plan_validation_error_then_succeeds() -> None:
    state = _state()
    bad_turn = _null_steps_turn()
    good_turn = PaTurnResult(tool_parts=[], text="", structured_plan=_plan())

    async def run() -> None:
        with patch(
            "app.agent.pa_decision._run_pa_single_turn",
            side_effect=[bad_turn, good_turn],
        ) as mock_run:
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, OutputPlanAction)
        assert mock_run.call_count == 2

        second_history = mock_run.call_args_list[1].kwargs["message_history"]
        assert second_history, "feedback message must be threaded into retry history"
        last_msg = second_history[-1]
        assert isinstance(last_msg, ModelRequest)
        assert any(
            isinstance(p, UserPromptPart) and "steps" in str(p.content)
            for p in last_msg.parts
        )

    asyncio.run(run())


def test_pa_decision_retry_exhausted_finishes_with_plan_validation_failed() -> None:
    state = _state()
    bad_turns = [
        PaTurnResult(
            tool_parts=[],
            text="",
            structured_plan=None,
            final_result_error=f"distinct error #{i}",
        )
        for i in range(1 + MAX_PLAN_VALIDATION_RETRIES)
    ]

    async def run() -> None:
        with patch(
            "app.agent.pa_decision._run_pa_single_turn",
            side_effect=bad_turns,
        ) as mock_run:
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, FinishAction)
        assert action.payload
        assert "plan_validation_failed" in (action.payload.reason or "")
        assert mock_run.call_count == 1 + MAX_PLAN_VALIDATION_RETRIES

    asyncio.run(run())


def test_pa_decision_retry_short_circuits_on_repeated_error() -> None:
    state = _state()
    bad_turn = PaTurnResult(
        tool_parts=[],
        text="",
        structured_plan=None,
        final_result_error="same error every time",
    )

    async def run() -> None:
        with patch(
            "app.agent.pa_decision._run_pa_single_turn",
            side_effect=[bad_turn, bad_turn, bad_turn],
        ) as mock_run:
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, FinishAction)
        # Retries once (new turn), then short-circuits on seeing the identical error again.
        assert mock_run.call_count == 2

    asyncio.run(run())


def test_pa_decision_retry_respects_max_turns_boundary() -> None:
    state = _state()
    state = state.model_copy(update={"current_turn": state.max_turns - 1})
    bad_turn = _null_steps_turn()

    async def run() -> None:
        with patch(
            "app.agent.pa_decision._run_pa_single_turn",
            return_value=bad_turn,
        ) as mock_run:
            _, action = await pa_decision_step(state, use_tools=True)
        assert isinstance(action, FinishAction)
        assert "plan_validation_failed" in (action.payload.reason or "")
        assert mock_run.call_count == 1

    asyncio.run(run())
