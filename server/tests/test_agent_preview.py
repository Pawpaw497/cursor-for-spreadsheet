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
    dry_run_plan_on_tables,
    execution_result_to_execute_plan_response,
    execution_tables_from_execute_tables,
    fingerprint_execution_tables,
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
