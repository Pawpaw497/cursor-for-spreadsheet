"""Structured logs for agent clarification issuance and resolution."""
from __future__ import annotations

from app.agent.actions import ClarificationPayload
from app.logging_config import get_logger, get_trace_id

log = get_logger("agent.clarification")

_PREVIEW_LIMIT = 80


def _truncate(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def log_clarification_issued(
    payload: ClarificationPayload,
    *,
    source: str,
) -> None:
    """Emit ``agent_clarification`` when a clarification action is issued."""
    log.info(
        "agent_clarification",
        extra={
            "trace_id": get_trace_id(),
            "source": source,
            "question_preview": _truncate(payload.question or ""),
            "options_count": len(payload.options) if payload.options else 0,
        },
    )


def log_clarification_resolved(
    *,
    reply: str,
    turn_id: str | None = None,
) -> None:
    """Emit ``clarification_resolved`` when ``clarificationReply`` is merged."""
    log.info(
        "clarification_resolved",
        extra={
            "trace_id": get_trace_id(),
            "turn_id": turn_id,
            "reply_length": len(reply),
        },
    )
