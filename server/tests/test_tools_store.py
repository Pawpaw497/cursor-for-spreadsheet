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


# --- Stage 4: get_column_stats prefers DataContext (SSOT) ---

def _data_context(sampled: bool = False):
    from app.models.table_models import ColumnProfile, DataContext, TableProfile

    return DataContext(
        tables=[
            TableProfile(
                table_name="Sheet1",
                total_row_count=100,
                col_count=2,
                profile_sampled=sampled,
                columns=[
                    ColumnProfile(
                        name="a",
                        inferred_type="numeric",
                        count=95,
                        null_count=5,
                        null_ratio=0.05,
                        distinct_count=42,
                        min_val="1",
                        max_val="99.5",
                        mean=50.0,
                        std=10.0,
                    ),
                    ColumnProfile(
                        name="b",
                        inferred_type="string",
                        count=90,
                        null_count=10,
                        null_ratio=0.1,
                        distinct_count=7,
                        min_val="apple",
                        max_val="zebra",
                    ),
                ],
            )
        ]
    )


def test_get_column_stats_hits_data_context_numeric() -> None:
    out = json.loads(
        get_column_stats(_tables("unused"), "Sheet1", "a", data_context=_data_context())
    )
    assert out == {"count": 95, "distinct": 42, "min": 1, "max": 99.5}


def test_get_column_stats_hits_data_context_string_no_minmax() -> None:
    out = json.loads(
        get_column_stats(_tables("unused"), "Sheet1", "b", data_context=_data_context())
    )
    assert out == {"count": 90, "distinct": 7}


def test_get_column_stats_miss_falls_back_to_store(data_store: DataStore) -> None:
    table_id = data_store.create_table(
        name="Sheet1",
        schema=[{"key": "a", "type": "number"}],
        rows=[{"a": i} for i in range(15)],
    )
    # data_context 无该列 → fallback 全量扫描
    out = json.loads(
        get_column_stats(_tables(table_id), "Sheet1", "zzz", data_context=_data_context())
    )
    assert out == {"count": 0, "distinct": 0}
    out2 = json.loads(
        get_column_stats(_tables(table_id), "Sheet1", "a", data_context=None)
    )
    assert out2["count"] == 15


def test_run_tool_injects_data_context_only_when_declared(data_store: DataStore) -> None:
    from app.services.tools import run_tool

    table_id = data_store.create_table(
        name="Sheet1",
        schema=[{"key": "a", "type": "number"}],
        rows=[{"a": 1}],
    )
    tables = _tables(table_id)
    # get_column_stats 声明了 data_context → 注入并命中 profile
    out = json.loads(
        run_tool(
            "get_column_stats",
            {"table_name": "Sheet1", "column": "a"},
            tables,
            data_context=_data_context(),
        )
    )
    assert out == {"count": 95, "distinct": 42, "min": 1, "max": 99.5}
    # validate_expression 未声明 data_context → 不注入、不报 TypeError
    out2 = json.loads(
        run_tool(
            "validate_expression",
            {"expression": "row['a'] + 1"},
            tables,
            data_context=_data_context(),
        )
    )
    assert out2["ok"] is True
