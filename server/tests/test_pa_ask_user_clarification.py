"""PA ask_user tool maps to AskClarificationAction (LLM-native clarification)."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ToolCallPart

from app.agent.actions import AskClarificationAction, CallToolAction
from app.agent.pa_decision import PaTurnResult, pa_decision_step
from app.agent.pa_tools import ASK_USER_TOOL_NAME
from app.models.agent_models import AgentState, TableContext


def _two_table_state() -> AgentState:
    table = {
        "schema": [{"key": "a", "type": "string"}],
    }
    return AgentState(
        tables=[
            TableContext(name="Sheet1", **table),
            TableContext(name="Sheet2", **table),
        ],
        messages=[],
        user_prompt="add a column",
        model_source="cloud",
    )


def _turn_ask_user(**kwargs: object) -> PaTurnResult:
    args = {
        "question": "Which table should receive the new column?",
        "options": ["Sheet1", "Sheet2"],
        "context": "Multiple tables in project",
        **kwargs,
    }
    return PaTurnResult(
        tool_parts=[
            ToolCallPart(
                tool_name=ASK_USER_TOOL_NAME,
                args=args,
                tool_call_id="ask1",
            )
        ],
        text="",
        structured_plan=None,
    )


def test_pa_decision_ask_user_returns_clarification() -> None:
    state = _two_table_state()

    async def run() -> None:
        with patch(
            "app.agent.pa_decision._run_pa_single_turn",
            return_value=_turn_ask_user(),
        ), patch("app.services.tools.run_tool") as m_run:
            new_state, action = await pa_decision_step(state, use_tools=True)
            m_run.assert_not_called()
            assert isinstance(action, AskClarificationAction)
            assert action.payload.question.startswith("Which table")
            assert action.payload.options == ["Sheet1", "Sheet2"]
            assert new_state.current_turn == 1

    asyncio.run(run())


def test_pa_decision_ask_user_not_call_tool() -> None:
    state = _two_table_state()

    async def run() -> None:
        with patch(
            "app.agent.pa_decision._run_pa_single_turn",
            return_value=_turn_ask_user(),
        ):
            _, action = await pa_decision_step(state, use_tools=True)
            assert not isinstance(action, CallToolAction)

    asyncio.run(run())


def test_pa_decision_ask_user_logs_clarification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _two_table_state()

    async def run() -> None:
        with caplog.at_level(logging.INFO):
            with patch(
                "app.agent.pa_decision._run_pa_single_turn",
                return_value=_turn_ask_user(),
            ):
                await pa_decision_step(state, use_tools=True)

    asyncio.run(run())
    assert any(
        r.message == "agent_clarification"
        and getattr(r, "source", None) == "ask_user"
        for r in caplog.records
    )
