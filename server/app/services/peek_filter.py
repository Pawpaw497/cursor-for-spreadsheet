"""Restricted filter DSL for peek_range (no eval)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Iterable

RowPredicate = Callable[[dict[str, Any]], bool]


class _TokKind(Enum):
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    OP = auto()
    AND = auto()
    OR = auto()
    CONTAINS = auto()
    EOF = auto()


@dataclass
class _Tok:
    kind: _TokKind
    value: str | float


class _Lexer:
    _KW = {"and": _TokKind.AND, "or": _TokKind.OR, "contains": _TokKind.CONTAINS}
    _OPS = ("==", "!=", ">=", "<=", ">", "<")

    def __init__(self, text: str) -> None:
        self._text = text.strip()
        self._i = 0
        self._cur: _Tok | None = None

    def _peek_char(self) -> str | None:
        if self._i >= len(self._text):
            return None
        return self._text[self._i]

    def _advance(self, n: int = 1) -> None:
        self._i += n

    def _skip_ws(self) -> None:
        while self._peek_char() is not None and self._peek_char() in " \t\n\r":
            self._advance()

    def _read_string(self, quote: str) -> str:
        self._advance()
        start = self._i
        while self._peek_char() is not None and self._peek_char() != quote:
            if self._peek_char() == "\\":
                self._advance(2)
                continue
            self._advance()
        if self._peek_char() != quote:
            raise ValueError("Unterminated string literal")
        s = self._text[start : self._i]
        self._advance()
        return s

    def _read_ident_unquoted(self) -> str:
        start = self._i
        while self._peek_char() is not None and (
            self._peek_char().isalnum() or self._peek_char() in "_"
        ):
            self._advance()
        return self._text[start : self._i]

    def _read_number(self) -> float:
        start = self._i
        if self._peek_char() == "-":
            self._advance()
        while self._peek_char() is not None and (
            self._peek_char().isdigit() or self._peek_char() == "."
        ):
            self._advance()
        chunk = self._text[start : self._i]
        return float(chunk)

    def next_tok(self) -> _Tok:
        self._skip_ws()
        ch = self._peek_char()
        if ch is None:
            return _Tok(_TokKind.EOF, "")

        if ch in "\"'":
            return _Tok(_TokKind.STRING, self._read_string(ch))

        if ch == "-" or ch.isdigit():
            return _Tok(_TokKind.NUMBER, self._read_number())

        for op in self._OPS:
            if self._text[self._i : self._i + len(op)] == op:
                self._advance(len(op))
                return _Tok(_TokKind.OP, op)

        ident = self._read_ident_unquoted()
        if not ident:
            raise ValueError(f"Unexpected character at position {self._i}")
        low = ident.lower()
        if low in self._KW:
            return _Tok(self._KW[low], ident)
        return _Tok(_TokKind.IDENT, ident)

    def peek(self) -> _Tok:
        if self._cur is None:
            self._cur = self.next_tok()
        return self._cur

    def consume(self) -> _Tok:
        tok = self.peek()
        self._cur = None
        return tok


def schema_column_names(schema: list[dict[str, Any]]) -> list[str]:
    """Column keys from TableContext.schema (key or name), same as profile_builder."""
    names: list[str] = []
    for c in schema:
        if not isinstance(c, dict):
            continue
        key = c.get("key") or c.get("name")
        if key:
            names.append(str(key))
    return names


def _resolve_column(token: str, allowed: set[str]) -> str | None:
    if token in allowed:
        return token
    return None


def _coerce_numeric(cell: Any) -> float | None:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    if isinstance(cell, str):
        try:
            return float(cell.strip())
        except ValueError:
            return None
    return None


def _eval_compare(col: str, op: str, literal: _Tok, row: dict[str, Any]) -> bool:
    cell = row.get(col)
    if op == "contains":
        if not isinstance(cell, str) or not cell:
            return False
        if literal.kind != _TokKind.STRING:
            return False
        return str(literal.value) in cell

    if literal.kind == _TokKind.NUMBER:
        left = _coerce_numeric(cell)
        if left is None:
            return False
        right = float(literal.value)
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        return False

    if literal.kind == _TokKind.STRING:
        if not isinstance(cell, str):
            return False
        if op == "==":
            return cell == literal.value
        if op == "!=":
            return cell != literal.value
        return False

    if literal.kind == _TokKind.IDENT:
        # bare ident as string literal fallback
        if not isinstance(cell, str):
            return False
        if op == "==":
            return cell == literal.value
        if op == "!=":
            return cell != literal.value
        return False

    return False


@dataclass
class _Parser:
    lex: _Lexer
    allowed: set[str]

    def _parse_value(self) -> _Tok:
        tok = self.lex.consume()
        if tok.kind in (_TokKind.NUMBER, _TokKind.STRING, _TokKind.IDENT):
            return tok
        raise ValueError("Expected value after operator")

    def _parse_comparison(self) -> tuple[str, str, _Tok]:
        col_tok = self.lex.consume()
        if col_tok.kind == _TokKind.STRING:
            col_name = str(col_tok.value)
        elif col_tok.kind == _TokKind.IDENT:
            col_name = str(col_tok.value)
        else:
            raise ValueError("Expected column name")

        resolved = _resolve_column(col_name, self.allowed)
        if resolved is None:
            raise ValueError(f"Unknown column: {col_name!r}")

        if self.lex.peek().kind == _TokKind.CONTAINS:
            self.lex.consume()
            op = "contains"
        else:
            op_tok = self.lex.consume()
            if op_tok.kind != _TokKind.OP:
                raise ValueError("Expected comparison operator")
            op = str(op_tok.value)

        val = self._parse_value()
        return resolved, op, val

    def _parse_and(self) -> RowPredicate:
        preds: list[RowPredicate] = []

        def one(row: dict[str, Any], c: str, o: str, v: _Tok) -> bool:
            return _eval_compare(c, o, v, row)

        col, op, val = self._parse_comparison()
        preds.append(lambda row, c=col, o=op, v=val: one(row, c, o, v))

        while self.lex.peek().kind == _TokKind.AND:
            self.lex.consume()
            col, op, val = self._parse_comparison()
            preds.append(lambda row, c=col, o=op, v=val: one(row, c, o, v))

        def combined(row: dict[str, Any]) -> bool:
            return all(p(row) for p in preds)

        return combined

    def _parse_or(self) -> RowPredicate:
        and_preds: list[RowPredicate] = [self._parse_and()]
        while self.lex.peek().kind == _TokKind.OR:
            self.lex.consume()
            and_preds.append(self._parse_and())

        def combined(row: dict[str, Any]) -> bool:
            return any(p(row) for p in and_preds)

        return combined

    def parse(self) -> RowPredicate:
        pred = self._parse_or()
        if self.lex.peek().kind != _TokKind.EOF:
            raise ValueError("Unexpected tokens after expression")
        return pred


def compile_filter_expr(
    expr: str,
    allowed_columns: Iterable[str],
) -> tuple[RowPredicate | None, str | None]:
    """Compile filter_expr to a row predicate, or return an error message."""
    allowed = set(allowed_columns)
    if not expr or not expr.strip():
        return None, "Empty filter expression"
    try:
        parser = _Parser(_Lexer(expr), allowed)
        return parser.parse(), None
    except ValueError as e:
        return None, str(e)


def apply_filter(
    rows: list[dict[str, Any]],
    expr: str,
    allowed_columns: Iterable[str],
) -> tuple[list[dict[str, Any]], str | None]:
    pred, err = compile_filter_expr(expr, allowed_columns)
    if err:
        return rows, err
    assert pred is not None
    return [r for r in rows if pred(r)], None
