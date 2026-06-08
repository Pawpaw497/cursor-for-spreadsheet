"""Memory Blueprint Stage 5: deterministic message compaction."""
from __future__ import annotations

import json

from app.agent.memory_compaction import (
    EARLIER_PREFIX,
    MAX_CHAT_TURNS,
    MAX_TOOL_MESSAGES,
    apply_message_compaction,
    compact_agent_messages,
)
from app.models.agent_models import AgentState, TableContext


def _plain_chat_pairs(count: int) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    for i in range(count):
        msgs.append({"role": "user", "content": f"user-{i}"})
        msgs.append({"role": "assistant", "content": f"assistant-{i}"})
    return msgs


def test_compact_many_plain_chat_turns_within_cap_and_summary() -> None:
    prefix = _plain_chat_pairs(32)
    result = compact_agent_messages(
        prefix,
        applied_plans_summary="Added column total",
        max_chat_turns=MAX_CHAT_TURNS,
        preserve_tail_count=0,
    )
    plain = [m for m in result if not str(m.get("content", "")).startswith(EARLIER_PREFIX)]
    assert len(plain) <= MAX_CHAT_TURNS
    assert result[0]["role"] == "user"
    assert result[0]["content"].startswith(EARLIER_PREFIX)
    assert "Added column total" in result[0]["content"]


def test_compact_tool_messages_keeps_last_n_and_digests() -> None:
    tid = "call_1"
    msgs: list[dict] = [
        {"role": "user", "content": "do something"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "old_call",
                    "type": "function",
                    "function": {"name": "get_schema", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "old_call", "content": '{"old": true}'},
    ]
    for i in range(8):
        cid = f"call_{i}"
        msgs.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": cid,
                            "type": "function",
                            "function": {
                                "name": "validate_table",
                                "arguments": json.dumps({"n": i}),
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": cid, "content": f"result-{i}"},
            ]
        )
    msgs.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tid,
                    "type": "function",
                    "function": {"name": "get_schema", "arguments": "{}"},
                }
            ],
        }
    )
    msgs.append({"role": "tool", "tool_call_id": tid, "content": "{}"})

    result = compact_agent_messages(
        msgs,
        applied_plans_summary="prior applies",
        max_tool_messages=MAX_TOOL_MESSAGES,
        preserve_tail_count=0,
    )
    tool_related = [
        m
        for m in result
        if m.get("role") == "tool" or m.get("tool_calls")
    ]
    assert len(tool_related) <= MAX_TOOL_MESSAGES
    summary_msgs = [
        m for m in result if str(m.get("content", "")).startswith(EARLIER_PREFIX)
    ]
    assert len(summary_msgs) == 1
    assert "Prior tool calls:" in summary_msgs[0]["content"]
    assert result[-1]["role"] == "tool"
    assert result[-1]["tool_call_id"] == tid


def test_tail_preservation_last_two_unchanged() -> None:
    prefix = _plain_chat_pairs(30)
    tail = [
        {"role": "user", "content": "selection context"},
        {"role": "user", "content": "table context"},
    ]
    full = prefix + tail
    result = compact_agent_messages(full, preserve_tail_count=2)
    assert result[-2:] == tail


def test_protected_table_and_selection_messages_kept_in_tool_loop() -> None:
    selection = {
        "role": "user",
        "content": "Current selection:\n- Active table: Sheet1",
    }
    table = {
        "role": "user",
        "content": "Spreadsheet schema:\n[]\n\nSample rows:\n[]\n\nUser request:\nadd col\n",
    }
    msgs = _plain_chat_pairs(20) + [selection, table]
    for i in range(10):
        cid = f"t{i}"
        msgs.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": cid,
                            "type": "function",
                            "function": {"name": "get_schema", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": cid, "content": "{}"},
            ]
        )
    result = compact_agent_messages(msgs, preserve_tail_count=0)
    assert selection in result
    assert table in result


def test_apply_message_compaction_on_state_with_tools() -> None:
    table = TableContext(name="Sheet1", schema=[], sample_rows=[])
    msgs: list[dict] = [
        {"role": "user", "content": "Spreadsheet schema:\n[]\n\nUser request:\nx\n"},
    ]
    for i in range(15):
        cid = f"c{i}"
        msgs.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": cid,
                            "type": "function",
                            "function": {"name": "get_schema", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": cid, "content": "{}"},
            ]
        )
    state = AgentState(
        tables=[table],
        messages=msgs,
        applied_plans_summary="summary",
    )
    compacted = apply_message_compaction(state)
    tool_rows = [
        m
        for m in compacted.messages
        if m.get("role") == "tool" or m.get("tool_calls")
    ]
    assert len(tool_rows) <= MAX_TOOL_MESSAGES
