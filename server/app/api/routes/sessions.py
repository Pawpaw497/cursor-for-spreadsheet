"""Optional server session memory API (Stage 6)."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.models.session_memory_models import SessionPutRequest, SessionResponse
from app.services.session_store import get_session, is_session_memory_enabled, put_session

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_SESSION_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    r"|^sess-[0-9A-Za-z-]+$"
)


def _validate_session_id(session_id: str) -> str:
    sid = session_id.strip()
    if not sid or not _SESSION_ID_RE.match(sid):
        raise HTTPException(status_code=400, detail="Invalid sessionId")
    return sid


@router.get("/{session_id}", response_model=SessionResponse)
async def read_session(session_id: str):
    if not is_session_memory_enabled():
        raise HTTPException(status_code=503, detail="Session memory store is disabled")
    sid = _validate_session_id(session_id)
    row = await get_session(sid)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.put("/{session_id}", response_model=SessionResponse)
async def write_session(session_id: str, body: SessionPutRequest):
    sid = _validate_session_id(session_id)
    return await put_session(sid, body)
