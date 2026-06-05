"""Agent memory block assembly for LLM prompt injection (Stage 1–3)."""
from __future__ import annotations

from app.models.agent_models import AgentState, PreviewRecord

_APPLIED_PLANS_HEADER = "Applied plans in this session:"
_PREVIEW_LINEAGE_HEADER = "Preview lineage:"


def _preview_lineage_lines(preview_history: list[PreviewRecord]) -> list[str]:
    """Surface aborted/revised previews so follow-ups can reference them."""
    lines: list[str] = []
    for record in preview_history[-5:]:
        if record.status not in ("aborted", "revised"):
            continue
        intent = ""
        if isinstance(record.plan, dict):
            intent = str(record.plan.get("intent") or "").strip()
        label = intent or record.id
        reason = (record.user_decision_reason or record.execution_error or "").strip()
        if record.status == "aborted":
            detail = reason or "user aborted"
            lines.append(f"- Aborted preview {label}: {detail}")
        else:
            detail = reason or "revised"
            lines.append(f"- Revised preview {label}: {detail}")
    return lines


def build_memory_context_block(state: AgentState) -> str:
    """Render compact session memory for injection after the system prompt."""
    parts: list[str] = []
    summary = (state.applied_plans_summary or "").strip()
    if summary:
        parts.append(f"{_APPLIED_PLANS_HEADER}\n{summary}")
    preview_lines = _preview_lineage_lines(state.preview_history)
    if preview_lines:
        parts.append(f"{_PREVIEW_LINEAGE_HEADER}\n" + "\n".join(preview_lines))
    return "\n\n".join(parts)


def append_memory_to_system_prompt(base_system: str, state: AgentState) -> str:
    """Append memory block to system instructions with a blank-line separator."""
    block = build_memory_context_block(state)
    if not block:
        return base_system
    return f"{base_system.rstrip()}\n\n{block}"
