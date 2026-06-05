"""Explicit Agent context package assembly (Memory Blueprint Stage 4)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.memory_context import build_memory_context_block
from app.models.agent_models import AgentState, TableContext
from app.models.plan import AgentRequestContext


class AgentContextPackage(BaseModel):
    """Versioned context slices for one Agent LLM call."""

    tables: list[TableContext]
    selection: AgentRequestContext | None = None
    workspace_rules: str | None = None
    memory_block: str = ""
    transcript_summary: str = ""
    selection_context_text: str | None = None


def _summarize_transcript(messages: list[dict[str, Any]], *, max_turns: int = 6) -> str:
    """Compact reference to prior transcript turns (not full replay)."""
    if not messages:
        return ""
    lines: list[str] = []
    for m in messages[-max_turns:]:
        role = str(m.get("role") or "user")
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if len(content) > 120:
            content = content[:117] + "…"
        lines.append(f"- {role}: {content}")
    if not lines:
        return ""
    omitted = len(messages) - min(len(messages), max_turns)
    header = "Prior transcript (recent turns):"
    if omitted > 0:
        header = f"Prior transcript ({omitted} earlier turn(s) omitted, recent):"
    return header + "\n" + "\n".join(lines)


def build_selection_context_text(ctx: AgentRequestContext | None) -> str | None:
    """Human-readable selection + workspace rules snippet for prompt injection."""
    if ctx is None:
        return None

    parts: list[str] = []
    rules = (ctx.workspaceRules or "").strip()
    if rules:
        parts.append(f"Workspace rules:\n{rules}")

    selection_lines: list[str] = []
    if ctx.activeTable:
        selection_lines.append(f"Active table: {ctx.activeTable}")
    if ctx.focusedColumn:
        selection_lines.append(f"Focused column: {ctx.focusedColumn}")
    if ctx.selectedRange is not None:
        r = ctx.selectedRange
        start = r.startRow + 1
        end = r.endRow + 1
        if r.colIds:
            cols = ", ".join(r.colIds)
            selection_lines.append(
                f"Selected range on {ctx.activeTable or 'table'}: "
                f"rows {start}–{end}, columns {cols}"
            )
        else:
            selection_lines.append(
                f"Selected rows on {ctx.activeTable or 'table'}: {start}–{end}"
            )
    if selection_lines:
        parts.append("Current selection:\n" + "\n".join(f"- {line}" for line in selection_lines))

    if not parts:
        return None
    return "\n\n".join(parts)


def selection_context_user_message(ctx: AgentRequestContext | None) -> dict[str, str] | None:
    """OpenAI-shaped user message for selection / workspace rules."""
    text = build_selection_context_text(ctx)
    if not text:
        return None
    return {"role": "user", "content": text}


def assemble_agent_context(
    state: AgentState,
    request_extras: AgentRequestContext | None = None,
) -> AgentContextPackage:
    """Build explicit context package for one Agent call."""
    ctx = request_extras or state.request_context
    rules = (ctx.workspaceRules or "").strip() if ctx else None
    return AgentContextPackage(
        tables=list(state.tables),
        selection=ctx,
        workspace_rules=rules or None,
        memory_block=build_memory_context_block(state),
        transcript_summary=_summarize_transcript(state.messages),
        selection_context_text=build_selection_context_text(ctx),
    )
