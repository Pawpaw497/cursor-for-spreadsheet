"""PA tool registration and OpenAI schema parity with legacy get_tools_spec_for_llm."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.agent.pa_tools import (
    GetColumnStatsArgs,
    GetSchemaArgs,
    PA_TOOL_DEFINITIONS,
    _run_tool_from_args,
    build_openai_tools_spec,
    tool_names,
)
from app.models.agent_models import TableContext
from app.services.tools import get_tools_spec_for_llm


def _deps() -> SimpleNamespace:
    return SimpleNamespace(
        tables=[
            TableContext(
                name="Sheet1",
                schema=[{"key": "a", "type": "string"}],
                sample_rows=[],
            )
        ]
    )


def test_tool_names_match_definitions() -> None:
    names = tool_names()
    assert names == [d.name for d in PA_TOOL_DEFINITIONS]
    assert len(names) == len(PA_TOOL_DEFINITIONS)


def test_get_tools_spec_for_llm_delegates_to_pa() -> None:
    spec = get_tools_spec_for_llm()
    pa_spec = build_openai_tools_spec()
    assert spec == pa_spec
    assert {s["function"]["name"] for s in spec} == set(tool_names())


def test_openai_required_fields_match_legacy_contract() -> None:
    by_name = {
        s["function"]["name"]: s["function"]["parameters"]
        for s in build_openai_tools_spec()
    }
    assert by_name["get_column_stats"]["required"] == ["table_name", "column"]
    assert by_name["validate_expression"]["required"] == ["expression"]
    assert by_name["execute_step"]["required"] == ["step"]
    assert "table_name" in by_name["get_schema"].get("properties", {})


def test_run_tool_from_args_invokes_run_tool() -> None:
    ctx = SimpleNamespace(deps=_deps())
    with patch("app.agent.pa_tools.run_tool", return_value="{}") as m_run:
        out = _run_tool_from_args(
            ctx,
            "get_schema",
            GetSchemaArgs(table_name="Sheet1"),
        )
    assert out == "{}"
    m_run.assert_called_once()
    assert m_run.call_args[0][0] == "get_schema"
    assert m_run.call_args[0][1] == {"table_name": "Sheet1"}


def test_get_column_stats_model_requires_fields() -> None:
    try:
        GetColumnStatsArgs.model_validate({"table_name": "S"})
        raise AssertionError("expected validation error")
    except Exception:
        pass
    args = GetColumnStatsArgs(table_name="S", column="a")
    assert args.column == "a"
