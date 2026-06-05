"""Deterministic clarification gates after Plan validation."""
from __future__ import annotations

from app.agent.actions import AskClarificationAction, ClarificationPayload
from app.agent.state import AgentState
from app.models.plan import Plan

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
