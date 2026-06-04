"""Agent memory block assembly for LLM prompt injection (Stage 1)."""
from __future__ import annotations

from app.models.agent_models import AgentState

_APPLIED_PLANS_HEADER = "Applied plans in this session:"


def build_memory_context_block(state: AgentState) -> str:
    """Render compact session memory for injection after the system prompt."""
    summary = (state.applied_plans_summary or "").strip()
    if not summary:
        return ""
    return f"{_APPLIED_PLANS_HEADER}\n{summary}"


def append_memory_to_system_prompt(base_system: str, state: AgentState) -> str:
    """Append memory block to system instructions with a blank-line separator."""
    block = build_memory_context_block(state)
    if not block:
        return base_system
    return f"{base_system.rstrip()}\n\n{block}"
