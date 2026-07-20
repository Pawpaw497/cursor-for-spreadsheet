"""SQLite audit logging: DB writes, middleware, PA hook, privacy, tolerance."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config as config_mod
from app.agent.pa_decision import PaTurnResult, pa_decision_step
from app.config import settings
from app.logging_config import reset_trace_id, set_trace_id
from app.main import app
from app.models.agent_models import AgentState, TableContext
from app.models.plan import Plan
from app.services import audit_db
from app.services import audit_log as audit_mod


async def _flush_audit_tasks() -> None:
    await asyncio.sleep(0.05)


def _schedule_audit_sync(**kwargs: object) -> None:
    """Test helper: complete HTTP audit write before middleware returns (avoids CI races)."""

    def _run() -> None:
        asyncio.run(audit_mod.record_http_request(**kwargs))

    thread = __import__("threading").Thread(target=_run)
    thread.start()
    thread.join(timeout=5.0)
    assert not thread.is_alive(), "audit HTTP write timed out"


async def _http_rows(trace_id: str) -> list[audit_db.HttpRequestLog]:
    factory = audit_db.get_session_factory()
    assert factory is not None
    async with factory() as session:
        result = await session.execute(
            select(audit_db.HttpRequestLog).where(
                audit_db.HttpRequestLog.trace_id == trace_id
            )
        )
        return list(result.scalars().all())


async def _llm_rows(trace_id: str | None = None) -> list[audit_db.LlmCallLog]:
    factory = audit_db.get_session_factory()
    assert factory is not None
    async with factory() as session:
        stmt = select(audit_db.LlmCallLog)
        if trace_id:
            stmt = stmt.where(audit_db.LlmCallLog.trace_id == trace_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


@pytest.fixture
def audit_db_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.sqlite3"


@pytest.fixture
def enable_audit(monkeypatch: pytest.MonkeyPatch, audit_db_path: Path) -> Path:
    for mod in (config_mod, audit_mod, audit_db):
        monkeypatch.setattr(mod.settings, "AUDIT_DB_ENABLED", True)
        monkeypatch.setattr(mod.settings, "AUDIT_DB_PATH", str(audit_db_path))
    return audit_db_path


@pytest.fixture
def audit_initialized(enable_audit: Path):
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
        yield enable_audit
    finally:
        try:
            loop.run_until_complete(gen.__anext__())
        except StopAsyncIteration:
            pass
        loop.close()


def test_record_http_and_llm_roundtrip(audit_initialized: Path) -> None:
    async def run() -> None:
        token = set_trace_id("trace-db-unit")
        try:
            await audit_mod.record_http_request(
                trace_id="trace-db-unit",
                method="POST",
                path="/api/agent",
                request_body={"prompt": "hi"},
                response_status=200,
                response_body={"ok": True},
                duration_ms=12.5,
                request_kind="agent",
            )
            await audit_mod.record_llm_call(
                trace_id="trace-db-unit",
                call_kind="plain",
                model_source="cloud",
                model="test/model",
                duration_ms=50.0,
                messages=[{"role": "user", "content": "hello"}],
                result={"content": "ok"},
            )
        finally:
            reset_trace_id(token)

        http = await _http_rows("trace-db-unit")
        llm = await _llm_rows("trace-db-unit")
        assert len(http) == 1
        assert http[0].response_status == 200
        assert json.loads(http[0].request_body or "{}")["prompt"] == "hi"
        assert len(llm) == 1
        assert llm[0].call_kind == "plain"
        assert llm[0].model == "test/model"

    asyncio.run(run())


def test_workspace_key_stored_as_hash_only() -> None:
    raw = "workspace:file:abc123"
    hashed = audit_mod.workspace_key_hash(raw)
    assert hashed != raw
    assert len(hashed) == 64


def test_audit_log_module_has_no_memory_writes() -> None:
    path = Path(audit_mod.__file__)
    text = path.read_text(encoding="utf-8")
    assert "WorkspaceMemory" not in text
    assert "memory_compaction" not in text
    assert "AgentSessionMemory" not in text


def test_middleware_records_agent_request(
    audit_initialized: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "k")
    plan = Plan.model_validate(
        {
            "intent": "x",
            "steps": [{"action": "add_column", "name": "c", "expression": "1"}],
        }
    )
    turn = PaTurnResult(tool_parts=[], text="", structured_plan=plan)

    monkeypatch.setattr("app.main.schedule_record_http_request", _schedule_audit_sync)

    body = {
        "prompt": "add column",
        "tables": [
            {
                "name": "Sheet1",
                "schema": [{"key": "a", "type": "string"}],
            }
        ],
        "modelSource": "cloud",
        "previewLifecycle": False,
    }
    with patch(
        "app.agent.pa_decision._run_pa_single_turn",
        new=AsyncMock(return_value=turn),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/agent",
                json=body,
                headers={"X-Request-ID": "trace-mw-agent"},
            )
            assert resp.status_code == 200

    async def check() -> None:
        # App lifespan may close the engine after TestClient exits; reconnect to the same DB file.
        await audit_db.init_audit_db()
        rows = await _http_rows("trace-mw-agent")
        assert len(rows) >= 1
        row = rows[0]
        assert row.method == "POST"
        assert row.path == "/api/agent"
        assert row.request_kind == "agent"
        assert row.response_status == 200

    asyncio.run(check())


def test_request_ok_when_audit_insert_fails(
    monkeypatch: pytest.MonkeyPatch, enable_audit: Path
) -> None:
    async def boom(**kwargs: object) -> None:
        raise OSError("audit write failed")

    monkeypatch.setattr(audit_mod, "_insert_http_row", boom)
    monkeypatch.setattr(audit_mod.settings, "AUDIT_DB_ENABLED", True)

    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200


def test_pa_turn_writes_llm_log(
    audit_initialized: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "k")
    plan = Plan.model_validate(
        {"intent": "x", "steps": [{"action": "add_column", "name": "c", "expression": "1"}]}
    )
    state = AgentState(
        tables=[
            TableContext(
                name="Sheet1",
                schema=[{"key": "a", "type": "string"}],
            )
        ],
        messages=[],
        user_prompt="Add column",
        model_source="cloud",
    )
    turn = PaTurnResult(tool_parts=[], text="", structured_plan=plan)

    async def run() -> None:
        token = set_trace_id("trace-pa-turn")
        try:
            with patch(
                "app.agent.pa_decision._run_pa_single_turn",
                new=AsyncMock(return_value=turn),
            ):
                await pa_decision_step(state, use_tools=True)
            await _flush_audit_tasks()
            rows = await _llm_rows("trace-pa-turn")
            assert any(r.call_kind == "pa_turn" for r in rows)
        finally:
            reset_trace_id(token)

    asyncio.run(run())


def test_agent_body_audited_without_memory_side_effects(
    audit_initialized: Path,
) -> None:
    """Large memory-shaped fields may be stored in audit only — no memory module coupling."""

    async def run() -> None:
        await audit_mod.record_http_request(
            trace_id="trace-agent-mem",
            method="POST",
            path="/api/agent",
            request_body={
                "appliedPlansSummary": "prior plan summary",
                "previewHistory": [{"id": "p1", "status": "pending"}],
            },
            response_status=200,
            duration_ms=1.0,
            request_kind="agent",
        )
        rows = await _http_rows("trace-agent-mem")
        assert len(rows) == 1
        body = json.loads(rows[0].request_body or "{}")
        assert "appliedPlansSummary" in body

    asyncio.run(run())


def test_log_llm_call_schedules_db_even_without_ndjson(
    audit_initialized: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import llm_debug_log as debug_mod

    monkeypatch.setattr(debug_mod.settings, "LLM_DEBUG_LOG_DIR", "")
    token = set_trace_id("trace-llm-dual")
    try:
        debug_mod.log_llm_call(
            call="plain",
            model_source="cloud",
            model="m",
            duration_ms=1.0,
            messages=[{"role": "user", "content": "x"}],
            result={"content": "y"},
        )
    finally:
        reset_trace_id(token)

    async def check() -> None:
        await _flush_audit_tasks()
        for _ in range(20):
            rows = await _llm_rows("trace-llm-dual")
            if rows:
                break
            await asyncio.sleep(0.05)
        assert len(rows) == 1

    asyncio.run(check())
