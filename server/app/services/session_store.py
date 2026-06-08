"""SQLite-backed optional server session memory (Stage 6)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.config import settings
from app.logging_config import get_logger
from app.models.session_memory_models import (
    AgentSessionMemoryPayload,
    SessionPutRequest,
    SessionResponse,
)
from app.services import audit_db

log = get_logger("services.session_store")


def is_session_memory_enabled() -> bool:
    return bool(settings.SESSION_MEMORY_DB_ENABLED)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _expires_at_iso() -> str:
    days = max(1, int(settings.SESSION_MEMORY_TTL_DAYS))
    return (_utc_now() + timedelta(days=days)).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _memory_to_json(memory: AgentSessionMemoryPayload) -> str:
    return json.dumps(memory.model_dump(by_alias=True), ensure_ascii=False)


def _memory_from_json(raw: str) -> AgentSessionMemoryPayload:
    data = json.loads(raw)
    return AgentSessionMemoryPayload.model_validate(data)


async def purge_expired_sessions() -> int:
    """Delete expired rows; returns count removed."""
    factory = audit_db.get_session_factory()
    if factory is None:
        return 0
    now_iso = _utc_now_iso()
    async with factory() as session:
        result = await session.execute(
            delete(audit_db.SessionMemoryRow).where(
                audit_db.SessionMemoryRow.expires_at.is_not(None),
                audit_db.SessionMemoryRow.expires_at < now_iso,
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


async def get_session(session_id: str) -> SessionResponse | None:
    if not is_session_memory_enabled():
        return None
    factory = audit_db.get_session_factory()
    if factory is None:
        return None
    sid = session_id.strip()
    if not sid:
        return None
    await purge_expired_sessions()
    async with factory() as session:
        row = await session.get(audit_db.SessionMemoryRow, sid)
        if row is None:
            return None
        expires = _parse_iso(row.expires_at)
        if row.expires_at and expires is not None and expires < _utc_now():
            await session.delete(row)
            await session.commit()
            return None
        memory = _memory_from_json(row.memory_json)
        return SessionResponse(
            sessionId=row.session_id,
            version=row.version,
            updatedAt=row.updated_at,
            memory=memory,
        )


async def put_session(session_id: str, body: SessionPutRequest) -> SessionResponse:
    if not is_session_memory_enabled():
        raise HTTPException(status_code=503, detail="Session memory store is disabled")
    factory = audit_db.get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Session memory database is unavailable")

    sid = session_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="sessionId is required")

    memory = body.memory
    meta = memory.session_meta
    if meta.session_id.strip() and meta.session_id.strip() != sid:
        raise HTTPException(status_code=400, detail="memory.sessionMeta.sessionId must match path sessionId")

    memory = memory.model_copy(
        update={
            "session_meta": meta.model_copy(update={"session_id": sid}),
        }
    )

    now_iso = _utc_now_iso()
    expires_iso = _expires_at_iso()
    memory_json = _memory_to_json(memory)

    async with factory() as session:
        row = await session.get(audit_db.SessionMemoryRow, sid)
        if row is not None:
            expires = _parse_iso(row.expires_at)
            if row.expires_at and expires is not None and expires < _utc_now():
                await session.delete(row)
                row = None

        if row is not None and body.expected_version is not None:
            if row.version != body.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Session version conflict",
                        "currentVersion": row.version,
                        "updatedAt": row.updated_at,
                    },
                )

        if row is None:
            row = audit_db.SessionMemoryRow(
                session_id=sid,
                workspace_key_hash=(body.workspace_key_hash or "").strip() or None,
                project_id=(body.project_id or "").strip() or None,
                version=1,
                memory_json=memory_json,
                updated_at=now_iso,
                expires_at=expires_iso,
            )
            session.add(row)
        else:
            row.version = row.version + 1
            row.memory_json = memory_json
            row.updated_at = now_iso
            row.expires_at = expires_iso
            if body.project_id:
                row.project_id = body.project_id.strip() or row.project_id
            if body.workspace_key_hash:
                row.workspace_key_hash = body.workspace_key_hash.strip() or row.workspace_key_hash

        await session.commit()
        await session.refresh(row)
        log.info(
            "session_store put session_id=%s version=%d project_id=%s",
            sid,
            row.version,
            row.project_id,
        )
        return SessionResponse(
            sessionId=row.session_id,
            version=row.version,
            updatedAt=row.updated_at,
            memory=_memory_from_json(row.memory_json),
        )


def redact_session_body_for_audit(body: Any) -> Any:
    """Strip heavy memory payload from audit rows for session sync routes."""
    if not isinstance(body, dict):
        return body
    memory = body.get("memory")
    if not isinstance(memory, dict):
        return {
            "_audit": "session_sync_metadata_only",
            "keys": sorted(body.keys()),
        }
    return {
        "_audit": "session_sync_metadata_only",
        "projectId": body.get("projectId"),
        "workspaceKeyHash": body.get("workspaceKeyHash"),
        "expectedVersion": body.get("expectedVersion"),
        "localUpdatedAt": body.get("localUpdatedAt"),
        "memory": {
            "version": memory.get("version"),
            "chatTranscriptCount": len(memory.get("chatTranscript") or []),
            "agentTranscriptCount": len(memory.get("agentTranscript") or []),
            "applyLogCount": len(memory.get("applyLog") or []),
            "previewHistoryCount": len(memory.get("previewHistory") or []),
            "appliedPlansSummaryChars": len(str(memory.get("appliedPlansSummary") or "")),
        },
    }
