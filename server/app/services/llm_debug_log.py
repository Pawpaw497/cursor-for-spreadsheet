"""Optional NDJSON debug logs for upstream LLM calls (local disk only)."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.logging_config import get_logger, get_trace_id
from app.services.prompts import Message

log = get_logger("services.llm_debug_log")

_write_lock = threading.Lock()
_UNSAFE_FILENAME = re.compile(r"[^\w.\-]+", re.ASCII)


def is_llm_debug_enabled() -> bool:
    """True when ``LLM_DEBUG_LOG_DIR`` is set to a non-empty path."""
    return bool((settings.LLM_DEBUG_LOG_DIR or "").strip())


def _max_content_chars() -> int:
    return max(1, int(settings.LLM_DEBUG_MAX_CHARS))


def _sanitize_trace_id(trace_id: str | None) -> str:
    raw = (trace_id or "").strip() or "-"
    safe = _UNSAFE_FILENAME.sub("_", raw)
    return safe[:128] or "-"


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "…", True


def _truncate_value(value: Any, max_chars: int) -> tuple[Any, bool]:
    if isinstance(value, str):
        out, truncated = _truncate_text(value, max_chars)
        return out, truncated
    if isinstance(value, (dict, list)):
        try:
            serialized = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized = str(value)
        if len(serialized) <= max_chars:
            return value, False
        out, truncated = _truncate_text(serialized, max_chars)
        return out, truncated
    return value, False


def _truncate_message_dict(msg: dict[str, Any], max_chars: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    truncated = False
    for key, value in msg.items():
        if key == "content" and value is not None:
            t, tr = _truncate_value(str(value), max_chars)
            out[key] = t
            truncated = truncated or tr
        elif key == "tool_calls" and isinstance(value, list):
            tc_out: list[Any] = []
            for tc in value:
                if not isinstance(tc, dict):
                    tc_out.append(tc)
                    continue
                tc_copy = dict(tc)
                fn = tc_copy.get("function")
                if isinstance(fn, dict) and "arguments" in fn:
                    fn_copy = dict(fn)
                    t, tr = _truncate_value(str(fn_copy.get("arguments", "")), max_chars)
                    fn_copy["arguments"] = t
                    tc_copy["function"] = fn_copy
                    truncated = truncated or tr
                tc_out.append(tc_copy)
            out[key] = tc_out
        else:
            t, tr = _truncate_value(value, max_chars)
            out[key] = t
            truncated = truncated or tr
    if truncated:
        out["truncated"] = True
    return out


def prepare_messages_for_log(messages: list[Any]) -> list[dict[str, Any]]:
    """Shallow-copy messages as dicts with truncated large fields."""
    max_chars = _max_content_chars()
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, Message):
            out.append(_truncate_message_dict(m.to_dict(), max_chars))
        elif isinstance(m, dict):
            out.append(_truncate_message_dict(dict(m), max_chars))
        else:
            out.append(_truncate_message_dict({"role": "user", "content": str(m)}, max_chars))
    return out


def tool_names_from_spec(tools: list[dict[str, Any]]) -> list[str]:
    """Extract tool function names for compact logging."""
    names: list[str] = []
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            names.append(str(fn["name"]))
        elif isinstance(t, dict) and t.get("name"):
            names.append(str(t["name"]))
    return names


def build_result_payload(
    *,
    content: str | None = None,
    tool_calls: list[dict] | None = None,
) -> dict[str, Any]:
    max_chars = _max_content_chars()
    result: dict[str, Any] = {}
    if content is not None:
        text, truncated = _truncate_text(content, max_chars)
        result["content"] = text
        if truncated:
            result["truncated"] = True
    if tool_calls is not None:
        result["tool_calls"] = tool_calls
    return result


def build_error_payload(exc: BaseException) -> dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(exc)}


def append_record(trace_id: str | None, payload: dict[str, Any]) -> None:
    """Append one JSON line under ``LLM_DEBUG_LOG_DIR``; never raises to caller."""
    base = (settings.LLM_DEBUG_LOG_DIR or "").strip()
    if not base:
        return
    try:
        tid = _sanitize_trace_id(trace_id or get_trace_id())
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = Path(base).expanduser() / day / f"{tid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with _write_lock:
            path.open("a", encoding="utf-8").write(line)
    except Exception as e:
        log.warning("llm_debug_log append failed: %s", e)


def log_llm_call(
    *,
    call: str,
    model_source: str,
    model: str,
    duration_ms: float,
    messages: list[Any],
    tools: list[dict[str, Any]] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """Best-effort structured record for one upstream LLM round-trip."""
    from app.services.audit_log import schedule_record_llm_call

    tid = trace_id or get_trace_id() or "-"
    schedule_record_llm_call(
        trace_id=tid,
        call_kind=call,
        model_source=model_source,
        model=model,
        duration_ms=duration_ms,
        messages=messages,
        tools=tools,
        result=result,
        error=error,
    )
    if not is_llm_debug_enabled():
        return
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "trace_id": tid,
        "call": call,
        "model_source": model_source,
        "model": model,
        "duration_ms": round(duration_ms, 2),
        "messages": prepare_messages_for_log(messages),
    }
    if tools is not None:
        record["tools"] = tool_names_from_spec(tools)
    if result is not None:
        record["result"] = result
    if error is not None:
        record["error"] = error
    append_record(record["trace_id"], record)
