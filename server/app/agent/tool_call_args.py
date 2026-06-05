"""Coerce malformed LLM tool call arguments into validated parameter dicts."""
from __future__ import annotations

import json
from typing import Any

from app.agent.pa_tools import PA_TOOL_DEFINITIONS
from app.logging_config import get_logger
from app.services.prompts import extract_json

log = get_logger("agent.tool_call_args")

_TOOL_BY_NAME = {spec.name: spec for spec in PA_TOOL_DEFINITIONS}


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(extract_json(stripped))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_raw(tool_name: str, args: Any) -> dict[str, Any] | None:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        as_obj = _parse_json_object(args)
        if as_obj is not None:
            return as_obj
        if tool_name == "validate_expression" and args.strip():
            return {"expression": args.strip()}
        return None
    return None


def coerce_tool_call_args(tool_name: str, args: Any) -> dict[str, Any] | None:
    """Return validated tool args, or None when arguments cannot be recovered."""
    raw = _coerce_raw(tool_name, args)
    if raw is None:
        return None

    spec = _TOOL_BY_NAME.get(tool_name)
    if spec is None:
        log.warning("coerce_tool_call_args unknown tool=%s", tool_name)
        return raw

    try:
        validated = spec.args_model.model_validate(raw)
        return validated.model_dump(exclude_none=True)
    except Exception as e:
        log.warning(
            "coerce_tool_call_args validation failed tool=%s err=%s",
            tool_name,
            e,
        )
        return None
