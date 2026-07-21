"""SQLite persistence for uploaded table rows."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings
from app.logging_config import get_logger

log = get_logger("services.data_store")

_SERVER_ROOT = Path(__file__).resolve().parents[2]

_store: DataStore | None = None

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS tables (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS rows (
    table_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    row_json TEXT NOT NULL,
    PRIMARY KEY (table_id, row_index),
    FOREIGN KEY (table_id) REFERENCES tables(id) ON DELETE CASCADE
);
"""


class TableNotFoundError(Exception):
    """Raised when a table_id does not exist in the store."""


@dataclass
class StoredTable:
    table_id: str
    name: str
    schema: list[dict[str, Any]]
    row_count: int
    rows: list[dict[str, Any]]


def resolve_data_db_path() -> Path:
    """Resolve SQLite file path (relative paths are under ``server/``)."""
    raw = (settings.DATA_DB_PATH or "data/tables.sqlite3").strip()
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    parts = p.parts
    if parts and parts[0] == "server":
        return _SERVER_ROOT.parent / p
    return _SERVER_ROOT / p


class DataStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLES_SQL)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
        self._initialized = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _lookup_by_client_request_id(
        conn: sqlite3.Connection, client_request_id: str
    ) -> str | None:
        row = conn.execute(
            "SELECT id FROM tables WHERE client_request_id = ?",
            (client_request_id,),
        ).fetchone()
        return str(row["id"]) if row else None

    def create_table(
        self,
        name: str,
        schema: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        client_request_id: str | None = None,
    ) -> str:
        """Write metadata + rows in one transaction; idempotent on client_request_id."""
        self._ensure_initialized()
        cid = (client_request_id or "").strip() or None

        self.sweep_expired()

        with self._connect() as conn:
            if cid:
                existing = self._lookup_by_client_request_id(conn, cid)
                if existing:
                    return existing

            table_id = uuid.uuid4().hex
            created_at = self._utc_now_iso()
            schema_json = json.dumps(schema, ensure_ascii=False)
            row_count = len(rows)

            try:
                with conn:
                    encoded_rows = [
                        (table_id, idx, json.dumps(row, ensure_ascii=False))
                        for idx, row in enumerate(rows)
                    ]
                    conn.execute(
                        """
                        INSERT INTO tables (
                            id, name, schema_json, row_count, created_at, client_request_id
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (table_id, name, schema_json, row_count, created_at, cid),
                    )
                    if encoded_rows:
                        conn.executemany(
                            """
                            INSERT INTO rows (table_id, row_index, row_json)
                            VALUES (?, ?, ?)
                            """,
                            encoded_rows,
                        )
            except sqlite3.IntegrityError:
                if cid:
                    existing = self._lookup_by_client_request_id(conn, cid)
                    if existing:
                        return existing
                raise

            return table_id

    def read_table(self, table_id: str) -> StoredTable:
        self._ensure_initialized()
        with self._connect() as conn:
            meta = conn.execute(
                "SELECT id, name, schema_json, row_count FROM tables WHERE id = ?",
                (table_id,),
            ).fetchone()
            if meta is None:
                raise TableNotFoundError(table_id)

            row_records = conn.execute(
                "SELECT row_json FROM rows WHERE table_id = ? ORDER BY row_index",
                (table_id,),
            ).fetchall()

            return StoredTable(
                table_id=str(meta["id"]),
                name=str(meta["name"]),
                schema=json.loads(meta["schema_json"]),
                row_count=int(meta["row_count"]),
                rows=[json.loads(record["row_json"]) for record in row_records],
            )

    def read_rows(self, table_id: str, start: int, end: int) -> list[dict[str, Any]]:
        self._ensure_initialized()
        start = max(0, start)

        with self._connect() as conn:
            meta = conn.execute(
                "SELECT row_count FROM tables WHERE id = ?",
                (table_id,),
            ).fetchone()
            if meta is None:
                raise TableNotFoundError(table_id)

            row_count = int(meta["row_count"])
            end = min(end, row_count)
            if start >= end:
                return []

            row_records = conn.execute(
                """
                SELECT row_json FROM rows
                WHERE table_id = ? AND row_index >= ? AND row_index < ?
                ORDER BY row_index
                """,
                (table_id, start, end),
            ).fetchall()

            return [json.loads(record["row_json"]) for record in row_records]

    def get_row_count(self, table_id: str) -> int:
        """Lightweight row count without loading row payloads."""
        self._ensure_initialized()
        with self._connect() as conn:
            meta = conn.execute(
                "SELECT row_count FROM tables WHERE id = ?",
                (table_id,),
            ).fetchone()
            if meta is None:
                raise TableNotFoundError(table_id)
            return int(meta["row_count"])

    def sweep_expired(self, ttl_hours: int | None = None) -> int:
        self._ensure_initialized()
        hours = ttl_hours if ttl_hours is not None else settings.TABLE_TTL_HOURS
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        with self._connect() as conn:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM tables WHERE created_at < ?",
                    (cutoff,),
                )
                return int(cursor.rowcount)


def get_data_store() -> DataStore:
    """Module-level singleton (lazy init)."""
    global _store
    if _store is None:
        _store = DataStore(resolve_data_db_path())
    return _store


def reset_data_store_for_tests() -> None:
    """Clear module singleton between tests."""
    global _store
    _store = None
