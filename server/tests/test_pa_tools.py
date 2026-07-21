"""PA tool registration and OpenAI schema parity with legacy get_tools_spec_for_llm."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pydantic_ai import Agent

from app.agent.pa_tools import (
    ASK_USER_TOOL_NAME,
    GetColumnStatsArgs,
    GetSchemaArgs,
    PA_TOOL_DEFINITIONS,
    PaAgentDeps,
    _run_tool_from_args,
    build_openai_tools_spec,
    register_pa_agent_tools,
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
    assert by_name["peek_range"]["required"] == ["table_name"]
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


def test_peek_range_description_mentions_window_filter() -> None:
    spec = next(s for s in build_openai_tools_spec() if s["function"]["name"] == "peek_range")
    desc = spec["function"]["description"].lower()
    assert "data profile" in desc or "profile" in desc
    assert "row range" in desc or "requested row" in desc


def test_tool_names_exclude_get_sample_rows() -> None:
    assert "get_sample_rows" not in tool_names()


def test_register_pa_agent_tools_names_match_definitions() -> None:
    """Regression for PR #42: pydantic-ai's @agent.tool registers each tool under
    the decorated function's __name__, a source of truth independent of
    PA_TOOL_DEFINITIONS/tool_names(). A mismatch there (peek_range_tool vs
    peek_range) let a live model be told about a tool name PA's own registry
    didn't expose. ask_user is excluded: it isn't a dynamic @agent.tool call,
    it's handled via the structured final_result output path (see
    ASK_USER_TOOL_NAME usage in pa_decision.py).

    Relies on pydantic-ai's private _function_toolset — no public introspection
    API exists for this. If a pydantic-ai upgrade removes/renames it, this test
    will error rather than silently stop guarding the invariant.
    """
    agent = Agent("test", deps_type=PaAgentDeps)
    register_pa_agent_tools(agent)
    registered = set(agent._function_toolset.tools.keys())
    expected = set(tool_names()) - {ASK_USER_TOOL_NAME}
    assert registered == expected


def test_get_column_stats_model_requires_fields() -> None:
    try:
        GetColumnStatsArgs.model_validate({"table_name": "S"})
        raise AssertionError("expected validation error")
    except Exception:
        pass
    args = GetColumnStatsArgs(table_name="S", column="a")
    assert args.column == "a"
