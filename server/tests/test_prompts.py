"""Stage 5：prompt 只渲染 schema + user request，无 sample dump / Column statistics。"""
from __future__ import annotations

from app.agent.state import TableContext
from app.agent.user_context import build_initial_user_message_from_tables
from app.services.prompts import ProjectPrompt, SpreadsheetPrompt

_SCHEMA = [{"key": "price", "label": "Price", "type": "number"}]


def test_single_table_no_sample_or_stats() -> None:
    text = SpreadsheetPrompt().build_user_content("add col", _SCHEMA)
    assert "Spreadsheet schema:" in text
    assert "User request:\nadd col" in text
    assert "Sample rows:" not in text
    assert "Column statistics" not in text


def test_project_no_sample_or_stats() -> None:
    tables = [
        {"name": "A", "schema": _SCHEMA},
        {"name": "B", "schema": _SCHEMA},
    ]
    text = ProjectPrompt().build_user_content("join", tables)
    assert "Project has multiple tables:" in text
    assert "Table 'A':" in text and "Table 'B':" in text
    assert "sample rows:" not in text
    assert "Column statistics" not in text


def test_build_column_stats_text_removed() -> None:
    import app.services.prompt_content as prompt_content

    assert not hasattr(prompt_content, "build_column_stats_text")


def test_initial_user_message_from_tables_clean() -> None:
    single = build_initial_user_message_from_tables(
        "x", [TableContext(name="S", schema=_SCHEMA)]
    )
    multi = build_initial_user_message_from_tables(
        "x",
        [TableContext(name="A", schema=_SCHEMA), TableContext(name="B", schema=_SCHEMA)],
    )
    for msg in (single, multi):
        assert "Sample rows:" not in msg["content"]
        assert "sample rows:" not in msg["content"]
        assert "Column statistics" not in msg["content"]
