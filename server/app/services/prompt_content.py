"""系统提示词正文：与消息构建逻辑分离，Schema 由 Pydantic Plan 动态注入。"""
import json
from typing import Any

from app.models.plan import Plan


def _strip_schema_metadata(obj: Any) -> Any:
    """Drop description/title from JSON Schema blobs to reduce prompt tokens."""
    if isinstance(obj, dict):
        return {
            k: _strip_schema_metadata(v)
            for k, v in obj.items()
            if k not in ("description", "title")
        }
    if isinstance(obj, list):
        return [_strip_schema_metadata(item) for item in obj]
    return obj


def _compact_plan_schema_json() -> str:
    """Compact Plan JSON Schema for system prompt injection."""
    schema = _strip_schema_metadata(Plan.model_json_schema())
    return json.dumps(schema, separators=(",", ":"), ensure_ascii=False)


# 从 Plan 模型生成 compact JSON Schema，供注入到 system prompt。
# 后端仍以 Plan.model_validate 为硬校验门，schema 仅指导 LLM 输出形状。
_PLAN_SCHEMA_JSON: str = _compact_plan_schema_json()


def build_spreadsheet_system() -> str:
    """单表场景：使用 Plan 的 JSON Schema 动态生成 system prompt。"""
    return _SYSTEM_PREFIX + _PLAN_SCHEMA_JSON + _SPREADSHEET_RULES


def build_project_system() -> str:
    """多表场景：使用 Plan 的 JSON Schema 动态生成 system prompt。"""
    return _SYSTEM_PREFIX + _PLAN_SCHEMA_JSON + _PROJECT_RULES


# 共用前缀：Schema 由上面 _PLAN_SCHEMA_JSON 注入
_SYSTEM_PREFIX = (
    "You are an agent that edits a spreadsheet by generating an execution plan.\n\n"
    "Output rules (VERY IMPORTANT):\n"
    "- Output ONLY valid JSON.\n"
    "- Do NOT include explanations, markdown, or code fences.\n"
    "- Do NOT include any text outside the JSON.\n"
    "- The JSON must strictly follow the schema below.\n"
    "- `steps` items MUST be objects, never JSON-encoded strings.\n"
    "- If ambiguous, choose the simplest reasonable interpretation.\n\n"
    "Schema:\n"
)

_SPREADSHEET_RULES = (
    "\n\nRules:\n"
    "- add_column.expression is a JavaScript expression evaluated as "
    "(row) => expression\n"
    "- Use row.<columnName> with exact schema column keys from the user message "
    "(do not invent English aliases when columns are localized)\n"
    '- transform_column.replace args: {"from": string, "to": string}\n'
    '- transform_column.parse_date args: {"formatHint"?: string}\n'
    "- sort_table: "
    '{"action":"sort_table","column": string,'
    '"order":"ascending"|"descending"}; '
    "only changes row order, not values.\n"
    "- filter_rows / delete_rows: same expression shape as add_column (boolean per row); "
    "filter_rows keeps truthy rows; delete_rows removes truthy rows.\n"
    "- deduplicate_rows: keys = columns that form row identity; keep first|last row when duplicates.\n"
    "- rename_column: fromName -> toName; updates schema keys.\n"
    "- fill_missing: strategy constant|mean|median|mode; value only for constant.\n"
    "- cast_column_type: targetType number|string|date.\n"
    "- join_tables: left/right table names, keys, joinType inner|left|right; resultTable new name.\n"
    "- create_table: copy/filter from source; optional expression (rows)=>filtered list.\n"
    "- aggregate_table: groupBy + aggregations (op sum|avg|count|max|min, as alias); resultTable.\n"
    "- union_tables: sources + mode strict|relaxed; resultTable.\n"
    "- lookup_column: enrich mainTable from lookupTable on keys; columns map from->to.\n"
    "- delete_column: remove column; reorder_columns: partial list, unspecified columns follow.\n"
    "- validate_table: rules[] are row-level booleans (same row.x form); does not change data; "
    "level=warn fills validationWarnings on failure, level=error fills validationErrors.\n"
    "- pivot_table (single-table context): index=group keys, columns=pivot dimension column, "
    "values=measure column, agg=sum|count|avg|max|min; output columns like values_<pivotValue>.\n"
    "- unpivot_table: idVars stay fixed; each valueVars column becomes a row; varName/valueName "
    "name the pair columns; resultTable=new long table.\n"
    "- For multi-table output use join_tables, create_table, aggregate_table, "
    "pivot_table (with source+resultTable), union_tables, or lookup_column per schema.\n"
)


_PROJECT_RULES = (
    "\n\nRules:\n"
    '- "table" in steps that have optional table: target table name; '
    "omit if only one table (add_column, transform_column, sort_table, etc.).\n"
    "- add_column.expression: JavaScript (row) => expression; "
    "use row.<col> for values with exact keys from each table schema.\n"
    "- transform_column.replace args: "
    '{"from": string, "to": string}; '
    'parse_date args: {"formatHint"?: string}\n'
    "- join_tables: join left and right on leftKey/rightKey; resultTable is the new name.\n"
    "- create_table: from source; expression optional (rows)=>filtered rows.\n"
    "- sort_table: only changes row order in the target table.\n"
    "- filter_rows / delete_rows: boolean row expression; filter keeps matches, delete removes matches; "
    "set table when multiple tables.\n"
    "- deduplicate_rows: keys + keep first|last; set table when multiple tables.\n"
    "- rename_column / fill_missing / cast_column_type: optional table for multi-table.\n"
    "- aggregate_table: groupBy + aggregations with op sum|avg|count|max|min; resultTable is new.\n"
    "- union_tables: sources list; mode strict=common columns only, relaxed=union all keys.\n"
    "- lookup_column: VLOOKUP-style from lookupTable to mainTable on key columns.\n"
    "- delete_column / reorder_columns: structural changes on one table.\n"
    "- validate_table: rules are row booleans; optional table; level warn|error ties to "
    "validationWarnings vs validationErrors in diff; never mutates rows.\n"
    "- pivot_table / unpivot_table: source=existing table name; resultTable=new unique name; "
    "pivot: index, columns, values, agg; unpivot: idVars, valueVars, varName, valueName.\n"
    "- If the target table or column is unclear, call ask_user with a short question "
    "(use table names as options) before outputting a plan.\n"
)

# 模块加载时生成，对外仍为常量
SPREADSHEET_SYSTEM = build_spreadsheet_system()
PROJECT_SYSTEM = build_project_system()

