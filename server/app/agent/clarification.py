"""Deterministic clarification gates after Plan validation."""
from __future__ import annotations

from typing import Any

from app.agent.actions import AskClarificationAction, ClarificationPayload
from app.agent.state import AgentState
from app.models.plan import AgentRequestContext, Plan

_WRITE_ACTIONS = frozenset({"add_column", "transform_column"})
_COLUMN_REF_FIELDS: dict[str, str] = {
    "transform_column": "column",
    "fill_missing": "column",
    "cast_column_type": "column",
    "sort_table": "column",
    "rename_column": "fromName",
    "delete_column": "column",
}


def _table_names(state: AgentState) -> list[str]:
    return [t.name for t in state.tables]


def _request_context(state: AgentState) -> AgentRequestContext | Any | None:
    return state.request_context


def _context_target_table(state: AgentState) -> str | None:
    ctx = _request_context(state)
    if ctx is None:
        return None
    if isinstance(ctx, AgentRequestContext):
        return ctx.activeTable
    active = getattr(ctx, "activeTable", None)
    if isinstance(active, str) and active.strip():
        return active.strip()
    if isinstance(ctx, dict):
        raw = ctx.get("activeTable")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _context_target_column(state: AgentState) -> str | None:
    ctx = _request_context(state)
    if ctx is None:
        return None
    if isinstance(ctx, AgentRequestContext):
        return ctx.focusedColumn
    focused = getattr(ctx, "focusedColumn", None)
    if isinstance(focused, str) and focused.strip():
        return focused.strip()
    if isinstance(ctx, dict):
        raw = ctx.get("focusedColumn")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _context_selected_col_ids(state: AgentState) -> list[str]:
    ctx = _request_context(state)
    if ctx is None:
        return []
    selected = (
        ctx.selectedRange
        if isinstance(ctx, AgentRequestContext)
        else getattr(ctx, "selectedRange", None)
    )
    if selected is None and isinstance(ctx, dict):
        selected = ctx.get("selectedRange")
    if selected is None:
        return []
    col_ids = (
        selected.colIds
        if hasattr(selected, "colIds")
        else selected.get("colIds") if isinstance(selected, dict) else None
    )
    if not col_ids:
        return []
    return [str(c) for c in col_ids]


def _context_disambiguates_column_step(state: AgentState, col: str) -> bool:
    """Selection context resolves an ambiguous column ref for one plan step."""
    active_table = _context_target_table(state)
    if not active_table:
        return False

    col_key = str(col)
    hosts = _column_to_tables(state).get(col_key, [])
    if active_table in hosts:
        return True

    focused = _context_target_column(state)
    if focused == col_key:
        return True

    selected_cols = _context_selected_col_ids(state)
    return len(selected_cols) == 1 and selected_cols[0] == col_key


def _column_to_tables(state: AgentState) -> dict[str, list[str]]:
    """Map schema column key -> table names that define that column."""
    mapping: dict[str, list[str]] = {}
    for table in state.tables:
        for col in table.schema:
            key = col.get("key") or col.get("name")
            if not key:
                continue
            mapping.setdefault(str(key), []).append(table.name)
    return mapping


def _clarify_missing_table_on_write_steps(
    state: AgentState,
    plan: Plan,
) -> AskClarificationAction | None:
    """Multi-table: ask when add_column/transform_column steps omit ``table``."""
    table_names = _table_names(state)
    if len(table_names) <= 1:
        return None
    if _context_target_table(state):
        return None

    ambiguous_steps: list[str] = []
    for idx, step in enumerate(plan.steps):
        action = getattr(step, "action", None)
        table = getattr(step, "table", None)
        if action in _WRITE_ACTIONS and not table:
            desc = f"#{idx}: {action}"
            col = getattr(step, "column", None) or getattr(step, "name", None)
            if col:
                desc += f" on {col}"
            ambiguous_steps.append(desc)

    if not ambiguous_steps:
        return None

    question = (
        "Multiple tables detected, but some steps do not specify which table "
        "to apply to. Which table should these steps target?"
    )
    context = (
        "Ambiguous steps:\n- " + "\n- ".join(ambiguous_steps)
        + "\nAvailable tables: " + ", ".join(table_names)
    )
    return AskClarificationAction(
        payload=ClarificationPayload(
            question=question,
            options=table_names,
            context=context,
        )
    )


def _clarify_ambiguous_column_ref(
    state: AgentState,
    plan: Plan,
) -> AskClarificationAction | None:
    """Multi-table: column name exists in 2+ tables but step omits ``table``."""
    table_names = _table_names(state)
    if len(table_names) <= 1:
        return None

    col_map = _column_to_tables(state)
    ambiguous_steps: list[str] = []
    option_tables: set[str] = set()

    for idx, step in enumerate(plan.steps):
        action = getattr(step, "action", None)
        if action in _WRITE_ACTIONS:
            continue
        if getattr(step, "table", None):
            continue
        field = _COLUMN_REF_FIELDS.get(action or "")
        if not field:
            continue
        col = getattr(step, field, None)
        if not col:
            continue
        hosts = col_map.get(str(col), [])
        if len(hosts) < 2:
            continue
        if _context_disambiguates_column_step(state, str(col)):
            continue
        ambiguous_steps.append(f"#{idx}: {action} on column {col}")
        option_tables.update(hosts)

    if not ambiguous_steps:
        return None

    question = (
        "Some steps reference column names that exist in multiple tables without "
        "specifying which table to use. Which table should these steps target?"
    )
    context = (
        "Ambiguous steps:\n- " + "\n- ".join(ambiguous_steps)
        + "\nAvailable tables: " + ", ".join(table_names)
    )
    options = sorted(option_tables) if option_tables else table_names
    return AskClarificationAction(
        payload=ClarificationPayload(
            question=question,
            options=options,
            context=context,
        )
    )


def maybe_need_clarification(
    state: AgentState,
    plan: Plan,
) -> AskClarificationAction | None:
    """Run clarification rules in priority order; first match wins."""
    missing_table = _clarify_missing_table_on_write_steps(state, plan)
    if missing_table is not None:
        return missing_table
    return _clarify_ambiguous_column_ref(state, plan)
