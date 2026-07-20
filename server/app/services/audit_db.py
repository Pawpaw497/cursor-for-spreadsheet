"""SQLite persistence for HTTP and LLM audit logs (SQLAlchemy 2 async)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Float, Integer, String, Text, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.config import settings
from app.logging_config import get_logger

log = get_logger("services.audit_db")

_SERVER_ROOT = Path(__file__).resolve().parents[2]

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# sqlite3 defaults to timeout=5.0 (busy_timeout=5000); a loaded CI runner exceeded that
# while the HTTP and pa_turn audit writes contended, and the row was silently dropped.
# Align with data_store.py's 30s budget.
_SQLITE_CONNECT_TIMEOUT_S = 30.0
_SQLITE_BUSY_TIMEOUT_MS = int(_SQLITE_CONNECT_TIMEOUT_S * 1000)


class Base(DeclarativeBase):
    """Declarative base for audit tables."""


class HttpRequestLog(Base):
    __tablename__ = "http_request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    workspace_key_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    workspace_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    query_params: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    client_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class SessionMemoryRow(Base):
    """Compressed product session memory (Stage 6); separate from audit rows."""

    __tablename__ = "session_memory"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_key_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    memory_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    call_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    model_source: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    model_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    messages: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


def resolve_audit_db_path() -> Path:
    """Resolve SQLite file path (relative paths are under ``server/``)."""
    raw = (settings.AUDIT_DB_PATH or "data/audit.sqlite3").strip()
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    parts = p.parts
    if parts and parts[0] == "server":
        return _SERVER_ROOT.parent / p
    return _SERVER_ROOT / p


def audit_sqlite_url() -> str:
    path = resolve_audit_db_path()
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    return _session_factory


def is_sqlite_persistence_enabled() -> bool:
    """True when audit and/or session memory needs the shared SQLite file."""
    return bool(settings.AUDIT_DB_ENABLED or settings.SESSION_MEMORY_DB_ENABLED)


async def init_audit_db() -> None:
    """Create engine, tables, and session factory when audit or session memory is enabled."""
    global _engine, _session_factory
    if not is_sqlite_persistence_enabled():
        log.info(
            "sqlite persistence disabled (AUDIT_DB_ENABLED=0, SESSION_MEMORY_DB_ENABLED=0)"
        )
        return
    if _engine is not None:
        return
    db_path = resolve_audit_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(
        audit_sqlite_url(),
        echo=False,
        connect_args={"timeout": _SQLITE_CONNECT_TIMEOUT_S},
        # Audit writes come from two event loops: the app loop (pa_turn LLM rows) and
        # short-lived loops in background threads (`audit_log._schedule` falls back to
        # `asyncio.run` when no loop is running). A pooled connection created on one
        # loop must never be handed to another -- that raises "Future attached to a
        # different loop", which WAL/busy_timeout/retry cannot recover from. NullPool
        # gives every session its own connection bound to the current loop; the cost is
        # acceptable for fire-and-forget single-row inserts.
        poolclass=NullPool,
    )

    @event.listens_for(_engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        # busy_timeout is per-connection, so it must be set on every connect rather
        # than once at init. WAL shortens the window writers block each other for.
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info(
        "sqlite persistence ready path=%s audit=%s session_memory=%s",
        db_path,
        settings.AUDIT_DB_ENABLED,
        settings.SESSION_MEMORY_DB_ENABLED,
    )


async def close_audit_db() -> None:
    """Dispose async engine on shutdown."""
    global _engine, _session_factory
    if _engine is None:
        return
    await _engine.dispose()
    _engine = None
    _session_factory = None
    log.info("audit_db closed")


async def ping_audit_db() -> bool:
    """Lightweight connectivity check for tests."""
    if _engine is None:
        return False
    async with _engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def reset_audit_db_for_tests() -> None:
    """Dispose engine between tests (test-only)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
