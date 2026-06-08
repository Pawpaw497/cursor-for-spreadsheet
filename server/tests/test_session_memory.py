"""Tests for optional SQLite session memory (Stage 6)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config as config_mod
from app.main import app
from app.services import audit_db
from app.services import session_store as session_mod


def _sample_memory(session_id: str) -> dict:
    return {
        "version": 1,
        "chatTranscript": [
            {
                "id": "m1",
                "sessionId": session_id,
                "role": "user",
                "content": "add total column",
                "createdAt": "2026-06-01T00:00:00.000Z",
                "source": "live",
            }
        ],
        "agentTranscript": [{"role": "user", "content": "add total column"}],
        "applyLog": [],
        "previewHistory": [],
        "appliedPlansSummary": "",
        "sessionMeta": {
            "sessionId": session_id,
            "lastServerBootId": None,
            "schemaFingerprint": None,
            "localUpdatedAt": "2026-06-01T00:00:00.000Z",
        },
    }


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.sqlite3"


@pytest.fixture
def enable_session_memory(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Path:
    for mod in (config_mod, session_mod, audit_db):
        monkeypatch.setattr(mod.settings, "AUDIT_DB_ENABLED", False)
        monkeypatch.setattr(mod.settings, "SESSION_MEMORY_DB_ENABLED", True)
        monkeypatch.setattr(mod.settings, "AUDIT_DB_PATH", str(db_path))
        monkeypatch.setattr(mod.settings, "SESSION_MEMORY_TTL_DAYS", 7)
    return db_path


@pytest.fixture
def session_db_initialized(enable_session_memory: Path):
    async def setup_teardown():
        await audit_db.reset_audit_db_for_tests()
        await audit_db.init_audit_db()
        yield
        await audit_db.close_audit_db()
        await audit_db.reset_audit_db_for_tests()

    gen = setup_teardown()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gen.__anext__())
        yield enable_session_memory
    finally:
        try:
            loop.run_until_complete(gen.__anext__())
        except StopAsyncIteration:
            pass
        loop.close()


def test_session_memory_disabled_returns_503():
    client = TestClient(app)
    resp = client.get("/api/sessions/00000000-0000-4000-8000-000000000001")
    assert resp.status_code == 503


def test_put_get_round_trip(session_db_initialized):
    client = TestClient(app)
    session_id = "00000000-0000-4000-8000-000000000001"
    memory = _sample_memory(session_id)
    put = client.put(
        f"/api/sessions/{session_id}",
        json={
            "memory": memory,
            "projectId": "proj-1",
            "workspaceKeyHash": "abc123",
            "localUpdatedAt": "2026-06-01T00:00:00.000Z",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["sessionId"] == session_id
    assert body["version"] == 1
    assert body["memory"]["chatTranscript"][0]["content"] == "add total column"

    got = client.get(f"/api/sessions/{session_id}")
    assert got.status_code == 200
    assert got.json()["version"] == 1

    put2 = client.put(
        f"/api/sessions/{session_id}",
        json={
            "memory": {
                **memory,
                "appliedPlansSummary": "Applied total",
            },
            "expectedVersion": 1,
        },
    )
    assert put2.status_code == 200
    assert put2.json()["version"] == 2


def test_version_conflict_returns_409(session_db_initialized):
    client = TestClient(app)
    session_id = "00000000-0000-4000-8000-000000000002"
    memory = _sample_memory(session_id)
    assert client.put(f"/api/sessions/{session_id}", json={"memory": memory}).status_code == 200

    conflict = client.put(
        f"/api/sessions/{session_id}",
        json={"memory": memory, "expectedVersion": 99},
    )
    assert conflict.status_code == 409


def test_config_exposes_session_memory_flag(session_db_initialized, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "SESSION_MEMORY_DB_ENABLED", True)
    client = TestClient(app)
    cfg = client.get("/api/config").json()
    assert cfg["sessionMemoryEnabled"] is True
    assert cfg["sessionMemoryTtlDays"] == 7


def test_persists_row_in_sqlite(session_db_initialized):
    session_id = "00000000-0000-4000-8000-000000000003"
    memory = _sample_memory(session_id)
    client = TestClient(app)
    assert client.put(f"/api/sessions/{session_id}", json={"memory": memory}).status_code == 200

    async def _read_row():
        factory = audit_db.get_session_factory()
        assert factory is not None
        async with factory() as session:
            return await session.get(audit_db.SessionMemoryRow, session_id)

    loop = asyncio.new_event_loop()
    try:
        row = loop.run_until_complete(_read_row())
    finally:
        loop.close()
    assert row is not None
    payload = json.loads(row.memory_json)
    assert payload["chatTranscript"][0]["content"] == "add total column"


def test_get_missing_returns_404(session_db_initialized):
    client = TestClient(app)
    resp = client.get("/api/sessions/00000000-0000-4000-8000-000000000099")
    assert resp.status_code == 404
