"""Structured logs for agent preview revision and cap events."""
from __future__ import annotations

from app.logging_config import get_logger, get_trace_id

log = get_logger("agent.preview")

_PREVIEW_LIMIT = 120


def _truncate(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def log_preview_revision(
    *,
    revision_count: int,
    preview_id: str | None = None,
    source: str,
    reason_preview: str | None = None,
) -> None:
    """Emit ``agent_preview_revision`` when a preview revision cycle starts."""
    extra: dict[str, object] = {
        "trace_id": get_trace_id(),
        "source": source,
        "revision_count": revision_count,
        "preview_id": preview_id,
    }
    if reason_preview:
        extra["reason_preview"] = _truncate(reason_preview)
    log.info("agent_preview_revision", extra=extra)


def log_preview_cap_hit(
    *,
    revision_count: int,
    preview_id: str | None = None,
    source: str = "auto_revise",
) -> None:
    """Emit ``agent_preview_cap_hit`` when revision cap is reached."""
    log.info(
        "agent_preview_cap_hit",
        extra={
            "trace_id": get_trace_id(),
            "source": source,
            "revision_count": revision_count,
            "cap_hit": True,
            "preview_id": preview_id,
        },
    )
