"""SQLite persistence for HTTP and LLM audit logs (SQLAlchemy 2 async)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Float, Integer, String, Text, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings
from app.logging_config import get_logger

log = get_logger("services.audit_db")

_SERVER_ROOT = Path(__file__).resolve().parents[2]

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


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


async def init_audit_db() -> None:
    """Create engine, tables, and session factory when audit is enabled."""
    global _engine, _session_factory
    if not settings.AUDIT_DB_ENABLED:
        log.info("audit_db disabled (AUDIT_DB_ENABLED=0)")
        return
    if _engine is not None:
        return
    db_path = resolve_audit_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(
        audit_sqlite_url(),
        echo=False,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("audit_db ready path=%s", db_path)


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
