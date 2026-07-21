"""peek_range tool (Stage 6) — store-backed row reads."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config as config_mod
from app.agent.state import TableContext
from app.services.data_store import DataStore, reset_data_store_for_tests
from app.services.tools import MAX_PEEK_ROWS, peek_range


@pytest.fixture
def data_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataStore:
    db_path = tmp_path / "peek.sqlite3"
    monkeypatch.setattr(config_mod.settings, "DATA_DB_PATH", str(db_path))
    reset_data_store_for_tests()
    store = DataStore(db_path)
    yield store
    reset_data_store_for_tests()


def _tables(
    table_id: str | None,
    name: str = "Sheet1",
    schema: list | None = None,
) -> list[TableContext]:
    if schema is None:
        schema = [
            {"key": "amount", "type": "number"},
            {"key": "label", "type": "string"},
        ]
    return [TableContext(name=name, schema=schema, table_id=table_id)]


def _load(raw: str) -> dict:
    assert isinstance(raw, str)
    return json.loads(raw)


def test_happy_path_range_read(data_store: DataStore) -> None:
    rows = [{"amount": i, "label": f"r{i}"} for i in range(20)]
    table_id = data_store.create_table(name="Sheet1", schema=_tables(None)[0].schema, rows=rows)
    out = _load(peek_range(_tables(table_id), "Sheet1", start_row=5, end_row=8))
    assert out["row_count"] == 20
    assert out["truncated"] is False
    assert len(out["rows"]) == 3
    assert out["rows"][0]["amount"] == 5


def test_out_of_range_empty_rows(data_store: DataStore) -> None:
    table_id = data_store.create_table(
        name="Sheet1",
        schema=_tables(None)[0].schema,
        rows=[{"amount": 1, "label": "a"}],
    )
    out = _load(peek_range(_tables(table_id), "Sheet1", start_row=10, end_row=20))
    assert out["rows"] == []
    assert out["truncated"] is False


def test_truncated_only_when_max_peek_rows_cap(data_store: DataStore) -> None:
    rows = [{"amount": i, "label": "x"} for i in range(500)]
    table_id = data_store.create_table(name="Sheet1", schema=_tables(None)[0].schema, rows=rows)
    out_cap = _load(
        peek_range(_tables(table_id), "Sheet1", start_row=0, end_row=MAX_PEEK_ROWS + 50)
    )
    assert out_cap["truncated"] is True
    assert len(out_cap["rows"]) == MAX_PEEK_ROWS

    out_row_count = _load(
        peek_range(_tables(table_id), "Sheet1", start_row=0, end_row=100)
    )
    assert out_row_count["truncated"] is False
    assert len(out_row_count["rows"]) == 100

    out_past_rows = _load(
        peek_range(_tables(table_id), "Sheet1", start_row=400, end_row=600)
    )
    assert out_past_rows["truncated"] is False
    assert len(out_past_rows["rows"]) == 100


def test_columns_projection_and_unknown_column(data_store: DataStore) -> None:
    table_id = data_store.create_table(
        name="Sheet1",
        schema=_tables(None)[0].schema,
        rows=[{"amount": 1, "label": "a"}],
    )
    out = _load(
        peek_range(_tables(table_id), "Sheet1", columns=["amount"])
    )
    assert out["rows"] == [{"amount": 1}]

    err_out = _load(
        peek_range(_tables(table_id), "Sheet1", columns=["nope"])
    )
    assert "error" in err_out


def test_filter_within_window_only(data_store: DataStore) -> None:
    rows = [{"amount": i, "label": "x"} for i in range(100)]
    table_id = data_store.create_table(name="Sheet1", schema=_tables(None)[0].schema, rows=rows)
    out = _load(
        peek_range(
            _tables(table_id),
            "Sheet1",
            start_row=0,
            end_row=10,
            filter_expr="amount > 50",
        )
    )
    assert out["rows"] == []


def test_filter_hits_rows_in_window(data_store: DataStore) -> None:
    rows = [{"amount": i, "label": "x"} for i in range(30)]
    table_id = data_store.create_table(name="Sheet1", schema=_tables(None)[0].schema, rows=rows)
    out = _load(
        peek_range(
            _tables(table_id),
            "Sheet1",
            start_row=20,
            end_row=30,
            filter_expr="amount >= 25",
        )
    )
    amounts = [r["amount"] for r in out["rows"]]
    assert amounts == [25, 26, 27, 28, 29]


def test_invalid_table_name() -> None:
    out = _load(peek_range(_tables("tid"), "Missing", start_row=0, end_row=1))
    assert "error" in out
    assert "not found" in out["error"].lower()


def test_empty_table(data_store: DataStore) -> None:
    table_id = data_store.create_table(
        name="Sheet1",
        schema=_tables(None)[0].schema,
        rows=[],
    )
    out = _load(peek_range(_tables(table_id), "Sheet1"))
    assert out["rows"] == []
    assert out["row_count"] == 0
    assert out["truncated"] is False


def test_no_table_ref_like_validate_expression() -> None:
    out = _load(peek_range(_tables(None), "Sheet1"))
    assert "error" in out
    assert "tableRef" in out["error"] or "upload" in out["error"].lower()
