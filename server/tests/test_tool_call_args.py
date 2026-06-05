"""Tests for LLM tool argument coercion."""
from __future__ import annotations

from app.agent.tool_call_args import coerce_tool_call_args


def test_coerce_validate_expression_json_string() -> None:
    args = coerce_tool_call_args(
        "validate_expression",
        '{"expression": "row[\'单价\'] * row[\'数量\']"}',
    )
    assert args == {"expression": "row['单价'] * row['数量']"}


def test_coerce_validate_expression_bare_expression_string() -> None:
    args = coerce_tool_call_args(
        "validate_expression",
        "row['单价'] * row['数量']",
    )
    assert args == {"expression": "row['单价'] * row['数量']"}


def test_coerce_get_schema_dict() -> None:
    args = coerce_tool_call_args("get_schema", {"table_name": "销售订单"})
    assert args == {"table_name": "销售订单"}


def test_coerce_unrecoverable_returns_none() -> None:
    assert coerce_tool_call_args("get_schema", "not-json") is None
    assert coerce_tool_call_args("validate_expression", "") is None
