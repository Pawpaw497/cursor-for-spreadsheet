# Plan step types reference

Execution plans are JSON objects:

```json
{
  "intent": "Human-readable summary of what the plan does",
  "steps": [ /* one or more step objects */ ]
}
```

- **Contract owners**: `server/app/models/plan.py` (Pydantic), `client/src/types.ts` (TypeScript).
- **Executors**: `client/src/engine.ts` (browser preview/apply), `server/app/services/plan_executor.py` (server dry-run / execute).
- **LLM rules**: injected from `Plan.model_json_schema()` plus text in `server/app/services/prompt_content.py`.

Optional `table` on single-table steps names the target when multiple tables exist; omit when only one table is in context.

Optional `note` on any step is for human/LLM commentary only; executors ignore it.

---

## Column operations

### `add_column`

Adds a derived column. Expression is JavaScript evaluated as `(row) => <expression>` with `row.<columnName>` access.

```json
{
  "action": "add_column",
  "name": "total_price",
  "expression": "row.price * row.quantity",
  "table": "Orders"
}
```

**Security (demo)**: expressions run via `new Function` in the browser; not production-safe.

### `transform_column`

In-place column transform. `transform` is one of: `trim`, `lower`, `upper`, `replace`, `parse_date`.

- `replace` args: `{ "from": string, "to": string }`
- `parse_date` args: `{ "formatHint"?: string }`

```json
{
  "action": "transform_column",
  "column": "email",
  "transform": "lower"
}
```

### `rename_column`

Renames a column key in schema and all rows.

```json
{
  "action": "rename_column",
  "fromName": "qty",
  "toName": "quantity"
}
```

### `delete_column`

Removes a column from schema and rows.

### `reorder_columns`

Reorders columns. `columns` is the desired prefix; unspecified columns keep relative order after the listed ones.

### `cast_column_type`

Casts values in a column. `targetType`: `number` | `string` | `date`.

### `fill_missing`

Fills null/empty cells. `strategy`: `constant` | `mean` | `median` | `mode`; `value` required only for `constant`.

---

## Row operations

### `sort_table`

Sorts rows by `column`. `order`: `ascending` (default) | `descending`. Does not change cell values.

### `filter_rows`

Keeps rows where the boolean expression (same shape as `add_column`) is truthy.

### `delete_rows`

Removes rows where the boolean expression is truthy.

### `deduplicate_rows`

Deduplicates by `keys` (column list). `keep`: `first` | `last` (default `first`).

---

## Multi-table operations

These steps create or combine tables. Use distinct `resultTable` / `name` values that do not collide with existing table names unless intentionally overwriting (engine-dependent).

### `join_tables`

SQL-style join.

| Field | Description |
|-------|-------------|
| `left`, `right` | Source table names |
| `leftKey`, `rightKey` | Join keys |
| `resultTable` | New table name |
| `joinType` | `inner` (default), `left`, `right` |

### `create_table`

Copies or filters from `source` into new table `name`. Optional `expression`: `(rows) => filteredRowArray` (JavaScript).

### `aggregate_table`

GROUP BY style aggregation.

```json
{
  "action": "aggregate_table",
  "source": "Orders",
  "groupBy": ["region"],
  "aggregations": [
    { "column": "amount", "op": "sum", "as": "total_amount" }
  ],
  "resultTable": "ByRegion"
}
```

`op`: `sum` | `avg` | `count` | `max` | `min`.

### `union_tables`

Stacks tables vertically. `mode`: `strict` (common columns only) | `relaxed` (default, union of all keys).

### `lookup_column`

VLOOKUP-style enrichment from `lookupTable` into `mainTable` on `mainKey` / `lookupKey`. `columns`: `[{ "from": "lookupCol", "to": "newCol" }]`.

---

## Shape / validation (no row mutation)

### `validate_table`

Evaluates `rules` (array of boolean row expressions). Does not change data.

- `level`: `warn` (default) → failures go to `diff.validationWarnings`
- `level`: `error` → failures go to `diff.validationErrors`

### `pivot_table`

Wide-to-wide pivot into `resultTable`.

| Field | Description |
|-------|-------------|
| `source` | Input table |
| `index` | Group-by column keys |
| `columns` | Column whose distinct values become new column headers |
| `values` | Measure column |
| `agg` | `sum` (default), `count`, `avg`, `max`, `min` |

Output columns are typically named like `values_<pivotValue>`.

### `unpivot_table`

Melt / unpivot to long format.

| Field | Default | Description |
|-------|---------|-------------|
| `idVars` | — | Identifier columns kept fixed |
| `valueVars` | — | Columns melted into rows |
| `varName` | `"variable"` | Name of the variable column |
| `valueName` | `"value"` | Name of the value column |
| `resultTable` | — | New long table |

---

## Diff shape (execution output)

After apply or dry-run, consumers receive a per-table diff:

```json
{
  "addedColumns": ["col_a"],
  "modifiedColumns": ["col_b"],
  "validationWarnings": ["rule message..."],
  "validationErrors": []
}
```

Frontend type: `client/src/types.ts` → `Diff`.

---

## Versioning

New step types require coordinated updates:

1. Pydantic union in `plan.py`
2. TypeScript union in `types.ts`
3. Branches in `engine.ts` and `plan_executor.py`
4. Prompt rules in `prompt_content.py`
5. This document and any LLM eval / E2E tests
