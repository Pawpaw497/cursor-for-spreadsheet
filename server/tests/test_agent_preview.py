"""Agent 预览生命周期的后端回归测试。"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.plan import ExecuteTable, Plan
from app.services.agent_preview import (
    MAX_AGENT_PREVIEW_REVISIONS,
    PREVIEW_TABLES_MAX_ROWS_PER_TABLE,
    build_preview_record,
    classify_stale_preview_reason,
    dry_run_plan_on_tables,
    execution_result_to_execute_plan_response,
    execution_tables_from_execute_tables,
    fingerprint_execution_tables,
    fingerprint_execution_tables_content_only,
    fingerprint_execution_tables_structure_only,
    merge_preview_history_mark_aborted,
    project_state_to_execution_tables,
)
from app.services.plan_executor import SchemaCol, TableData, apply_project_plan
from app.services.projects import ProjectState


@pytest.fixture()
def client() -> TestClient:
    """提供同步 HTTP 客户端。"""
    return TestClient(app)


def _simple_plan() -> Plan:
    """构造最小可用的 add_column Plan。"""
    return Plan.model_validate(
        {
            "intent": "add x",
            "steps": [
                {
                    "action": "add_column",
                    "name": "x",
                    "expression": "1",
                }
            ],
        }
    )


def test_dry_run_does_not_mutate_source_tables() -> None:
    """dry-run 不应修改传入的已提交表行或 schema。"""
    tables: dict[str, TableData] = {
        "A": TableData(
            name="A",
            rows=[{"k": 1}],
            schema=[SchemaCol(key="k", type="number")],
        )
    }
    snap = copy.deepcopy(tables["A"].rows)
    plan = _simple_plan()
    diff, _, errs = dry_run_plan_on_tables(tables, plan)
    assert not errs
    assert diff is not None
    assert tables["A"].rows == snap


def test_abort_marks_preview_and_leaves_store_unchanged() -> None:
    """abort 仅更新预览元数据，不写入项目表。"""
    state = ProjectState(
        id="testproj",
        tables={
            "A": {
                "name": "A",
                "rows": [{"k": 1}],
                "schema": [{"key": "k", "type": "number"}],
            }
        },
    )
    exec_tables = project_state_to_execution_tables(state)
    fp_before = fingerprint_execution_tables(exec_tables)
    from app.services.agent_preview import build_preview_record

    rec = build_preview_record(
        plan=_simple_plan(),
        diff={"addedColumns": ["x"], "modifiedColumns": [], "validationWarnings": [], "validationErrors": []},
        new_tables=[],
        tables_fingerprint=fp_before,
    )
    hist = merge_preview_history_mark_aborted([rec], rec.id, "user_cancel")
    assert hist[0].status == "aborted"
    fp_after = fingerprint_execution_tables(exec_tables)
    assert fp_after == fp_before


def test_confirm_diff_matches_dry_run() -> None:
    """同一 Plan 在相同表上的 dry-run diff 与 apply 结果 diff 一致。"""
    tables: dict[str, TableData] = {
        "A": TableData(
            name="A",
            rows=[{"k": 1}],
            schema=[SchemaCol(key="k", type="number")],
        )
    }
    plan = _simple_plan()
    d1, _, _ = dry_run_plan_on_tables(tables, plan)
    r2 = apply_project_plan(tables, plan)
    assert d1 == r2.diff


def test_execute_plan_response_dump_uses_schema_alias_for_wire() -> None:
    """``ExecutePlanResponse.model_dump()`` 默认嵌套 ``ExecuteTable`` 为 ``schema_``；Wire JSON 须 ``by_alias=True`` 得到 ``schema``。"""
    tables: dict[str, TableData] = {
        "A": TableData(
            name="A",
            rows=[{"k": 1}],
            schema=[SchemaCol(key="k", type="number")],
        )
    }
    plan = _simple_plan()
    result = apply_project_plan(tables, plan)
    exec_resp = execution_result_to_execute_plan_response(result)
    raw = exec_resp.model_dump()
    aliased = exec_resp.model_dump(by_alias=True)
    assert "schema_" in raw["tables"]["A"]
    assert "schema" not in raw["tables"]["A"]
    assert "schema" in aliased["tables"]["A"]
    assert "schema_" not in aliased["tables"]["A"]
    sch = aliased["tables"]["A"]["schema"]
    assert isinstance(sch, list) and len(sch) == 2
    keys = [c["key"] for c in sch]
    assert keys == ["k", "x"]


def test_revision_cap_constant() -> None:
    """修订上限为固定常量，供路由与编排共享。"""
    assert MAX_AGENT_PREVIEW_REVISIONS == 5


def test_execution_tables_truncates_preview_rows() -> None:
    """``previewTables`` 超大行数在入口截断到常量上限。"""
    n = PREVIEW_TABLES_MAX_ROWS_PER_TABLE + 50
    rows = [{"k": i} for i in range(n)]
    out = execution_tables_from_execute_tables(
        [
            ExecuteTable(
                name="S",
                rows=rows,
                schema=[{"key": "k", "type": "number"}],
            )
        ]
    )
    assert len(out["S"].rows) == PREVIEW_TABLES_MAX_ROWS_PER_TABLE


def test_agent_endpoint_without_preview_flag_returns_plan_shape(client: TestClient) -> None:
    """未开启 previewLifecycle 时仍返回 ``{plan: ...}`` 形状（兼容旧客户端）。"""
    body = {
        "prompt": "Return a trivial plan with one add_column step on default table",
        "tables": [
            {
                "name": "Sheet1",
                "schema": [{"key": "a", "type": "string"}],
                "sampleRows": [{"a": "x"}],
            }
        ],
        "history": [],
        "previewLifecycle": False,
    }
    resp = client.post("/api/agent", json=body)
    if resp.status_code != 200:
        pytest.skip("LLM unavailable in CI: " + resp.text[:200])
    data = resp.json()
    assert "plan" in data
    assert data["plan"]["steps"]


def _table_a(*, rows: list[dict[str, int]]) -> TableData:
    return TableData(
        name="A",
        rows=rows,
        schema=[SchemaCol(key="k", type="number")],
    )


def test_fingerprint_differs_when_cell_value_changes() -> None:
    """相同 schema/行数、不同单元格值 → 不同指纹。"""
    t1 = {"A": _table_a(rows=[{"k": 1}])}
    t2 = {"A": _table_a(rows=[{"k": 2}])}
    assert fingerprint_execution_tables_structure_only(t1) == fingerprint_execution_tables_structure_only(t2)
    assert fingerprint_execution_tables(t1) != fingerprint_execution_tables(t2)


def test_fingerprint_differs_when_structure_changes() -> None:
    """增行或改 schema → 结构指纹与全量指纹均变化。"""
    base = {"A": _table_a(rows=[{"k": 1}])}
    more_rows = {"A": _table_a(rows=[{"k": 1}, {"k": 2}])}
    new_schema = {
        "A": TableData(
            name="A",
            rows=[{"k": 1}],
            schema=[SchemaCol(key="k", type="number"), SchemaCol(key="x", type="string")],
        )
    }
    fp_base = fingerprint_execution_tables(base)
    assert fingerprint_execution_tables(more_rows) != fp_base
    assert fingerprint_execution_tables(new_schema) != fp_base
    assert fingerprint_execution_tables_structure_only(more_rows) != fingerprint_execution_tables_structure_only(base)
    assert fingerprint_execution_tables_structure_only(new_schema) != fingerprint_execution_tables_structure_only(base)


def test_fingerprint_content_bounded_by_row_cap() -> None:
    """超过行上限的尾部行不参与内容指纹；上限内修改仍会改变内容指纹。"""
    rows_in_cap = [{"k": i} for i in range(PREVIEW_TABLES_MAX_ROWS_PER_TABLE)]
    rows_beyond_cap = rows_in_cap + [{"k": 999_999}]
    rows_tail_changed = rows_in_cap + [{"k": 888_888}]
    rows_in_cap_changed = [{"k": i} for i in range(PREVIEW_TABLES_MAX_ROWS_PER_TABLE - 1)] + [{"k": 42}]
    same_row_count_tail_changed = rows_in_cap[:-1] + [{"k": 999_999}]

    schema = [SchemaCol(key="k", type="number")]
    t_cap = {"S": TableData(name="S", rows=rows_in_cap, schema=schema)}
    t_beyond = {"S": TableData(name="S", rows=rows_beyond_cap, schema=schema)}
    t_tail = {"S": TableData(name="S", rows=rows_tail_changed, schema=schema)}
    t_in_cap = {"S": TableData(name="S", rows=rows_in_cap_changed, schema=schema)}
    t_same_count_tail = {
        "S": TableData(name="S", rows=same_row_count_tail_changed, schema=schema),
    }

    assert fingerprint_execution_tables_content_only(t_cap) == fingerprint_execution_tables_content_only(t_beyond)
    assert fingerprint_execution_tables_content_only(t_cap) == fingerprint_execution_tables_content_only(t_tail)
    assert fingerprint_execution_tables_content_only(t_cap) != fingerprint_execution_tables_content_only(t_in_cap)
    assert fingerprint_execution_tables_content_only(t_cap) != fingerprint_execution_tables_content_only(t_same_count_tail)
    assert fingerprint_execution_tables_structure_only(t_beyond) != fingerprint_execution_tables_structure_only(t_cap)


def test_classify_stale_preview_reason_content_vs_structure() -> None:
    """复合指纹可区分仅内容变化与结构变化。"""
    original = {"A": _table_a(rows=[{"k": 1}])}
    content_changed = {"A": _table_a(rows=[{"k": 9}])}
    structure_changed = {"A": _table_a(rows=[{"k": 1}, {"k": 2}])}
    expected = fingerprint_execution_tables(original)
    assert classify_stale_preview_reason(expected, content_changed) == "content"
    assert classify_stale_preview_reason(expected, structure_changed) == "structure"


def test_confirm_returns_409_stale_preview_on_structure_change(client: TestClient) -> None:
    """confirm 路径在结构变化时返回 409 stale_preview 且 staleReason=structure（无 LLM）。"""
    preview_tables = [_table_a(rows=[{"k": 1}])]
    exec_tables = {"A": preview_tables[0]}
    fp_at_preview = fingerprint_execution_tables(exec_tables)
    rec = build_preview_record(
        plan=_simple_plan(),
        diff={"addedColumns": ["x"], "modifiedColumns": [], "validationWarnings": [], "validationErrors": []},
        new_tables=[],
        tables_fingerprint=fp_at_preview,
    )
    body = {
        "prompt": "confirm",
        "tables": [{"name": "A", "schema": [{"key": "k", "type": "number"}], "sampleRows": [{"k": 1}, {"k": 2}]}],
        "history": [],
        "previewLifecycle": True,
        "previewDecision": "confirm",
        "previewId": rec.id,
        "previewHistory": [
            {
                "id": rec.id,
                "plan": rec.plan,
                "diff": rec.diff,
                "newTables": rec.new_tables,
                "status": rec.status,
                "tables_fingerprint_at_preview": fp_at_preview,
                "created_at": rec.created_at,
            }
        ],
        "commitPlan": _simple_plan().model_dump(),
        "previewTables": [
            {
                "name": "A",
                "rows": [{"k": 1}, {"k": 2}],
                "schema": [{"key": "k", "type": "number"}],
            }
        ],
    }
    resp = client.post("/api/agent", json=body)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "stale_preview"
    assert detail["staleReason"] == "structure"


def test_confirm_returns_409_stale_preview_on_content_change(client: TestClient) -> None:
    """confirm 路径在内容变化时返回 409 stale_preview（无 LLM）。"""
    preview_tables = [_table_a(rows=[{"k": 1}])]
    exec_tables = {"A": preview_tables[0]}
    fp_at_preview = fingerprint_execution_tables(exec_tables)
    rec = build_preview_record(
        plan=_simple_plan(),
        diff={"addedColumns": ["x"], "modifiedColumns": [], "validationWarnings": [], "validationErrors": []},
        new_tables=[],
        tables_fingerprint=fp_at_preview,
    )
    body = {
        "prompt": "confirm",
        "tables": [{"name": "A", "schema": [{"key": "k", "type": "number"}], "sampleRows": [{"k": 2}]}],
        "history": [],
        "previewLifecycle": True,
        "previewDecision": "confirm",
        "previewId": rec.id,
        "previewHistory": [
            {
                "id": rec.id,
                "plan": rec.plan,
                "diff": rec.diff,
                "newTables": rec.new_tables,
                "status": rec.status,
                "tables_fingerprint_at_preview": fp_at_preview,
                "created_at": rec.created_at,
            }
        ],
        "commitPlan": _simple_plan().model_dump(),
        "previewTables": [
            {
                "name": "A",
                "rows": [{"k": 2}],
                "schema": [{"key": "k", "type": "number"}],
            }
        ],
    }
    resp = client.post("/api/agent", json=body)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "stale_preview"
    assert detail["staleReason"] == "content"


def test_agent_user_revise_cap_returns_degraded_preview_ready(client: TestClient) -> None:
    """User revise at cap returns preview_ready with warnings instead of HTTP 429."""
    preview_tables = [_table_a(rows=[{"k": 1}])]
    exec_tables = {"A": preview_tables[0]}
    fp_at_preview = fingerprint_execution_tables(exec_tables)
    rec = build_preview_record(
        plan=_simple_plan(),
        diff={
            "addedColumns": ["x"],
            "modifiedColumns": [],
            "validationWarnings": [],
            "validationErrors": [],
        },
        new_tables=[],
        tables_fingerprint=fp_at_preview,
    )
    body = {
        "prompt": "revise",
        "tables": [
            {
                "name": "A",
                "schema": [{"key": "k", "type": "number"}],
                "sampleRows": [{"k": 1}],
            }
        ],
        "history": [],
        "previewLifecycle": True,
        "previewDecision": "revise",
        "previewId": rec.id,
        "revisionCount": MAX_AGENT_PREVIEW_REVISIONS,
        "revisionMessage": "try again",
        "previewHistory": [
            {
                "id": rec.id,
                "plan": rec.plan,
                "diff": rec.diff,
                "newTables": rec.new_tables,
                "status": rec.status,
                "tables_fingerprint_at_preview": fp_at_preview,
                "created_at": rec.created_at,
            }
        ],
        "previewTables": [
            {
                "name": "A",
                "rows": [{"k": 1}],
                "schema": [{"key": "k", "type": "number"}],
            }
        ],
    }
    resp = client.post("/api/agent", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "preview_ready"
    assert data["preview"]["id"] == rec.id
    assert data.get("warnings")


def test_agent_user_revise_cap_without_pending_returns_429(client: TestClient) -> None:
    """User revise at cap with no pending preview still returns 429."""
    body = {
        "prompt": "revise",
        "tables": [
            {
                "name": "A",
                "schema": [{"key": "k", "type": "number"}],
                "sampleRows": [{"k": 1}],
            }
        ],
        "history": [],
        "previewLifecycle": True,
        "previewDecision": "revise",
        "previewId": "preview_missing",
        "revisionCount": MAX_AGENT_PREVIEW_REVISIONS,
        "revisionMessage": "try again",
        "previewHistory": [],
        "previewTables": [
            {
                "name": "A",
                "rows": [{"k": 1}],
                "schema": [{"key": "k", "type": "number"}],
            }
        ],
    }
    resp = client.post("/api/agent", json=body)
    assert resp.status_code == 429
    assert resp.json()["detail"]["reason"] == "preview_revision_cap"


def test_agent_endpoint_accepts_preview_lifecycle_payload(client: TestClient) -> None:
    """开启 previewLifecycle 时请求体可被解析；若 LLM 不可用则跳过。"""
    body = {
        "prompt": "noop",
        "tables": [
            {
                "name": "Sheet1",
                "schema": [{"key": "a", "type": "string"}],
                "sampleRows": [{"a": "x"}],
            }
        ],
        "history": [],
        "previewLifecycle": True,
        "previewTables": [
            {
                "name": "Sheet1",
                "rows": [{"a": "y"}],
                "schema": [{"key": "a", "type": "string"}],
            }
        ],
    }
    resp = client.post("/api/agent", json=body)
    if resp.status_code == 422:
        pytest.skip("LLM error: " + resp.text[:200])
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("kind") in ("preview_ready", None) or "plan" in data
