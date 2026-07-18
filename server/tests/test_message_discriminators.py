"""共享消息判别器（context-analyzer Stage 4）。"""
from __future__ import annotations

from app.agent.message_discriminators import (
    DATA_PROFILE_PREFIX,
    is_data_profile_message,
    is_selection_context_message,
    is_table_context_message,
)


def test_table_context_single_and_multi() -> None:
    assert is_table_context_message(
        {"role": "user", "content": "Spreadsheet schema:\n[]"}
    )
    assert is_table_context_message(
        {"role": "user", "content": "Project has multiple tables:\n..."}
    )


def test_selection_context_selection_and_rules() -> None:
    assert is_selection_context_message(
        {"role": "user", "content": "Current selection:\n- Active table: Sheet1"}
    )
    assert is_selection_context_message(
        {"role": "user", "content": "Workspace rules:\nbe careful"}
    )


def test_data_profile_prefix_at_start_only() -> None:
    assert is_data_profile_message(
        {"role": "user", "content": DATA_PROFILE_PREFIX + 'Table "t" (3 rows)'}
    )
    # 前缀出现在中间不算
    assert not is_data_profile_message(
        {"role": "user", "content": "see the " + DATA_PROFILE_PREFIX}
    )


def test_non_user_role_rejected() -> None:
    for fn in (
        is_table_context_message,
        is_selection_context_message,
        is_data_profile_message,
    ):
        assert not fn({"role": "assistant", "content": DATA_PROFILE_PREFIX})
        assert not fn(
            {"role": "assistant", "content": "Spreadsheet schema:\nCurrent selection:"}
        )


def test_empty_or_missing_content() -> None:
    for fn in (
        is_table_context_message,
        is_selection_context_message,
        is_data_profile_message,
    ):
        assert not fn({"role": "user"})
        assert not fn({"role": "user", "content": ""})
        assert not fn({"role": "user", "content": None})
        assert not fn({})


def test_compat_aliases_still_exported() -> None:
    from app.agent import context_assembler, memory_compaction

    assert memory_compaction._is_table_context_message is is_table_context_message
    assert memory_compaction._is_selection_context_message is is_selection_context_message
    assert context_assembler.is_data_profile_message is is_data_profile_message
    assert context_assembler.DATA_PROFILE_PREFIX == DATA_PROFILE_PREFIX
