"""Tests for Agent context assembler (Memory Blueprint Stage 4)."""
from __future__ import annotations

from app.agent.context_assembler import assemble_agent_context, build_selection_context_text
from app.agent.decision import _build_messages_dict_from_state
from app.models.agent_models import AgentState, TableContext, initial_state_from_agent_project_request
from app.models.plan import AgentProjectPlanRequest, AgentRequestContext, SelectedRange, TableInfo


def _table() -> TableContext:
    return TableContext(
        name="Orders",
        schema=[{"key": "id", "type": "string"}, {"key": "amount", "type": "number"}],
    )


def test_assemble_agent_context_shape() -> None:
    ctx = AgentRequestContext(
        activeTable="Orders",
        focusedColumn="amount",
        workspaceRules="Always round currency to 2 decimals.",
    )
    state = AgentState(
        tables=[_table()],
        messages=[{"role": "user", "content": "prior"}],
        user_prompt="sum amounts",
        applied_plans_summary="Added column total",
        request_context=ctx,
    )
    pkg = assemble_agent_context(state)
    assert len(pkg.tables) == 1
    assert pkg.selection is ctx
    assert pkg.workspace_rules == "Always round currency to 2 decimals."
    assert "Applied plans in this session:" in pkg.memory_block
    assert "prior" in pkg.transcript_summary
    assert pkg.selection_context_text is not None
    assert "Focused column: amount" in pkg.selection_context_text
    assert "Workspace rules:" in pkg.selection_context_text


def test_build_selection_context_text_rows_and_columns() -> None:
    text = build_selection_context_text(
        AgentRequestContext(
            activeTable="Sheet1",
            selectedRange=SelectedRange(startRow=0, endRow=2, colIds=["A", "B"]),
        )
    )
    assert text is not None
    assert "Active table: Sheet1" in text
    assert "rows 1–3" in text
    assert "columns A, B" in text


def test_selection_snippet_injected_before_table_context_in_messages() -> None:
    req = AgentProjectPlanRequest(
        prompt="delete selected rows",
        tables=[
            TableInfo(
                name="Sheet1",
                schema_=[{"key": "A", "type": "string"}],
                sampleRows=[{"A": "x"}],
            )
        ],
        context=AgentRequestContext(
            activeTable="Sheet1",
            selectedRange=SelectedRange(startRow=1, endRow=1),
        ),
    )
    state = initial_state_from_agent_project_request(req)
    messages = _build_messages_dict_from_state(state)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Selected rows" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "delete selected rows" in messages[2]["content"]


def test_context_fields_round_trip_on_agent_request() -> None:
    req = AgentProjectPlanRequest(
        prompt="filter",
        tables=[
            TableInfo(
                name="T1",
                schema_=[{"key": "c", "type": "string"}],
                sampleRows=[{"c": "v"}],
            )
        ],
        context=AgentRequestContext(
            activeTable="T1",
            focusedColumn="c",
            workspaceRules="Prefer ISO dates.",
        ),
    )
    state = initial_state_from_agent_project_request(req)
    assert state.request_context is not None
    assert state.request_context.activeTable == "T1"
    assert state.request_context.focusedColumn == "c"
    assert state.request_context.workspaceRules == "Prefer ISO dates."
    selection_msg = next(
        m for m in state.messages if "Workspace rules" in str(m.get("content", ""))
    )
    assert "Prefer ISO dates." in selection_msg["content"]
