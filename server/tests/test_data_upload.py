"""Tests for POST /api/data/upload."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config as config_mod
from app.main import app
from app.services import data_store as data_store_mod
from app.services.audit_log import parse_request_body_for_audit
from app.services.data_store import DataStore, reset_data_store_for_tests


@pytest.fixture
def data_db_path(tmp_path: Path) -> Path:
    return tmp_path / "tables.sqlite3"


@pytest.fixture
def data_store_client(
    monkeypatch: pytest.MonkeyPatch, data_db_path: Path
) -> tuple[TestClient, DataStore]:
    monkeypatch.setattr(config_mod.settings, "DATA_DB_PATH", str(data_db_path))
    reset_data_store_for_tests()
    store = DataStore(data_db_path)
    client = TestClient(app)
    yield client, store
    reset_data_store_for_tests()


def _upload_payload(
    *,
    name: str = "t1",
    rows: list[dict] | None = None,
    schema: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "schema": schema if schema is not None else [{"key": "a", "type": "string"}],
        "rows": rows if rows is not None else [{"a": "x"}, {"a": "y"}],
    }


def test_upload_happy_path_returns_camel_case_wire_json(
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, store = data_store_client
    payload = _upload_payload(rows=[{"a": "one"}, {"a": "two"}, {"a": "three"}])
    resp = client.post("/api/data/upload", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "tableId" in body
    assert "rowCount" in body
    assert "table_id" not in body
    assert "row_count" not in body
    assert body["rowCount"] == 3

    stored = store.read_table(body["tableId"])
    assert stored.name == "t1"
    assert stored.rows == payload["rows"]


def test_upload_accepts_schema_alias(
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    resp = client.post(
        "/api/data/upload",
        json={"name": "t", "schema": [{"key": "id"}], "rows": [{"id": 1}]},
    )
    assert resp.status_code == 200


def test_upload_empty_rows(
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    resp = client.post(
        "/api/data/upload",
        json={"name": "empty", "schema": [], "rows": []},
    )
    assert resp.status_code == 200
    assert resp.json()["rowCount"] == 0


def test_upload_row_count_at_limit_ok(
    monkeypatch: pytest.MonkeyPatch,
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    monkeypatch.setattr(config_mod.settings, "MAX_UPLOAD_ROWS", 5)
    rows = [{"i": i} for i in range(5)]
    resp = client.post(
        "/api/data/upload",
        json={"name": "t", "schema": [], "rows": rows},
    )
    assert resp.status_code == 200
    assert resp.json()["rowCount"] == 5


def test_upload_row_count_over_limit_returns_413(
    monkeypatch: pytest.MonkeyPatch,
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    monkeypatch.setattr(config_mod.settings, "MAX_UPLOAD_ROWS", 5)
    rows = [{"i": i} for i in range(6)]
    resp = client.post(
        "/api/data/upload",
        json={"name": "t", "schema": [], "rows": rows},
    )
    assert resp.status_code == 413
    assert "5" in str(resp.json()["detail"])


def test_upload_byte_count_at_limit_ok(
    monkeypatch: pytest.MonkeyPatch,
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    payload = _upload_payload(rows=[{"a": "x"}])
    body_bytes = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(config_mod.settings, "MAX_UPLOAD_BYTES", len(body_bytes))
    resp = client.post(
        "/api/data/upload",
        content=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200


def test_upload_byte_count_over_limit_returns_413(
    monkeypatch: pytest.MonkeyPatch,
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    payload = _upload_payload(rows=[{"a": "x"}])
    body_bytes = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(config_mod.settings, "MAX_UPLOAD_BYTES", len(body_bytes) - 1)
    resp = client.post(
        "/api/data/upload",
        content=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert str(len(body_bytes) - 1) in str(resp.json()["detail"])


def test_upload_idempotent_client_request_id(
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    headers = {"X-Client-Request-Id": "idem-1"}
    payload = _upload_payload()
    first = client.post("/api/data/upload", json=payload, headers=headers)
    second = client.post("/api/data/upload", json=payload, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["tableId"] == second.json()["tableId"]


def test_upload_missing_name_returns_422(
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    resp = client.post("/api/data/upload", json={"schema": [], "rows": []})
    assert resp.status_code == 422


def test_upload_rows_not_list_returns_422(
    data_store_client: tuple[TestClient, DataStore],
) -> None:
    client, _store = data_store_client
    resp = client.post(
        "/api/data/upload",
        json={"name": "t", "schema": [], "rows": "bad"},
    )
    assert resp.status_code == 422


def test_parse_request_body_for_audit_data_upload_metadata_only() -> None:
    payload = {
        "name": "big",
        "schema": [{"key": "a"}],
        "rows": [{"a": i} for i in range(100)],
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    audit_body = parse_request_body_for_audit(
        body_bytes,
        path="/api/data/upload",
        content_type="application/json",
    )
    assert audit_body == {
        "name": "big",
        "rowCount": 100,
        "schemaCols": 1,
        "_audit": "data_upload_metadata_only",
    }
    assert "rows" not in audit_body
