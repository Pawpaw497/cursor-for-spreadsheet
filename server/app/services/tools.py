"""Agent 可调用的工具：读表、样本、列统计、校验表达式。"""
from __future__ import annotations

import inspect
import json
from typing import Any, Dict, List, Optional

from app.agent.state import TableContext
from app.logging_config import get_logger
from app.models.table_models import ColumnProfile, DataContext
from app.services.plan_executor import _safe_globals

log = get_logger("services.tools")

# 工具名与实现函数的注册表；(tables, **kwargs) -> str
_TOOL_IMPLS: Dict[str, Any] = {}


def _register(name: str):
    def deco(f):
        _TOOL_IMPLS[name] = f
        return f
    return deco


@_register("get_schema")
def get_schema(
    tables: List[TableContext],
    table_name: str | None = None,
) -> str:
    """
    返回指定表或全部表的 schema（列名与类型）。
    table_name 为空时：单表返回该表 schema，多表返回所有表的 schema。
    """
    if table_name:
        t = next((x for x in tables if x.name == table_name), None)
        if not t:
            return json.dumps({"error": f"Table not found: {table_name!r}"})
        return json.dumps(t.schema, ensure_ascii=False, indent=2)
    if len(tables) == 1:
        return json.dumps(tables[0].schema, ensure_ascii=False, indent=2)
    out = {t.name: t.schema for t in tables}
    return json.dumps(out, ensure_ascii=False, indent=2)


def _column_profile_to_wire_stats(cp: ColumnProfile) -> Dict[str, Any]:
    """ColumnProfile → 现有工具 wire shape ``{count, distinct, min?, max?}``。

    注意：大表 profile（profile_sampled）的 distinct/极值可能基于采样子集，
    与 fallback 的全量精确扫描在超大表上可能有差异 — SSOT 上以 profile 口径为准。
    """
    result: Dict[str, Any] = {"count": cp.count, "distinct": cp.distinct_count}
    if cp.inferred_type == "numeric":
        for key, raw in (("min", cp.min_val), ("max", cp.max_val)):
            if raw is None:
                continue
            try:
                num = float(raw)
            except ValueError:
                continue
            result[key] = int(num) if num.is_integer() else num
    return result


def _find_column_profile(
    data_context: Optional[DataContext], table_name: str, column: str
) -> Optional[ColumnProfile]:
    if data_context is None:
        return None
    tp = next(
        (x for x in data_context.tables if x.table_name == table_name), None
    )
    if tp is None:
        return None
    return next((c for c in tp.columns if c.name == column), None)


@_register("get_column_stats")
def get_column_stats(
    tables: List[TableContext],
    table_name: str,
    column: str,
    data_context: Optional[DataContext] = None,
) -> str:
    """
    列统计（SSOT）：优先读 state.data_context 的 ColumnProfile；
    未命中时 fallback 到 store 全量行扫描。
    """
    from app.services.data_store import TableNotFoundError, get_data_store

    cp = _find_column_profile(data_context, table_name, column)
    if cp is not None:
        return json.dumps(_column_profile_to_wire_stats(cp), ensure_ascii=False)

    t = next((x for x in tables if x.name == table_name), None)
    if not t:
        return json.dumps({"error": f"Table not found: {table_name!r}"})
    if not t.table_id:
        return json.dumps({"count": 0, "distinct": 0})
    try:
        rows = get_data_store().read_table(t.table_id).rows
    except TableNotFoundError:
        return json.dumps({"error": "Table data not found"})
    values = [r.get(column) for r in rows if r.get(column) is not None]
    count = len(values)
    distinct = len(set(str(v) for v in values))
    result: Dict[str, Any] = {"count": count, "distinct": distinct}
    try:
        comparable = [v for v in values if isinstance(v, (int, float))]
        if comparable:
            result["min"] = min(comparable)
            result["max"] = max(comparable)
    except TypeError:
        pass
    return json.dumps(result, ensure_ascii=False, indent=2)


@_register("validate_expression")
def validate_expression(
    tables: List[TableContext],
    expression: str,
    table_name: str | None = None,
) -> str:
    """
    用 store 首行在浏览器同构的 (row) => expr 下校验表达式是否可执行。
    返回 ok 或错误信息。
    """
    from app.services.data_store import TableNotFoundError, get_data_store

    t = tables[0] if not table_name else next(
        (x for x in tables if x.name == table_name), None
    )
    if not t:
        return json.dumps({"ok": False, "error": f"Table not found: {table_name!r}"})
    if not t.table_id:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"No tableRef for table {t.name!r}; "
                    "upload rows before agent request"
                ),
            }
        )
    try:
        rows = get_data_store().read_rows(t.table_id, 0, 1)
    except TableNotFoundError:
        return json.dumps(
            {"ok": False, "error": f"Table not found in store: {t.table_id}"}
        )
    if not rows:
        return json.dumps({"ok": False, "error": "No sample row"})
    row = rows[0]
    try:
        # 与前端 engine 一致： (row) => expression
        fn = eval(f"lambda row: ({expression})", _safe_globals(), {})
        fn(row)
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


MAX_PEEK_ROWS = 200


@_register("peek_range")
def peek_range(
    tables: List[TableContext],
    table_name: str,
    start_row: int = 0,
    end_row: int = 10,
    columns: list[str] | None = None,
    filter_expr: str | None = None,
) -> str:
    """
    Read a bounded slice of rows from the store (0-based half-open [start, end)).
    filter_expr applies only within the read window, not the whole table.
    """
    from app.services.data_store import TableNotFoundError, get_data_store
    from app.services.peek_filter import apply_filter, schema_column_names

    t = next((x for x in tables if x.name == table_name), None)
    if not t:
        return json.dumps({"error": f"Table not found: {table_name!r}"})
    if not t.table_id:
        return json.dumps(
            {
                "error": (
                    f"No tableRef for table {t.name!r}; "
                    "upload rows before agent request"
                ),
            }
        )

    try:
        row_count = get_data_store().get_row_count(t.table_id)
    except TableNotFoundError:
        return json.dumps(
            {"error": f"Table not found in store: {t.table_id}"}
        )

    start = max(0, start_row)
    truncated = end_row > start + MAX_PEEK_ROWS
    end_eff = min(end_row, start + MAX_PEEK_ROWS, row_count)

    if start >= end_eff:
        rows: list[dict[str, Any]] = []
    else:
        rows = get_data_store().read_rows(t.table_id, start, end_eff)

    col_names = schema_column_names(t.schema)
    allowed = set(col_names)

    if columns is not None:
        unknown = [c for c in columns if c not in allowed]
        if unknown:
            return json.dumps(
                {"error": f"Unknown column(s): {', '.join(unknown)!r}"}
            )

    if filter_expr:
        rows, ferr = apply_filter(rows, filter_expr, allowed)
        if ferr:
            return json.dumps({"error": ferr})

    if columns is not None:
        rows = [{k: r.get(k) for k in columns} for r in rows]

    return json.dumps(
        {
            "rows": rows,
            "truncated": truncated,
            "row_count": row_count,
        },
        ensure_ascii=False,
    )


@_register("execute_step")
def execute_step(
    tables: List[TableContext],
    step: Dict[str, Any],
    table_name: str | None = None,
) -> str:
    """
    分步执行（demo 版）：目前仅返回 echo 信息，实际执行仍在前端 engine 中完成。
    主要用于让 Agent 在需要时显式调用“执行一步”这一语义。
    """
    return json.dumps(
        {
            "ok": True,
            "note": (
                "execute_step is a server-side stub; actual data mutation "
                "still happens in the frontend engine."
            ),
            "step": step,
            "table": table_name,
        },
        ensure_ascii=False,
        indent=2,
    )


@_register("rollback_last_step")
def rollback_last_step(
    tables: List[TableContext],
) -> str:
    """
    回滚上一步（demo 版）：当前表格状态仍完全由前端维护，这里只提供语义占位。
    """
    return json.dumps(
        {
            "ok": True,
            "note": (
                "rollback_last_step is a semantic hook for future server-side "
                "state; current demo rollback is handled in the frontend."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def run_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    tables: List[TableContext],
    *,
    data_context: Optional[DataContext] = None,
) -> str:
    """执行指定工具，返回 JSON 字符串结果。工具不存在或参数错误时返回错误 JSON。

    条件注入契约（validate-expression-region-aware.plan.md 复用，勿移除）：
    仅当工具实现声明了 ``data_context`` 形参时才注入，其余工具签名不变。
    """
    arg_keys = sorted(tool_args.keys()) if tool_args else []
    log.info(
        "run_tool start name=%s arg_keys=%s tables=%d",
        tool_name,
        arg_keys,
        len(tables),
    )
    if tool_name not in _TOOL_IMPLS:
        log.warning("run_tool unknown_tool name=%s", tool_name)
        return json.dumps({"error": f"Unknown tool: {tool_name!r}"})
    impl = _TOOL_IMPLS[tool_name]
    kwargs = dict(tool_args) if tool_args else {}
    if "data_context" in inspect.signature(impl).parameters:
        kwargs["data_context"] = data_context
    try:
        out = impl(tables, **kwargs)
        log.info(
            "run_tool done name=%s result_len=%d",
            tool_name,
            len(out) if out else 0,
        )
        return out
    except TypeError as e:
        log.warning("run_tool invalid_arguments name=%s err=%s", tool_name, e)
        return json.dumps({"error": f"Invalid arguments: {e}"})
    except Exception as e:
        log.exception("run_tool error name=%s err=%s", tool_name, e)
        return json.dumps({"error": str(e)})


def get_tools_spec_for_llm() -> List[Dict[str, Any]]:
    """返回供 OpenRouter/Ollama 使用的 tools 定义（OpenAI 兼容格式）。"""
    from app.agent.pa_tools import build_openai_tools_spec

    return build_openai_tools_spec()
