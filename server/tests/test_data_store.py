"""Tests for SQLite table row persistence (data_store)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.data_store import DataStore, TableNotFoundError


@pytest.fixture
def store(tmp_path) -> DataStore:
    return DataStore(tmp_path / "tables.sqlite3")


def test_create_and_read_table_roundtrip(store: DataStore) -> None:
    schema = [{"key": "a", "type": "number"}, {"key": "b", "type": "string"}]
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "z"}]
    table_id = store.create_table(name="t1", schema=schema, rows=rows)

    stored = store.read_table(table_id)
    assert stored.table_id == table_id
    assert stored.name == "t1"
    assert stored.schema == schema
    assert stored.row_count == 3
    assert stored.rows == rows


def test_create_empty_table(store: DataStore) -> None:
    table_id = store.create_table(name="empty", schema=[{"key": "a"}], rows=[])
    stored = store.read_table(table_id)
    assert stored.row_count == 0
    assert stored.rows == []


def test_read_rows_half_open_interval(store: DataStore) -> None:
    rows = [{"i": i} for i in range(10)]
    table_id = store.create_table(name="t", schema=[], rows=rows)
    assert store.read_rows(table_id, 2, 5) == [{"i": 2}, {"i": 3}, {"i": 4}]


def test_read_rows_clamps_bounds(store: DataStore) -> None:
    rows = [{"i": i} for i in range(5)]
    table_id = store.create_table(name="t", schema=[], rows=rows)

    assert store.read_rows(table_id, 0, 100) == rows
    assert store.read_rows(table_id, 5, 10) == []
    assert store.read_rows(table_id, -3, 2) == [{"i": 0}, {"i": 1}]


def test_read_rows_start_gte_end_returns_empty(store: DataStore) -> None:
    table_id = store.create_table(name="t", schema=[], rows=[{"i": 0}, {"i": 1}])
    assert store.read_rows(table_id, 5, 2) == []
    assert store.read_rows(table_id, 3, 3) == []


def test_read_table_missing_raises(store: DataStore) -> None:
    with pytest.raises(TableNotFoundError):
        store.read_table("missing-id")


def test_read_rows_missing_raises(store: DataStore) -> None:
    with pytest.raises(TableNotFoundError):
        store.read_rows("missing-id", 0, 1)


def test_get_row_count(store: DataStore) -> None:
    table_id = store.create_table(
        name="t",
        schema=[{"key": "a"}],
        rows=[{"a": 1}, {"a": 2}],
    )
    assert store.get_row_count(table_id) == 2


def test_get_row_count_missing_raises(store: DataStore) -> None:
    with pytest.raises(TableNotFoundError):
        store.get_row_count("missing-id")


def test_create_table_rolls_back_on_serialization_failure(store: DataStore) -> None:
    bad_rows = [{"ok": 1}, {"bad": object()}]
    with pytest.raises(TypeError):
        store.create_table(name="bad", schema=[], rows=bad_rows)

    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tables").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM rows").fetchone()[0] == 0


def test_client_request_id_is_idempotent(store: DataStore) -> None:
    rows = [{"a": 1}]
    first = store.create_table(
        name="t",
        schema=[{"key": "a"}],
        rows=rows,
        client_request_id="req-1",
    )
    second = store.create_table(
        name="t2",
        schema=[{"key": "a"}],
        rows=[{"a": 99}],
        client_request_id="req-1",
    )
    assert first == second

    stored = store.read_table(first)
    assert stored.rows == rows
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tables").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rows").fetchone()[0] == 1


def test_without_client_request_id_creates_distinct_tables(store: DataStore) -> None:
    rows = [{"a": 1}]
    first = store.create_table(name="t", schema=[], rows=rows)
    second = store.create_table(name="t", schema=[], rows=rows)
    assert first != second


def test_sweep_expired_deletes_old_tables(store: DataStore) -> None:
    old_id = store.create_table(name="old", schema=[], rows=[{"x": 1}])
    fresh_id = store.create_table(name="fresh", schema=[], rows=[{"y": 2}])
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    with store._connect() as conn:
        with conn:
            conn.execute(
                "UPDATE tables SET created_at = ? WHERE id = ?",
                (old_ts, old_id),
            )

    deleted = store.sweep_expired(ttl_hours=24)
    assert deleted == 1

    with pytest.raises(TableNotFoundError):
        store.read_table(old_id)
    assert store.read_table(fresh_id).name == "fresh"
