"""Stage 4：Agent 路径 prompt 不再含 sample dump / Column statistics。

legacy `/api/plan` 路径（非空 sampleRows）保持原行为，归 Stage 5 退役。
"""
from __future__ import annotations

from app.agent.state import TableContext
from app.agent.user_context import build_initial_user_message_from_tables
from app.services.prompts import ProjectPrompt, SpreadsheetPrompt

_SCHEMA = [{"key": "price", "label": "Price", "type": "number"}]
_ROWS = [{"price": 1}, {"price": 2}]


def test_single_table_agent_path_no_sample_or_stats() -> None:
    text = SpreadsheetPrompt().build_user_content("add col", _SCHEMA, [])
    assert "Spreadsheet schema:" in text
    assert "User request:\nadd col" in text
    assert "Sample rows:" not in text
    assert "Column statistics" not in text


def test_single_table_legacy_path_unchanged() -> None:
    text = SpreadsheetPrompt().build_user_content("add col", _SCHEMA, _ROWS)
    assert "Sample rows:" in text


def test_project_agent_path_no_sample_or_stats() -> None:
    tables = [
        {"name": "A", "schema": _SCHEMA, "sampleRows": []},
        {"name": "B", "schema": _SCHEMA, "sampleRows": []},
    ]
    text = ProjectPrompt().build_user_content("join", tables)
    assert "Project has multiple tables:" in text
    assert "Table 'A':" in text and "Table 'B':" in text
    assert "sample rows:" not in text
    assert "Column statistics" not in text


def test_project_legacy_path_unchanged() -> None:
    tables = [{"name": "A", "schema": _SCHEMA, "sampleRows": _ROWS}]
    text = ProjectPrompt().build_user_content("join", tables)
    assert "sample rows:" in text


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
