"""Regression guards for compact Plan schema embedded in system prompts."""
from __future__ import annotations

import json

import pytest

from app.models.plan import Plan
from app.services.prompt_content import (
    PROJECT_SYSTEM,
    SPREADSHEET_SYSTEM,
    _PLAN_SCHEMA_JSON,
    build_project_system,
    build_spreadsheet_system,
)

# Baselines after compact-schema rollout (2026-05). Raise only when Plan grows.
MAX_SPREADSHEET_SYSTEM_CHARS = 11_000
MAX_PROJECT_SYSTEM_CHARS = 11_000
MAX_PLAN_SCHEMA_JSON_CHARS = 9_000

# Pre-compact prompts were ~26k chars; guard meaningful token savings.
LEGACY_SPREADSHEET_BASELINE_CHARS = 26_000
MIN_REDUCTION_VS_LEGACY_BASELINE = 12_000


def test_system_prompts_under_character_baselines() -> None:
    assert len(SPREADSHEET_SYSTEM) <= MAX_SPREADSHEET_SYSTEM_CHARS
    assert len(PROJECT_SYSTEM) <= MAX_PROJECT_SYSTEM_CHARS
    assert len(_PLAN_SCHEMA_JSON) <= MAX_PLAN_SCHEMA_JSON_CHARS
    reduction = LEGACY_SPREADSHEET_BASELINE_CHARS - len(SPREADSHEET_SYSTEM)
    assert reduction >= MIN_REDUCTION_VS_LEGACY_BASELINE


def test_system_prompt_builders_match_module_constants() -> None:
    assert build_spreadsheet_system() == SPREADSHEET_SYSTEM
    assert build_project_system() == PROJECT_SYSTEM


def test_embedded_plan_schema_is_compact_valid_json() -> None:
    parsed = json.loads(_PLAN_SCHEMA_JSON)
    assert "properties" in parsed
    assert "intent" in parsed["properties"]
    assert "steps" in parsed["properties"]
    assert "\n  " not in _PLAN_SCHEMA_JSON
    assert '"description"' not in _PLAN_SCHEMA_JSON
    assert '"title"' not in _PLAN_SCHEMA_JSON


@pytest.mark.parametrize(
    "action",
    [
        "add_column",
        "transform_column",
        "join_tables",
        "validate_table",
        "pivot_table",
    ],
)
def test_embedded_plan_schema_lists_core_step_actions(action: str) -> None:
    assert action in _PLAN_SCHEMA_JSON


def test_plan_model_validate_remains_validation_gate() -> None:
    plan = Plan.model_validate(
        {
            "intent": "add total column",
            "steps": [
                {
                    "action": "add_column",
                    "name": "total",
                    "expression": "row.price * row.qty",
                }
            ],
        }
    )
    assert plan.intent == "add total column"
    assert plan.steps[0].action == "add_column"
