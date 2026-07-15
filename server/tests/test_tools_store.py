"""Tools read rows from data_store via table_id."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config as config_mod
from app.agent.state import TableContext
from app.services.data_store import DataStore, reset_data_store_for_tests
from app.services.tools import get_column_stats, validate_expression


@pytest.fixture
def data_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataStore:
    db_path = tmp_path / "tools.sqlite3"
    monkeypatch.setattr(config_mod.settings, "DATA_DB_PATH", str(db_path))
    reset_data_store_for_tests()
    store = DataStore(db_path)
    yield store
    reset_data_store_for_tests()


def _tables(table_id: str | None, name: str = "Sheet1") -> list[TableContext]:
    return [
        TableContext(
            name=name,
            schema=[{"key": "a", "type": "number"}, {"key": "b", "type": "string"}],
            table_id=table_id,
        )
    ]


def test_validate_expression_happy_path_from_store(data_store: DataStore) -> None:
    table_id = data_store.create_table(
        name="Sheet1",
        schema=[{"key": "a", "type": "number"}],
        rows=[{"a": 2, "b": "x"}],
    )
    out = json.loads(
        validate_expression(_tables(table_id), "row['a'] * 2")
    )
    assert out == {"ok": True}


def test_validate_expression_no_table_ref() -> None:
    out = json.loads(validate_expression(_tables(None), "row['a']"))
    assert out["ok"] is False
    assert "No tableRef" in out["error"]


def test_validate_expression_table_not_found_in_tables() -> None:
    out = json.loads(
        validate_expression(_tables("t1"), "row['a']", table_name="Missing")
    )
    assert out["ok"] is False
    assert "Table not found" in out["error"]


def test_validate_expression_table_not_found_in_store(data_store: DataStore) -> None:
    out = json.loads(
        validate_expression(_tables("nonexistent-id"), "row['a']")
    )
    assert out["ok"] is False
    assert "Table not found in store" in out["error"]


def test_validate_expression_empty_table(data_store: DataStore) -> None:
    table_id = data_store.create_table(
        name="empty",
        schema=[{"key": "a", "type": "string"}],
        rows=[],
    )
    out = json.loads(validate_expression(_tables(table_id), "row['a']"))
    assert out["ok"] is False
    assert out["error"] == "No sample row"


def test_get_column_stats_reads_full_table_from_store(data_store: DataStore) -> None:
    rows = [{"price": i} for i in range(15)]
    table_id = data_store.create_table(
        name="Sheet1",
        schema=[{"key": "price", "type": "number"}],
        rows=rows,
    )
    out = json.loads(
        get_column_stats(_tables(table_id), "Sheet1", "price")
    )
    assert out["count"] == 15
    assert out["distinct"] == 15
    assert out["min"] == 0
    assert out["max"] == 14


def test_get_column_stats_no_table_ref_returns_zeros() -> None:
    out = json.loads(get_column_stats(_tables(None), "Sheet1", "price"))
    assert out == {"count": 0, "distinct": 0}


def test_get_column_stats_table_not_in_store() -> None:
    out = json.loads(
        get_column_stats(_tables("ghost"), "Sheet1", "price")
    )
    assert out["error"] == "Table data not found"
