"""Regression: row bracket/attribute access in add_column expressions."""
from __future__ import annotations

from app.models.plan import Plan
from app.services.plan_executor import SchemaCol, TableData, apply_plan, apply_project_plan


def _sales_row() -> dict[str, object]:
    return {"单价": 10, "数量": 3}


def _add_total_plan(expression: str) -> Plan:
    return Plan.model_validate(
        {
            "intent": "add total_price",
            "steps": [
                {
                    "action": "add_column",
                    "name": "total_price",
                    "expression": expression,
                }
            ],
        }
    )


def test_add_column_bracket_access_chinese_keys() -> None:
    """row['单价'] * row['数量'] must not silently become None on apply."""
    rows = [_sales_row()]
    schema = [SchemaCol(key="单价", type="number"), SchemaCol(key="数量", type="number")]
    plan = _add_total_plan("row['单价'] * row['数量']")
    result = apply_plan(rows, schema, plan)
    assert result.rows[0]["total_price"] == 30


def test_add_column_attribute_access_chinese_keys() -> None:
    """row.单价 * row.数量 remains valid when keys are valid identifiers."""
    rows = [_sales_row()]
    schema = [SchemaCol(key="单价", type="number"), SchemaCol(key="数量", type="number")]
    plan = _add_total_plan("row.单价 * row.数量")
    result = apply_plan(rows, schema, plan)
    assert result.rows[0]["total_price"] == 30


def test_add_column_bracket_access_via_apply_project_plan() -> None:
    """Project apply path uses the same _eval_row_expression."""
    tables = {
        "销售订单": TableData(
            name="销售订单",
            rows=[_sales_row()],
            schema=[
                SchemaCol(key="单价", type="number"),
                SchemaCol(key="数量", type="number"),
            ],
        )
    }
    plan = Plan.model_validate(
        {
            "intent": "add total_price",
            "steps": [
                {
                    "action": "add_column",
                    "name": "total_price",
                    "table": "销售订单",
                    "expression": "row['单价'] * row['数量']",
                }
            ],
        }
    )
    result = apply_project_plan(tables, plan)
    t = result.tables["销售订单"]
    assert t.rows[0]["total_price"] == 30


def test_filter_rows_js_and_operator_keeps_matching_rows() -> None:
    """filter_rows with JS ``&&`` must not drop every row on server apply."""
    tables = {
        "销售订单": TableData(
            name="销售订单",
            rows=[
                {"订单日期": "2024-03-01", "订单号": "A"},
                {"订单日期": "2023-12-31", "订单号": "B"},
            ],
            schema=[
                SchemaCol(key="订单日期", type="string"),
                SchemaCol(key="订单号", type="string"),
            ],
        )
    }
    plan = Plan.model_validate(
        {
            "intent": "2024 only",
            "steps": [
                {
                    "action": "filter_rows",
                    "table": "销售订单",
                    "condition": (
                        "row.订单日期 >= '2024-01-01' && row.订单日期 < '2025-01-01'"
                    ),
                }
            ],
        }
    )
    result = apply_project_plan(tables, plan)
    rows = result.tables["销售订单"].rows
    assert len(rows) == 1
    assert rows[0]["订单号"] == "A"


def test_sales_clean_plan_with_js_filter_not_empty() -> None:
    """Multi-step cast + add_column + filter_rows(&&) + sort: server apply must keep 2024 rows."""
    tables = {
        "销售订单": TableData(
            name="销售订单",
            rows=[
                {
                    "订单号": "O1",
                    "客户": "A",
                    "产品": "P1",
                    "数量": "2",
                    "单价": "10",
                    "订单日期": "2024-03-01",
                },
                {
                    "订单号": "O2",
                    "客户": "B",
                    "产品": "P2",
                    "数量": "1",
                    "单价": "5",
                    "订单日期": "2023-06-01",
                },
            ],
            schema=[
                SchemaCol(key="订单号", type="string"),
                SchemaCol(key="客户", type="string"),
                SchemaCol(key="产品", type="string"),
                SchemaCol(key="数量", type="string"),
                SchemaCol(key="单价", type="string"),
                SchemaCol(key="订单日期", type="string"),
            ],
        )
    }
    plan = Plan.model_validate(
        {
            "intent": "clean sales",
            "steps": [
                {
                    "action": "cast_column_type",
                    "table": "销售订单",
                    "column": "数量",
                    "targetType": "number",
                },
                {
                    "action": "cast_column_type",
                    "table": "销售订单",
                    "column": "单价",
                    "targetType": "number",
                },
                {
                    "action": "add_column",
                    "table": "销售订单",
                    "name": "金额",
                    "expression": "row.数量 * row.单价",
                },
                {
                    "action": "filter_rows",
                    "table": "销售订单",
                    "condition": (
                        "row.订单日期 >= '2024-01-01' && row.订单日期 < '2025-01-01'"
                    ),
                },
                {
                    "action": "sort_table",
                    "table": "销售订单",
                    "column": "金额",
                    "order": "descending",
                },
            ],
        }
    )
    result = apply_project_plan(tables, plan)
    rows = result.tables["销售订单"].rows
    assert len(rows) == 1
    assert rows[0]["订单号"] == "O1"
    assert rows[0]["金额"] == 20
