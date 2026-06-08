"""Deterministic middle-out message compaction (Memory Blueprint Stage 5)."""
from __future__ import annotations

from typing import Any

from app.models.agent_models import AgentState

MAX_CHAT_TURNS = 24
MAX_TOOL_MESSAGES = 12
DEFAULT_PRESERVE_TAIL_COUNT = 2

EARLIER_PREFIX = "Earlier in this workspace:\n"


def _is_tool_related(msg: dict[str, Any]) -> bool:
    role = msg.get("role")
    if role == "tool":
        return True
    if role == "assistant" and msg.get("tool_calls"):
        return True
    return False


def _is_table_context_message(msg: dict[str, Any]) -> bool:
    if msg.get("role") != "user":
        return False
    content = str(msg.get("content") or "")
    return "Spreadsheet schema:" in content or "Project has multiple tables:" in content


def _is_selection_context_message(msg: dict[str, Any]) -> bool:
    if msg.get("role") != "user":
        return False
    content = str(msg.get("content") or "")
    return "Current selection:" in content or "Workspace rules:" in content


def _protected_message_indices(messages: list[dict[str, Any]]) -> set[int]:
    """Selection + table-context user messages are never dropped."""
    return {
        i
        for i, m in enumerate(messages)
        if _is_table_context_message(m) or _is_selection_context_message(m)
    }


def _digest_tool_message(msg: dict[str, Any]) -> str:
    role = msg.get("role")
    if role == "tool":
        content = str(msg.get("content") or "").strip()
        if len(content) > 80:
            content = content[:77] + "…"
        tid = msg.get("tool_call_id") or "?"
        return f"- tool result ({tid}): {content or '(empty)'}"
    if role == "assistant":
        names: list[str] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            names.append(str(fn.get("name") or "?"))
        if names:
            return f"- called {', '.join(names)}"
    return ""


def _build_earlier_summary(
    *,
    applied_plans_summary: str | None,
    tool_digests: list[str],
) -> str:
    parts: list[str] = []
    summary = (applied_plans_summary or "").strip()
    if summary:
        parts.append(summary)
    if tool_digests:
        parts.append("Prior tool calls:\n" + "\n".join(tool_digests))
    body = "\n\n".join(parts) if parts else "(no prior context recorded)"
    return EARLIER_PREFIX + body


def detect_preserve_tail_count(messages: list[dict[str, Any]]) -> int:
    """Infer how many trailing messages must stay verbatim (selection + table context)."""
    if not messages:
        return 0
    count = 0
    if _is_table_context_message(messages[-1]):
        count = 1
        if len(messages) >= 2 and _is_selection_context_message(messages[-2]):
            count = 2
    return count


def compact_agent_messages(
    messages: list[dict[str, Any]],
    *,
    applied_plans_summary: str | None = None,
    max_chat_turns: int = MAX_CHAT_TURNS,
    max_tool_messages: int = MAX_TOOL_MESSAGES,
    preserve_tail_count: int = DEFAULT_PRESERVE_TAIL_COUNT,
) -> list[dict[str, Any]]:
    """Compact prefix history; preserve trailing selection/table-context messages."""
    if not messages:
        return []

    if preserve_tail_count > 0:
        tail = list(messages[-preserve_tail_count:])
        prefix = list(messages[:-preserve_tail_count])
    else:
        tail = []
        prefix = list(messages)

    if not prefix:
        return list(messages)

    protected = _protected_message_indices(prefix)
    compactable_indices = [i for i in range(len(prefix)) if i not in protected]

    plain_chat_idx = [i for i in compactable_indices if not _is_tool_related(prefix[i])]
    tool_idx = [i for i in compactable_indices if _is_tool_related(prefix[i])]

    dropped_chat = (
        plain_chat_idx[:-max_chat_turns] if len(plain_chat_idx) > max_chat_turns else []
    )
    kept_chat = (
        plain_chat_idx[-max_chat_turns:]
        if len(plain_chat_idx) > max_chat_turns
        else plain_chat_idx
    )

    dropped_tools = (
        tool_idx[:-max_tool_messages] if len(tool_idx) > max_tool_messages else []
    )
    kept_tools = (
        tool_idx[-max_tool_messages:]
        if len(tool_idx) > max_tool_messages
        else tool_idx
    )

    kept_indices = set(kept_chat) | set(kept_tools) | protected
    need_summary = bool(dropped_chat or dropped_tools)

    tool_digests = [
        d
        for i in dropped_tools
        if (d := _digest_tool_message(prefix[i]))
    ]

    result: list[dict[str, Any]] = []
    if need_summary:
        result.append(
            {
                "role": "user",
                "content": _build_earlier_summary(
                    applied_plans_summary=applied_plans_summary,
                    tool_digests=tool_digests,
                ),
            }
        )

    for i, msg in enumerate(prefix):
        if i in kept_indices:
            result.append(msg)

    return result + tail


def apply_message_compaction(state: AgentState) -> AgentState:
    """Return state with ``messages`` compacted before an LLM decision step."""
    messages = state.messages
    if not messages:
        return state

    has_tools = any(
        m.get("role") == "tool" or m.get("tool_calls") for m in messages
    )
    if has_tools:
        preserve = 0
    else:
        preserve = detect_preserve_tail_count(messages)
        if preserve == 0 and len(messages) <= MAX_CHAT_TURNS:
            return state

    compacted = compact_agent_messages(
        messages,
        applied_plans_summary=state.applied_plans_summary,
        preserve_tail_count=preserve,
    )
    if compacted == messages:
        return state
    return state.model_copy(update={"messages": compacted})
