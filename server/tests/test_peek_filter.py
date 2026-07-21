"""peek_filter DSL parser (Stage 6) — independent of data store."""
from __future__ import annotations

import pytest

from app.services.peek_filter import compile_filter_expr


def _cols(*names: str) -> set[str]:
    return set(names)


def test_numeric_eq_and_gt() -> None:
    pred, err = compile_filter_expr("amount > 100", _cols("amount"))
    assert err is None
    assert pred is not None
    assert pred({"amount": 101}) is True
    assert pred({"amount": 100}) is False
    assert pred({"amount": "150"}) is True


def test_string_eq_quoted() -> None:
    pred, err = compile_filter_expr('status == "ok"', _cols("status"))
    assert err is None
    assert pred({"status": "ok"}) is True
    assert pred({"status": "bad"}) is False


def test_contains_string_only() -> None:
    pred, err = compile_filter_expr('note contains "foo"', _cols("note"))
    assert err is None
    assert pred({"note": "hello foo"}) is True
    assert pred({"note": ""}) is False
    assert pred({"note": None}) is False
    assert pred({"note": 123}) is False


def test_and_binds_tighter_than_or() -> None:
    pred, err = compile_filter_expr(
        "a == 1 or b == 2 and c == 3",
        _cols("a", "b", "c"),
    )
    assert err is None
    assert pred({"a": 1, "b": 0, "c": 0}) is True
    assert pred({"a": 0, "b": 2, "c": 3}) is True
    assert pred({"a": 0, "b": 2, "c": 0}) is False


def test_left_associative_and() -> None:
    pred, err = compile_filter_expr(
        "x > 0 and x < 10 and x != 5",
        _cols("x"),
    )
    assert err is None
    assert pred({"x": 3}) is True
    assert pred({"x": 5}) is False
    assert pred({"x": 11}) is False


def test_quoted_column_name() -> None:
    pred, err = compile_filter_expr('"单价" >= 10', _cols("单价"))
    assert err is None
    assert pred({"单价": 10}) is True


def test_unknown_column_error() -> None:
    _, err = compile_filter_expr("missing == 1", _cols("a"))
    assert err is not None
    assert "missing" in err.lower() or "column" in err.lower()


def test_malformed_expression_error() -> None:
    _, err = compile_filter_expr("a >", _cols("a"))
    assert err is not None


def test_neq_op() -> None:
    pred, err = compile_filter_expr("a != 0", _cols("a"))
    assert err is None
    assert pred({"a": 1}) is True
    assert pred({"a": 0}) is False
