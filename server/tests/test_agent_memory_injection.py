"""Applied plans summary injection into Agent system instructions / messages."""
from __future__ import annotations

from app.agent.decision import _build_messages_dict_from_state
from app.agent.memory_context import build_memory_context_block
from app.agent.pa_state import system_instructions_for_state
from app.models.agent_models import AgentState, TableContext


def _table() -> TableContext:
    return TableContext(
        name="Sheet1",
        schema=[{"key": "a", "type": "string"}],
    )


def test_build_memory_context_block_empty_when_no_summary() -> None:
    state = AgentState(tables=[_table()], messages=[], user_prompt="hi")
    assert build_memory_context_block(state) == ""


def test_build_memory_context_block_renders_summary() -> None:
    state = AgentState(
        tables=[_table()],
        messages=[],
        user_prompt="hi",
        applied_plans_summary="Added column total = price * qty",
    )
    block = build_memory_context_block(state)
    assert "Applied plans in this session:" in block
    assert "Added column total = price * qty" in block


def test_build_memory_context_block_renders_preview_lineage() -> None:
    from app.models.agent_models import PreviewRecord

    state = AgentState(
        tables=[_table()],
        messages=[],
        user_prompt="follow up",
        preview_history=[
            PreviewRecord(
                id="pv1",
                plan={"intent": "Join A and B"},
                diff={"added_columns": [], "modified_columns": [], "removed_columns": []},
                status="aborted",
                user_decision="abort",
                user_decision_reason="wrong key",
                created_at=1.0,
            )
        ],
    )
    block = build_memory_context_block(state)
    assert "Preview lineage:" in block
    assert "Aborted preview Join A and B" in block
    assert "wrong key" in block


def test_system_instructions_include_applied_summary() -> None:
    state = AgentState(
        tables=[_table()],
        messages=[],
        user_prompt="undo that column",
        applied_plans_summary="1. Added column total_price",
    )
    instructions = system_instructions_for_state(state)
    assert "Applied plans in this session:" in instructions
    assert "1. Added column total_price" in instructions


def test_build_messages_dict_injects_summary_in_system() -> None:
    state = AgentState(
        tables=[_table()],
        messages=[{"role": "user", "content": "prior turn"}],
        user_prompt="follow up",
        applied_plans_summary="Joined Sheet1 and Orders",
    )
    messages = _build_messages_dict_from_state(state)
    assert messages[0]["role"] == "system"
    assert "Applied plans in this session:" in messages[0]["content"]
    assert "Joined Sheet1 and Orders" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "prior turn"
