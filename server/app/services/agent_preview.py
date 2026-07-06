"""Agent 预览生命周期：在隔离表副本上 dry-run，并生成指纹用于 confirm 防陈旧。

本模块不修改 ProjectStore 或请求方传入的已提交表数据；所有执行均通过
`apply_project_plan`，其对输入表做拷贝后再变换。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Union

from app.agent.preview_telemetry import log_preview_cap_hit, log_preview_revision
from app.logging_config import get_logger
from app.models.agent_models import AgentState, PreviewRecord
from app.models.plan import AgentProjectPlanRequest, ExecuteTable, Plan, plan_to_wire_dict
from app.services.plan_executor import (
    ProjectApplyResult,
    SchemaCol,
    TableData,
    apply_project_plan,
)
from app.services.projects import ProjectState

log = get_logger("services.agent_preview")

# 与编排层约定一致：超过后优先 degraded preview_ready；无法恢复时 finish 或 429。
MAX_AGENT_PREVIEW_REVISIONS: int = 5

# ``previewTables`` 全量行硬上限（与前端 ``PREVIEW_TABLES_MAX_ROWS_PER_TABLE`` 对齐），避免反代 body 限制与内存尖峰。
PREVIEW_TABLES_MAX_ROWS_PER_TABLE: int = 5000


def new_preview_id() -> str:
    """生成用于客户端与日志关联的预览标识。

    @return: 形如 ``preview_<hex>`` 的稳定可读 id。
    """
    return f"preview_{uuid.uuid4().hex[:16]}"


def _structure_payload_for_tables(tables: Mapping[str, TableData]) -> Dict[str, Any]:
    """构造仅含表名、行数与 schema 列 key 的指纹载荷。"""
    payload: Dict[str, Any] = {}
    for name in sorted(tables.keys()):
        t = tables[name]
        payload[name] = {
            "rowCount": len(t.rows),
            "schemaKeys": [c.key for c in t.schema],
        }
    return payload


def _content_payload_for_table(t: TableData) -> List[Dict[str, Any]]:
    """对单表行做有界采样并规范化键序，供内容指纹稳定序列化。"""
    rows = t.rows[:PREVIEW_TABLES_MAX_ROWS_PER_TABLE]
    return [{k: row[k] for k in sorted(row.keys())} for row in rows]


def _content_payload_for_tables(tables: Mapping[str, TableData]) -> Dict[str, Any]:
    """构造各表有界行内容的指纹载荷。"""
    payload: Dict[str, Any] = {}
    for name in sorted(tables.keys()):
        payload[name] = _content_payload_for_table(tables[name])
    return payload


def _sha256_json_payload(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fingerprint_execution_tables_structure_only(tables: Mapping[str, TableData]) -> str:
    """仅对表结构（行数 + schema 列 key）做指纹。

    @param tables: 表名到执行引擎 ``TableData`` 的映射。
    @return: SHA256 十六进制摘要字符串。
    """
    return _sha256_json_payload(_structure_payload_for_tables(tables))


def fingerprint_execution_tables_content_only(tables: Mapping[str, TableData]) -> str:
    """对有界采样的单元格内容做指纹（每表最多 ``PREVIEW_TABLES_MAX_ROWS_PER_TABLE`` 行）。

    @param tables: 表名到执行引擎 ``TableData`` 的映射。
    @return: SHA256 十六进制摘要字符串。
    """
    return _sha256_json_payload(_content_payload_for_tables(tables))


def fingerprint_execution_tables(tables: Mapping[str, TableData]) -> str:
    """对当前已提交表做结构 + 有界内容指纹，用于 confirm 时检测预览是否过期。

    返回 ``{structure_hash}:{content_hash}``，便于在 confirm 路径区分结构陈旧与内容陈旧。

    @param tables: 表名到执行引擎 ``TableData`` 的映射。
    @return: 复合指纹字符串。
    """
    struct_fp = fingerprint_execution_tables_structure_only(tables)
    content_fp = fingerprint_execution_tables_content_only(tables)
    return f"{struct_fp}:{content_fp}"


def classify_stale_preview_reason(
    expected_fingerprint: str,
    current_tables: Mapping[str, TableData],
) -> Literal["structure", "content"]:
    """根据预期指纹与当前表推断陈旧类型（结构变化 vs 仅内容变化）。

    @param expected_fingerprint: 预览创建时写入的复合指纹。
    @param current_tables: confirm 时解析的已提交表。
    @return: ``"structure"`` 或 ``"content"``。
    """
    if ":" not in expected_fingerprint:
        return "structure"
    struct_expected = expected_fingerprint.split(":", 1)[0]
    struct_now = fingerprint_execution_tables_structure_only(current_tables)
    if struct_now != struct_expected:
        return "structure"
    return "content"


def execution_tables_from_execute_tables(rows_payload: List[ExecuteTable]) -> Dict[str, TableData]:
    """将 API 请求中的 ``ExecuteTable`` 列表转为执行引擎表字典。

    超过 ``PREVIEW_TABLES_MAX_ROWS_PER_TABLE`` 的行按表截断并打 warning（与前端序列化上限一致）。

    @param rows_payload: 每张表的全量行与 schema。
    @return: 表名到 ``TableData`` 的映射。
    @raises ValueError: 当表名为空或 schema 无法解析时抛出。
    """
    out: Dict[str, TableData] = {}
    for t in rows_payload:
        schema_cols: List[SchemaCol] = []
        for col in t.schema_:
            key = str(col.get("key", ""))
            if not key:
                continue
            col_type = str(col.get("type", "string"))
            if col_type not in ("number", "string", "date"):
                col_type = "string"
            schema_cols.append(SchemaCol(key=key, type=col_type))  # type: ignore[arg-type]
        raw_rows = list(t.rows)
        if len(raw_rows) > PREVIEW_TABLES_MAX_ROWS_PER_TABLE:
            log.warning(
                "preview_tables_truncated table=%s original_rows=%d cap=%d",
                t.name,
                len(raw_rows),
                PREVIEW_TABLES_MAX_ROWS_PER_TABLE,
            )
            raw_rows = raw_rows[:PREVIEW_TABLES_MAX_ROWS_PER_TABLE]
        out[t.name] = TableData(name=t.name, rows=raw_rows, schema=schema_cols)
    return out


def project_state_to_execution_tables(state: ProjectState) -> Dict[str, TableData]:
    """将 ``ProjectState`` 转为执行引擎使用的多表字典（深拷贝行与 schema 元数据）。

    @param state: 内存项目状态。
    @return: 表名到 ``TableData`` 的映射。
    """
    tables: Dict[str, TableData] = {}
    for name, t in state.tables.items():
        raw_schema = t.get("schema") or []
        schema_cols: List[SchemaCol] = []
        for col in raw_schema:
            key = str(col.get("key", ""))
            if not key:
                continue
            col_type = str(col.get("type", "string"))
            if col_type not in ("number", "string", "date"):
                col_type = "string"
            schema_cols.append(SchemaCol(key=key, type=col_type))  # type: ignore[arg-type]
        tables[name] = TableData(
            name=name,
            rows=list(t.get("rows") or []),
            schema=schema_cols,
        )
    return tables


def dry_run_plan_on_tables(
    tables: Mapping[str, TableData],
    plan: Plan,
) -> tuple[Optional[Dict[str, List[str]]], List[str], List[str]]:
    """在表副本上执行 Plan，返回 diff、新建表名列表及可选错误说明。

    ``apply_project_plan`` 内部已克隆输入，不会修改 ``tables`` 参数对象中的行。

    @param tables: 已提交的表数据视图（只读使用）。
    @param plan: 待验证的 Plan。
    @return: ``(diff, new_tables, errors)``；若执行链抛出异常则 ``diff`` 为 ``None``。
    """
    try:
        result = apply_project_plan(dict(tables), plan)
    except Exception as e:  # noqa: BLE001 — 预览路径需吞并记录，供修订反馈
        log.warning("dry_run_plan_on_tables failed err=%s", e)
        return None, [], [str(e)]
    return result.diff, list(result.new_tables), []


def build_preview_record(
    *,
    plan: Plan,
    diff: Dict[str, List[str]],
    new_tables: List[str],
    tables_fingerprint: str,
    execution_error: Optional[str] = None,
) -> PreviewRecord:
    """从 dry-run 结果构造 ``PreviewRecord``（pending 状态）。

    @param plan: 已校验的 Plan。
    @param diff: 与 ``ExecutePlanResponse.diff`` 对齐的四键 diff。
    @param new_tables: 新建逻辑表名列表。
    @param tables_fingerprint: 生成预览时表的指纹。
    @param execution_error: 若 dry-run 失败则写入错误摘要。
    @return: 新的 ``PreviewRecord``。
    """
    now = time.time()
    return PreviewRecord(
        id=new_preview_id(),
        plan=plan_to_wire_dict(plan),
        diff=dict(diff),
        new_tables=list(new_tables),
        status="pending",
        user_decision=None,
        user_decision_reason=None,
        execution_error=execution_error,
        tables_fingerprint_at_preview=tables_fingerprint,
        created_at=now,
        resolved_at=None,
    )


def merge_preview_history_mark_revised(
    history: List[PreviewRecord],
    preview_id: str,
) -> List[PreviewRecord]:
    """将指定预览标记为 ``revised``，其余条目原样拷贝。

    @param history: 当前历史列表。
    @param preview_id: 被用户选择修订的预览 id。
    @return: 新的历史列表（浅拷贝容器，记录为替换后的副本）。
    """
    out: List[PreviewRecord] = []
    now = time.time()
    for rec in history:
        if rec.id == preview_id and rec.status == "pending":
            out.append(
                rec.model_copy(
                    update={
                        "status": "revised",
                        "user_decision": "revise",
                        "resolved_at": now,
                    }
                )
            )
        else:
            out.append(rec)
    return out


def merge_preview_history_mark_aborted(
    history: List[PreviewRecord],
    preview_id: str,
    reason: Optional[str],
) -> List[PreviewRecord]:
    """Abort：标记预览为 ``aborted``，不修改表数据。

    @param history: 当前历史列表。
    @param preview_id: 目标预览 id。
    @param reason: 可选用户说明。
    @return: 更新后的历史列表。
    """
    out: List[PreviewRecord] = []
    now = time.time()
    for rec in history:
        if rec.id == preview_id and rec.status == "pending":
            out.append(
                rec.model_copy(
                    update={
                        "status": "aborted",
                        "user_decision": "abort",
                        "user_decision_reason": reason,
                        "resolved_at": now,
                    }
                )
            )
        else:
            out.append(rec)
    return out


def merge_preview_history_mark_committed(
    history: List[PreviewRecord],
    preview_id: str,
) -> List[PreviewRecord]:
    """Confirm 成功后把对应 ``pending`` 预览标记为 ``committed``。

    @param history: 当前历史列表。
    @param preview_id: 已提交的预览 id。
    @return: 更新后的历史列表。
    """
    out: List[PreviewRecord] = []
    now = time.time()
    for rec in history:
        if rec.id == preview_id and rec.status == "pending":
            out.append(
                rec.model_copy(
                    update={
                        "status": "committed",
                        "user_decision": "confirm",
                        "resolved_at": now,
                    }
                )
            )
        else:
            out.append(rec)
    return out


@dataclass(frozen=True)
class PreviewEvaluationReady:
    """Dry-run 成功：可返回 ``preview_ready`` 终端动作。"""

    agent: AgentState
    plan: Plan
    record: PreviewRecord
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreviewEvaluationRevise:
    """预览失败且未达修订上限：已追加反馈并递增 ``revision_count``。"""

    working_agent: AgentState


@dataclass(frozen=True)
class PreviewEvaluationCap:
    """已达 ``MAX_AGENT_PREVIEW_REVISIONS``：终止并返回稳定 finish reason。"""

    agent: AgentState
    finish_reason: str


PreviewEvaluation = Union[
    PreviewEvaluationReady,
    PreviewEvaluationRevise,
    PreviewEvaluationCap,
]


def last_pending_preview(history: List[PreviewRecord]) -> Optional[PreviewRecord]:
    """Return the most recent ``pending`` preview record, if any."""
    for rec in reversed(history):
        if rec.status == "pending":
            return rec
    return None


def _cap_warning_messages(cap_detail: str) -> tuple[str, ...]:
    return (
        f"Preview revision limit ({MAX_AGENT_PREVIEW_REVISIONS}) reached.",
        f"Last failure: {cap_detail}",
        "You may confirm this preview, abort, or rephrase your request.",
    )


def _empty_diff() -> Dict[str, List[str]]:
    return {
        "addedColumns": [],
        "modifiedColumns": [],
        "validationWarnings": [],
        "validationErrors": [],
    }


def resolve_preview_cap_degraded_ready(
    agent: AgentState,
    plan: Plan,
    execution_tables: Mapping[str, TableData],
    *,
    cap_detail: str,
    precomputed_diff: Optional[Dict[str, List[str]]] = None,
    precomputed_new_tabs: Optional[List[str]] = None,
    source: str = "auto_revise",
) -> Optional[PreviewEvaluationReady]:
    """When revision cap is hit, return degraded ``preview_ready`` if possible."""
    pending = last_pending_preview(agent.preview_history)
    warnings = _cap_warning_messages(cap_detail)

    if pending is not None:
        log_preview_cap_hit(
            revision_count=agent.revision_count,
            preview_id=pending.id,
            source=source,
        )
        return PreviewEvaluationReady(
            agent=agent.model_copy(update={"last_execution_error": cap_detail}),
            plan=Plan.model_validate(pending.plan),
            record=pending,
            warnings=warnings,
        )

    fp = fingerprint_execution_tables(execution_tables)
    diff = precomputed_diff
    new_tabs = list(precomputed_new_tabs or [])
    errs: List[str] = []
    if diff is None:
        diff, new_tabs, errs = dry_run_plan_on_tables(execution_tables, plan)

    if diff is None and not errs:
        log_preview_cap_hit(
            revision_count=agent.revision_count,
            preview_id=None,
            source=source,
        )
        return None

    record = build_preview_record(
        plan=plan,
        diff=diff or _empty_diff(),
        new_tables=new_tabs,
        tables_fingerprint=fp,
        execution_error=cap_detail,
    )
    final_agent = agent.model_copy(
        update={
            "preview_history": list(agent.preview_history) + [record],
            "last_execution_error": cap_detail,
        }
    )
    log_preview_cap_hit(
        revision_count=agent.revision_count,
        preview_id=record.id,
        source=source,
    )
    return PreviewEvaluationReady(
        agent=final_agent,
        plan=plan,
        record=record,
        warnings=warnings,
    )


def _on_cap_hit(
    agent: AgentState,
    plan: Plan,
    execution_tables: Mapping[str, TableData],
    cap_detail: str,
    *,
    precomputed_diff: Optional[Dict[str, List[str]]] = None,
    precomputed_new_tabs: Optional[List[str]] = None,
) -> PreviewEvaluation:
    degraded = resolve_preview_cap_degraded_ready(
        agent,
        plan,
        execution_tables,
        cap_detail=cap_detail,
        precomputed_diff=precomputed_diff,
        precomputed_new_tabs=precomputed_new_tabs,
    )
    if degraded is not None:
        return degraded
    return PreviewEvaluationCap(
        agent=agent.model_copy(update={"last_execution_error": cap_detail}),
        finish_reason=f"preview_revision_cap: {cap_detail}",
    )


def evaluate_output_plan_preview(
    agent: AgentState,
    plan: Plan,
    execution_tables: Mapping[str, TableData],
) -> PreviewEvaluation:
    """在已提交表快照上 dry-run Plan，并决定 preview_ready / 修订 / 修订上限。

    供 ``run_agent_orchestrated`` 与 ``stream_agent_events`` 共用，保证同步与 SSE 预览失败恢复一致。

    @param agent: 产出 ``output_plan`` 后的 Agent 状态（含 ``revision_count``）。
    @param plan: 待预览的 Plan。
    @param execution_tables: 只读表快照。
    @return: ``PreviewEvaluationReady``、``PreviewEvaluationRevise`` 或 ``PreviewEvaluationCap``。
    """
    fp = fingerprint_execution_tables(execution_tables)
    diff, new_tabs, errs = dry_run_plan_on_tables(execution_tables, plan)

    if errs:
        err_text = "; ".join(errs)
        if agent.revision_count >= MAX_AGENT_PREVIEW_REVISIONS:
            return _on_cap_hit(agent, plan, execution_tables, err_text)
        feedback = (
            "Plan execution failed during server-side preview with error(s): "
            f"{err_text}. Reply with corrected JSON plan only."
        )
        log_preview_revision(
            revision_count=agent.revision_count + 1,
            source="auto_revise",
            reason_preview=err_text,
        )
        working = agent.model_copy(
            update={
                "messages": agent.messages
                + [{"role": "user", "content": feedback}],
                "revision_count": agent.revision_count + 1,
                "last_execution_error": err_text,
            }
        )
        return PreviewEvaluationRevise(working_agent=working)

    if diff is not None and should_auto_revise_after_preview(diff, plan):
        errs_txt = "; ".join(diff.get("validationErrors") or [])
        if agent.revision_count >= MAX_AGENT_PREVIEW_REVISIONS:
            return _on_cap_hit(
                agent,
                plan,
                execution_tables,
                errs_txt,
                precomputed_diff=diff,
                precomputed_new_tabs=new_tabs,
            )
        feedback = (
            "Preview produced validationErrors with validate_table level=error: "
            f"{errs_txt}. Regenerate the plan as JSON only."
        )
        log_preview_revision(
            revision_count=agent.revision_count + 1,
            source="auto_revise",
            reason_preview=errs_txt,
        )
        working = agent.model_copy(
            update={
                "messages": agent.messages
                + [{"role": "user", "content": feedback}],
                "revision_count": agent.revision_count + 1,
                "last_execution_error": errs_txt,
            }
        )
        return PreviewEvaluationRevise(working_agent=working)

    record = build_preview_record(
        plan=plan,
        diff=diff or {},
        new_tables=new_tabs,
        tables_fingerprint=fp,
    )
    final_agent = agent.model_copy(
        update={
            "preview_history": list(agent.preview_history) + [record],
            "last_execution_error": None,
        }
    )
    return PreviewEvaluationReady(agent=final_agent, plan=plan, record=record)


def should_auto_revise_after_preview(diff: Dict[str, List[str]], plan: Plan) -> bool:
    """当存在 error 级校验失败且 Plan 含 error 级 validate 步骤时，触发自动修订。

    @param diff: dry-run 产生的 diff。
    @param plan: 当前 Plan。
    @return: 若应把校验失败反馈给 LLM 并进入下一轮则为 True。
    """
    if not diff.get("validationErrors"):
        return False
    for step in plan.steps:
        if getattr(step, "action", None) == "validate_table" and getattr(step, "level", "warn") == "error":
            return True
    return False


def execution_result_to_execute_plan_response(result: ProjectApplyResult):
    """将 ``ProjectApplyResult`` 转为 ``ExecutePlanResponse``（用于 confirm 响应体）。

    @param result: 执行引擎多表结果。
    @return: ``ExecutePlanResponse`` 实例。
    """
    from app.models.plan import ExecutePlanResponse, ExecuteTable

    out_tables: Dict[str, ExecuteTable] = {}
    for name, t in result.tables.items():
        schema_payload = [{"key": c.key, "type": c.type} for c in t.schema]
        out_tables[name] = ExecuteTable(
            name=name,
            rows=list(t.rows),
            schema=schema_payload,
        )
    return ExecutePlanResponse(
        tables=out_tables,
        diff=result.diff,
        newTables=list(result.new_tables),
    )


def resolve_execution_tables_for_agent_request(
    req: AgentProjectPlanRequest,
    *,
    project_tables: Optional[Mapping[str, TableData]],
) -> Optional[Dict[str, TableData]]:
    """根据 ``projectId`` / ``previewTables`` 解析用于 dry-run 与指纹的表集合。

    @param req: Agent 请求体。
    @param project_tables: 当 ``req.projectId`` 命中存储时由路由注入的只读快照。
    @return: 可执行表字典；若无法解析（缺少数据）则返回 ``None``。
    """
    if project_tables is not None:
        return dict(project_tables)
    if req.previewTables:
        return execution_tables_from_execute_tables(list(req.previewTables))
    return None
