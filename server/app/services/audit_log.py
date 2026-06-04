"""Best-effort SQLite audit logging for HTTP requests and LLM calls."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.config import settings
from app.logging_config import get_logger, get_trace_id
from app.services import audit_db
from app.services.llm_debug_log import (
    build_error_payload,
    build_result_payload,
    prepare_messages_for_log,
    tool_names_from_spec,
)

log = get_logger("services.audit_log")


def is_audit_enabled() -> bool:
    return bool(settings.AUDIT_DB_ENABLED)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _max_body_chars() -> int:
    return max(1, int(settings.AUDIT_MAX_BODY_CHARS))


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _serialize_json(value: Any, *, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(value)
    limit = max_chars if max_chars is not None else _max_body_chars()
    return _truncate_text(raw, limit)


def workspace_key_hash(raw_key: str | None) -> str | None:
    """Hash workspace key for audit storage; never store plaintext unless explicitly enabled."""
    key = (raw_key or "").strip()
    if not key:
        return None
    if settings.AUDIT_STORE_WORKSPACE_KEY:
        return _truncate_text(key, 128)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def infer_request_kind(path: str) -> str | None:
    p = path.rstrip("/") or "/"
    if p == "/health":
        return "health"
    if p == "/api/load-sample":
        return "load_sample"
    if p == "/api/import-file":
        return "import"
    if p.endswith("/export-excel") or p == "/api/export-excel":
        return "export"
    if "/execute-plan" in p or p.endswith("/execute-plan"):
        return "execute"
    if p.endswith("/agent-stream") or p.endswith("/agent"):
        return "agent"
    if "/plan" in p:
        return "plan"
    return None


def infer_workspace_kind(path: str, request_kind: str | None) -> str | None:
    if request_kind == "load_sample":
        return "builtin_sample"
    if request_kind == "import":
        return "uploaded_file"
    return None


def _extract_from_mapping(data: dict[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {
        "project_id": None,
        "session_id": None,
        "model_tag": None,
    }
    for key in ("projectId", "project_id"):
        if data.get(key):
            out["project_id"] = str(data[key])
            break
    for key in ("sessionId", "session_id"):
        if data.get(key):
            out["session_id"] = str(data[key])
            break
    for key in ("modelTag", "model_tag"):
        if data.get(key):
            out["model_tag"] = str(data[key])
            break
    return out


def extract_audit_context(
    request: Request | None = None,
    *,
    body: Any = None,
    path: str | None = None,
) -> dict[str, str | None]:
    """Collect trace/session/project/model_tag/workspace fields from headers and JSON body."""
    ctx: dict[str, str | None] = {
        "trace_id": get_trace_id(),
        "project_id": None,
        "session_id": None,
        "model_tag": None,
        "workspace_key_hash": None,
        "workspace_kind": None,
        "request_kind": None,
    }
    req_path = path or (request.url.path if request else "")
    ctx["request_kind"] = infer_request_kind(req_path)
    ctx["workspace_kind"] = infer_workspace_kind(req_path, ctx["request_kind"])

    if request is not None:
        session_hdr = (request.headers.get("X-Session-ID") or "").strip()
        if session_hdr:
            ctx["session_id"] = session_hdr
        tag_hdr = (request.headers.get("X-Model-Tag") or "").strip()
        if tag_hdr:
            ctx["model_tag"] = tag_hdr
        ws_hdr = (request.headers.get("X-Workspace-Key") or "").strip()
        if ws_hdr:
            ctx["workspace_key_hash"] = workspace_key_hash(ws_hdr)

    if isinstance(body, dict):
        mapped = _extract_from_mapping(body)
        for k, v in mapped.items():
            if v and not ctx.get(k):
                ctx[k] = v

    return ctx


def _schedule(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        import threading

        def _run() -> None:
            try:
                asyncio.run(coro)
            except Exception as e:
                log.warning("audit_log background write failed: %s", e)

        threading.Thread(target=_run, daemon=True).start()


async def _insert_http_row(**fields: Any) -> None:
    factory = audit_db.get_session_factory()
    if factory is None:
        return
    async with factory() as session:
        row = audit_db.HttpRequestLog(**fields)
        session.add(row)
        await session.commit()


async def _insert_llm_row(**fields: Any) -> None:
    factory = audit_db.get_session_factory()
    if factory is None:
        return
    async with factory() as session:
        row = audit_db.LlmCallLog(**fields)
        session.add(row)
        await session.commit()


async def record_http_request(
    *,
    trace_id: str,
    method: str,
    path: str,
    query_params: dict[str, Any] | None = None,
    request_body: Any = None,
    response_status: int | None = None,
    response_body: Any = None,
    error_detail: str | None = None,
    duration_ms: float | None = None,
    client_host: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    workspace_key_hash: str | None = None,
    workspace_kind: str | None = None,
    model_tag: str | None = None,
    request_kind: str | None = None,
) -> None:
    """Persist one HTTP audit row; callers should schedule via ``schedule_record_http_request``."""
    if not is_audit_enabled():
        return
    try:
        await _insert_http_row(
            trace_id=trace_id or "-",
            project_id=project_id,
            session_id=session_id,
            workspace_key_hash=workspace_key_hash,
            workspace_kind=workspace_kind,
            model_tag=model_tag,
            method=method,
            path=path,
            query_params=_serialize_json(dict(query_params) if query_params else None),
            request_body=_serialize_json(request_body),
            response_status=response_status,
            response_body=_serialize_json(response_body),
            error_detail=_truncate_text(error_detail, _max_body_chars())
            if error_detail
            else None,
            duration_ms=duration_ms,
            client_host=client_host,
            request_kind=request_kind,
            created_at=_utc_now_iso(),
        )
    except Exception as e:
        log.warning("record_http_request failed: %s", e)


def schedule_record_http_request(**kwargs: Any) -> None:
    """Fire-and-forget HTTP audit write; never raises."""
    if not is_audit_enabled():
        return
    try:
        _schedule(record_http_request(**kwargs))
    except Exception as e:
        log.warning("schedule_record_http_request failed: %s", e)


async def record_llm_call(
    *,
    trace_id: str | None = None,
    call_kind: str,
    model_source: str,
    model: str,
    duration_ms: float,
    messages: list[Any],
    tools: list[dict[str, Any]] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    model_tag: str | None = None,
) -> None:
    """Persist one LLM audit row aligned with ``llm_debug_log`` field shapes."""
    if not is_audit_enabled():
        return
    try:
        msg_json = _serialize_json(prepare_messages_for_log(messages))
        tools_json = None
        if tools is not None:
            tools_json = _serialize_json(tool_names_from_spec(tools))
        await _insert_llm_row(
            trace_id=(trace_id or get_trace_id() or "-"),
            project_id=project_id,
            session_id=session_id,
            call_kind=call_kind,
            model_source=model_source,
            model=model,
            model_tag=model_tag,
            messages=msg_json,
            tools=tools_json,
            result=_serialize_json(result),
            error=_serialize_json(error),
            duration_ms=round(duration_ms, 2),
            created_at=_utc_now_iso(),
        )
    except Exception as e:
        log.warning("record_llm_call failed: %s", e)


def schedule_record_llm_call(**kwargs: Any) -> None:
    """Fire-and-forget LLM audit write; never raises."""
    if not is_audit_enabled():
        return
    try:
        _schedule(record_llm_call(**kwargs))
    except Exception as e:
        log.warning("schedule_record_llm_call failed: %s", e)


def parse_request_body_for_audit(
    body_bytes: bytes,
    *,
    path: str,
    content_type: str | None,
) -> Any:
    """Decode request body per route policy (JSON, metadata-only, or skip)."""
    kind = infer_request_kind(path)
    if kind == "health":
        return None
    if kind == "import":
        return {"_audit": "multipart_metadata_only"}
    if not body_bytes:
        return None
    ct = (content_type or "").lower()
    if "application/json" in ct or not ct:
        try:
            return json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _truncate_text(body_bytes.decode("utf-8", errors="replace"), _max_body_chars())
    return _truncate_text(
        f"<non-json body len={len(body_bytes)} content-type={content_type}>",
        _max_body_chars(),
    )


def parse_response_body_for_audit(
    body_bytes: bytes,
    *,
    path: str,
    content_type: str | None,
    is_streaming: bool,
) -> Any:
    if is_streaming:
        return {"response_kind": "sse"}
    kind = infer_request_kind(path)
    if kind == "export":
        return {
            "_audit": "binary_response",
            "content_type": content_type,
            "byte_length": len(body_bytes),
        }
    if kind == "health" and not body_bytes:
        return None
    if not body_bytes:
        return None
    ct = (content_type or "").lower()
    if "application/json" in ct or not ct:
        try:
            return json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _truncate_text(body_bytes.decode("utf-8", errors="replace"), _max_body_chars())
    return _truncate_text(
        f"<non-json response len={len(body_bytes)} content-type={content_type}>",
        _max_body_chars(),
    )
