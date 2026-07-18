"""context_analyzer Stage 3：data_context 填充 + Data profile 消息注入（R1 规则）。"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.config as config_mod
from app.agent.context_assembler import is_data_profile_message
from app.agent.sub_agents.context_analyzer import analyze_context
from app.models.agent_models import AgentState, TableContext
from app.services.data_store import get_data_store, reset_data_store_for_tests

SCHEMA = [{"key": "price"}, {"key": "status"}]
ROWS = [
    {"price": 1, "status": "active"},
    {"price": 2, "status": "done"},
    {"price": 3, "status": "active"},
]

SCHEMA_MSG = {"role": "user", "content": "Spreadsheet schema:\n[...]\n\nUser request:\nsum"}
SELECTION_MSG = {"role": "user", "content": "Current selection:\n- Active table: Sheet1"}


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "ctx.sqlite3"
    monkeypatch.setattr(config_mod.settings, "DATA_DB_PATH", str(db_path))
    reset_data_store_for_tests()
    yield get_data_store()
    reset_data_store_for_tests()


def _state(table_id: str | None, messages: list[dict]) -> AgentState:
    return AgentState(
        tables=[TableContext(name="Sheet1", schema=SCHEMA, table_id=table_id)],
        messages=messages,
        user_prompt="sum",
    )


def test_fills_data_context_and_injects_before_schema(store) -> None:
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    out = analyze_context(_state(tid, [SELECTION_MSG, dict(SCHEMA_MSG)]))

    assert out.data_context is not None
    tp = out.data_context.tables[0]
    assert tp.total_row_count == 3
    assert {c.name for c in tp.columns} == {"price", "status"}

    # 顺序：selection → Data profile → schema
    assert len(out.messages) == 3
    assert out.messages[0] == SELECTION_MSG
    assert is_data_profile_message(out.messages[1])
    assert "Spreadsheet schema:" in out.messages[2]["content"]


def test_empty_messages_path_skips_injection(store) -> None:
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    out = analyze_context(_state(tid, []))
    # data_context 照常计算，但不注入（transcript 无 schema 消息）
    assert out.data_context is not None
    assert out.messages == []


def test_table_id_none_is_noop(store) -> None:
    msgs = [dict(SCHEMA_MSG)]
    out = analyze_context(_state(None, msgs))
    assert out.data_context is None
    assert out.messages == msgs


def test_table_not_found_graceful_skip(store) -> None:
    out = analyze_context(_state("nonexistent", [dict(SCHEMA_MSG)]))
    assert out.data_context is None
    assert len(out.messages) == 1


def test_empty_table_profiles_without_crash(store) -> None:
    tid = store.create_table("Sheet1", SCHEMA, [])
    out = analyze_context(_state(tid, [dict(SCHEMA_MSG)]))
    assert out.data_context is not None
    tp = out.data_context.tables[0]
    assert tp.total_row_count == 0
    assert all(c.inferred_type == "empty" for c in tp.columns)


def test_rerun_replaces_old_profile_message(store) -> None:
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    once = analyze_context(_state(tid, [dict(SCHEMA_MSG)]))
    twice = analyze_context(once)
    profile_msgs = [m for m in twice.messages if is_data_profile_message(m)]
    assert len(profile_msgs) == 1


def test_multiturn_reinjects_before_schema_message(store) -> None:
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    once = analyze_context(_state(tid, [dict(SCHEMA_MSG)]))
    # 模拟 ReAct 多轮：尾部追加 assistant tool_calls + tool 结果
    multi = once.model_copy(
        update={
            "messages": list(once.messages)
            + [
                {"role": "assistant", "content": None, "tool_calls": [{"id": "t1"}]},
                {"role": "tool", "tool_call_id": "t1", "content": "{}"},
            ]
        }
    )
    out = analyze_context(multi)
    profile_idx = [i for i, m in enumerate(out.messages) if is_data_profile_message(m)]
    schema_idx = [
        i for i, m in enumerate(out.messages)
        if "Spreadsheet schema:" in str(m.get("content") or "")
    ]
    assert len(profile_idx) == 1
    # profile 紧邻 schema 消息之前，而非 append 到 tool 消息之后
    assert profile_idx[0] == schema_idx[0] - 1
    assert out.messages[-1]["role"] == "tool"


def test_injected_message_recognized_by_discriminator(store) -> None:
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    out = analyze_context(_state(tid, [dict(SCHEMA_MSG)]))
    assert any(is_data_profile_message(m) for m in out.messages)
    # 普通消息不误判
    assert not is_data_profile_message(SCHEMA_MSG)
    assert not is_data_profile_message({"role": "assistant", "content": "Data profile:\nfake"})


def test_discriminator_requires_prefix_at_start(store) -> None:
    # 用户文本中间出现前缀不误判（startswith 契约）
    assert not is_data_profile_message(
        {"role": "user", "content": "please read this: Data profile:\nfoo"}
    )


def test_schema_message_gone_strips_stale_profile(store) -> None:
    """schema 消息后来消失的罕见场景：旧 profile 不残留。"""
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    once = analyze_context(_state(tid, [dict(SCHEMA_MSG)]))
    no_schema = once.model_copy(
        update={"messages": [m for m in once.messages if is_data_profile_message(m)]}
    )
    out = analyze_context(no_schema)
    assert not any(is_data_profile_message(m) for m in out.messages)


def test_store_lost_after_first_run_clears_stale_state(store) -> None:
    """首轮成功、后续 store 失效：清掉过期 data_context 与旧 profile 消息。"""
    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    once = analyze_context(_state(tid, [dict(SCHEMA_MSG)]))
    assert once.data_context is not None

    gone = once.model_copy(
        update={"tables": [TableContext(name="Sheet1", schema=SCHEMA, table_id="gone")]}
    )
    out = analyze_context(gone)
    assert out.data_context is None
    assert not any(is_data_profile_message(m) for m in out.messages)
    assert any("Spreadsheet schema:" in str(m.get("content") or "") for m in out.messages)


def test_multiple_tables_profiled_into_one_message(store) -> None:
    tid_a = store.create_table("A", SCHEMA, ROWS)
    tid_b = store.create_table("B", SCHEMA, ROWS[:1])
    state = AgentState(
        tables=[
            TableContext(name="A", schema=SCHEMA, table_id=tid_a),
            TableContext(name="B", schema=SCHEMA, table_id=tid_b),
        ],
        messages=[
            {"role": "user", "content": "Project has multiple tables:\n[...]\n\nUser request:\nsum"}
        ],
        user_prompt="sum",
    )
    out = analyze_context(state)
    assert out.data_context is not None
    assert [t.table_name for t in out.data_context.tables] == ["A", "B"]
    assert out.data_context.tables[1].total_row_count == 1
    profile_msgs = [m for m in out.messages if is_data_profile_message(m)]
    assert len(profile_msgs) == 1
    assert '"A"' in profile_msgs[0]["content"] and '"B"' in profile_msgs[0]["content"]


def test_node_context_graph_roundtrip_preserves_data_context(store) -> None:
    """经 orchestrator _node_context 的 model_dump/model_validate 往返后 data_context 完好。"""
    from app.agent.orchestrator import _node_context

    tid = store.create_table("Sheet1", SCHEMA, ROWS)
    state = _state(tid, [dict(SCHEMA_MSG)])
    out = _node_context({"agent": state.model_dump(), "scratch": {}})
    restored = AgentState.model_validate(out["agent"])
    assert restored.data_context is not None
    assert restored.data_context.tables[0].total_row_count == 3
    assert any(is_data_profile_message(m) for m in restored.messages)


def test_partial_multi_table_profiles_present_and_summary_warning(
    store, caplog: pytest.LogCaptureFixture
) -> None:
    """Stage 4：A 在 store、B 缺失 → partial DataContext + 单条汇总 warning。"""
    import logging

    tid_a = store.create_table("A", SCHEMA, ROWS)
    state = AgentState(
        tables=[
            TableContext(name="A", schema=SCHEMA, table_id=tid_a),
            TableContext(name="B", schema=SCHEMA, table_id="missing-id"),
        ],
        messages=[dict(SCHEMA_MSG)],
        user_prompt="join",
    )
    with caplog.at_level(logging.WARNING, logger="app.agent.sub_agents.context_analyzer"):
        out = analyze_context(state)

    assert out.data_context is not None
    assert [tp.table_name for tp in out.data_context.tables] == ["A"]
    summary = [
        r for r in caplog.records if "partial DataContext" in r.getMessage()
    ]
    assert len(summary) == 1
    assert "B" in summary[0].getMessage()
