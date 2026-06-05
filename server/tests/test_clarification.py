"""Unit tests for deterministic clarification rules."""
from __future__ import annotations

from app.agent.actions import AskClarificationAction
from app.agent.clarification import maybe_need_clarification
from app.models.agent_models import AgentState, TableContext
from app.models.plan import AgentRequestContext, Plan, SelectedRange


def _two_table_state() -> AgentState:
    schema = [{"key": "price", "type": "number"}]
    return AgentState(
        tables=[
            TableContext(name="Sheet1", schema=schema, sample_rows=[{"price": 1}]),
            TableContext(name="Sheet2", schema=schema, sample_rows=[{"price": 2}]),
        ],
        messages=[],
        user_prompt="lower price",
    )


def test_clarify_missing_table_on_add_column() -> None:
    plan = Plan.model_validate(
        {
            "intent": "add",
            "steps": [{"action": "add_column", "name": "x", "expression": "1"}],
        }
    )
    action = maybe_need_clarification(_two_table_state(), plan)
    assert isinstance(action, AskClarificationAction)
    assert action.payload.options == ["Sheet1", "Sheet2"]
    assert "Multiple tables" in action.payload.question


def test_clarify_ambiguous_column_ref_sort_table() -> None:
    """Duplicate column across tables + sort_table without table triggers rule 2."""
    plan = Plan.model_validate(
        {
            "intent": "sort",
            "steps": [
                {
                    "action": "sort_table",
                    "column": "price",
                    "order": "ascending",
                }
            ],
        }
    )
    action = maybe_need_clarification(_two_table_state(), plan)
    assert isinstance(action, AskClarificationAction)
    assert "multiple tables" in action.payload.question.lower()
    assert action.payload.options == ["Sheet1", "Sheet2"]
    ctx = action.payload.context or ""
    assert "sort_table on column price" in ctx


def test_no_clarify_when_table_specified() -> None:
    plan = Plan.model_validate(
        {
            "intent": "sort",
            "steps": [
                {
                    "action": "sort_table",
                    "column": "price",
                    "order": "ascending",
                    "table": "Sheet1",
                }
            ],
        }
    )
    assert maybe_need_clarification(_two_table_state(), plan) is None


def test_no_clarify_single_table() -> None:
    state = AgentState(
        tables=[
            TableContext(
                name="Only",
                schema=[{"key": "price", "type": "number"}],
                sample_rows=[{"price": 1}],
            )
        ],
        messages=[],
        user_prompt="sort",
    )
    plan = Plan.model_validate(
        {
            "intent": "sort",
            "steps": [
                {"action": "sort_table", "column": "price", "order": "ascending"}
            ],
        }
    )
    assert maybe_need_clarification(state, plan) is None


def test_skip_missing_table_clarify_when_active_table_in_context() -> None:
    state = _two_table_state()
    state.request_context = AgentRequestContext(activeTable="Sheet1")
    plan = Plan.model_validate(
        {
            "intent": "add",
            "steps": [{"action": "add_column", "name": "x", "expression": "1"}],
        }
    )
    assert maybe_need_clarification(state, plan) is None


def test_skip_ambiguous_column_when_active_table_hosts_column() -> None:
    state = _two_table_state()
    state.request_context = AgentRequestContext(activeTable="Sheet2")
    plan = Plan.model_validate(
        {
            "intent": "sort",
            "steps": [
                {"action": "sort_table", "column": "price", "order": "ascending"}
            ],
        }
    )
    assert maybe_need_clarification(state, plan) is None


def test_skip_ambiguous_column_when_focused_column_matches() -> None:
    state = _two_table_state()
    state.request_context = AgentRequestContext(
        activeTable="Sheet1",
        focusedColumn="price",
    )
    plan = Plan.model_validate(
        {
            "intent": "sort",
            "steps": [
                {"action": "sort_table", "column": "price", "order": "ascending"}
            ],
        }
    )
    assert maybe_need_clarification(state, plan) is None


def test_skip_ambiguous_column_when_single_selected_column_matches() -> None:
    state = _two_table_state()
    state.request_context = AgentRequestContext(
        activeTable="Sheet1",
        selectedRange=SelectedRange(startRow=0, endRow=2, colIds=["price"]),
    )
    plan = Plan.model_validate(
        {
            "intent": "sort",
            "steps": [
                {"action": "sort_table", "column": "price", "order": "ascending"}
            ],
        }
    )
    assert maybe_need_clarification(state, plan) is None
