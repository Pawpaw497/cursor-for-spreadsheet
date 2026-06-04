# Cursor plans in this workspace

**Canonical path:** [`.cursor/plans/`](../../.cursor/plans/) at the repository root.

**Last refresh:** 2026-06-03 — 新增 PA `final_result` empty_response 修复计划；LangGraph + Pydantic AI 迁移 Phase 0–5 完成；Agent 仅 PA 路径。

**LangGraph + Pydantic AI 子计划（按顺序执行）：**

| Phase | 文件 | 父计划 `id` |
| --- | --- | --- |
| 3 | [langgraph-pa-phase-3.plan.md](langgraph-pa-phase-3.plan.md) | `pa-register-tools`, `pa-structured-plan-output` |
| 4 | [langgraph-pa-phase-4.plan.md](langgraph-pa-phase-4.plan.md) | `pa-stream-sse-mapping`, `pa-sync-api-parity` |
| 5 | [langgraph-pa-phase-5.plan.md](langgraph-pa-phase-5.plan.md) | `pa-optional-plan-routes`, `pa-deprecate-manual-decision`, `pa-docs-architecture` |

---

**Last refresh (archive note):** 2026-05-20 — 删除已全部完成的实施计划；`cloud_llm_tier3_execution` 并入 `cloud_llm_roi_fixes`；Plan Step 参考迁至 [docs/plan-step-types-reference.md](../../docs/plan-step-types-reference.md)（技术文档不进 `.cursor/plans/`）。

Selection criteria (keyword / path match for this spreadsheet AI demo):

* Filename or body mentions: `spreadsheet`, `cursor-spreadsheet`, Cmd+K, `plan.py`, `plan_executor`, AG Grid, LangGraph / agent in the `spreadsheet-cursor-mvp` tree.
* Excluded as unrelated: `open-xrd-*`, `update-project-description` (XRD).

## Merged plans (replace older duplicates)

| Canonical file | Replaced（旧稿已删除） |
| --- | --- |
| [langgraph-pydantic-ai-migration.plan.md](langgraph-pydantic-ai-migration.plan.md) | `langgraph+pydantic_ai_迁移_0c573c3e.plan.md`, `langgraph_+_pydantic_ai_迁移_8ebc8333.plan.md` |
| [docs/plan-step-types-reference.md](../../docs/plan-step-types-reference.md) | `spreadsheet-plan-step-types-reference.plan.md` 及更早的 operation-types / supported-ops 计划稿 |
| [cloud\_llm\_roi\_fixes\_c3a77a21.plan.md](cloud_llm_roi_fixes_c3a77a21.plan.md) | `cloud_llm_tier3_execution_200ee1f5.plan.md`（Tier 3 执行清单仅保留在 ROI 计划正文，不再单独维护 meta-plan） |

> **Note:** 原 `ollama-local-llm-runtime.plan.md` 等 Ollama 旧稿已移除；本地/云端 LLM 配置与排障以 [README](../../README.md) 为准。

## Pending（按优先级）

**待办真源：** 各 `.plan.md` 的 YAML frontmatter `todos`（与 [plan-explicit-todos.mdc](../../.cursor/rules/plan-explicit-todos.mdc) 一致）。

### P1 — PA final_result empty_response 修复

#### [pa-final-result-empty-response-fix.plan.md](pa-final-result-empty-response-fix.plan.md)

**YAML `todos`（`pending`）：**

| `id` | 摘要 |
| --- | --- |
| `coerce-final-result-args` | 解析 PA `final_result` 的 Plan / dict / JSON string 参数 |
| `surface-final-result-error` | 保留短错误文本，不把校验失败吞成空响应 |
| `finish-plan-validation-failed` | `final_result_error` 优先返回 `plan_validation_failed:` |
| `backend-pa-tests` | 覆盖 string args、invalid args、错误映射和真 empty_response |
| `frontend-detail-reason` | 前端优先展示 FastAPI `detail.reason` |
| `readme-empty-response-note` | README 区分 `/api/plan*` 空内容重试与 PA 错误语义 |
| `focused-verification` | 跑 PA 后端测试与客户端窄测 / 全量 Vitest |

### P2 — 云端 LLM 长期项（可选）

#### [cloud\_llm\_roi\_fixes\_c3a77a21.plan.md](cloud_llm_roi_fixes_c3a77a21.plan.md)

**YAML `todos`（`pending`）—— Tier 3：**

| `id` | 摘要 |
| --- | --- |
| `tier3-shared-client` | 进程级共享 `httpx.AsyncClient`（lifespan + limits） |
| `tier3-prompt-slim` | 压缩 system prompt / Plan schema 基线 + 回归 fixtures |
| `tier3-stream-parity` | SSE 与同步 `preview_lifecycle` 失败恢复策略对齐或文档化差异 |
| `tier3-tool-json` | 畸形 tool JSON 参数勿静默 `{}`，可观测 retry / finish |

**已完成（同文件 YAML）：** Tier 1（超时对齐、httpx/JSON 映射、OpenRouter 解析）与 Tier 2（preview 行数上限、有限重试、前端 AbortSignal 合并）。用户可见行为见 README「云端 LLM 稳定性」。

### P3 — 路线图池（不整单「完成」）

#### [spreadsheet-cursor-roadmap\_66f6c3b6.plan.md](spreadsheet-cursor-roadmap_66f6c3b6.plan.md)

合集型愿景（UX、agent-stream UI、tools/refinement、可观测性、配置文档）。应**拆成独立小 plan / issue** 再排期，勿把本文件当作闭集交付。

***

## 已从工作区移除的计划（已完成 / 已并入 README）

以下 `.plan.md` 已删除；内容已写入 [README](../../README.md) 或可由 git 历史追溯：

| 主题 | 说明 |
| --- | --- |
| `agent-step-enhancement_95f11d59` | P0–P2 Step 类型与 Prompt；见 README 与 [docs/plan-step-types-reference.md](../../docs/plan-step-types-reference.md) |
| `agent-preview-abort-loop` | `previewLifecycle`、Apply/Abort/Revise；见 README § Agent 预览生命周期 |
| `langgraph-three-subagents-migration` | LangGraph 编排已落地（`orchestrator.py`）；见 README 架构 |
| `workspace_chat_local_cache_ddb4107f` | 工作区键 + `localStorage` / `sessionStorage`；见 README § AI 面板 |
| `cloud_llm_tier3_execution_200ee1f5` | 与 ROI 计划重复，已合并 |
| `agent-message-shape-fix` | `call_llm` dict 消息 + `test_agent_message_shape.py`；见 README § Agent 多轮 tools |
| `表格内_diff_预览_151197d3` | 主表 dry-run Diff；见 README § Diff 预览 |
| `apply_后新列为空…`、`spreadsheet-mvp-interview-enhancements` 等 | 历史说明稿，无待办 |

另含 INDEX 既往表中的日志设计、导入优化、Python 环境文档等 **completed** / **cancelled** 项（均不再保留文件）。

***

## 当前目录内文件

| File | Plan name | Notes |
| --- | --- | --- |
| [pa-final-result-empty-response-fix.plan.md](pa-final-result-empty-response-fix.plan.md) | pa-final-result-empty-response-fix | **pending** ×7（PA `final_result` args + error semantics） |
| [cloud\_llm\_roi\_fixes\_c3a77a21.plan.md](cloud_llm_roi_fixes_c3a77a21.plan.md) | Cloud LLM ROI fixes | **pending** ×4（Tier 3）；Tier 1–2 **completed** |
| [spreadsheet-cursor-roadmap\_66f6c3b6.plan.md](spreadsheet-cursor-roadmap_66f6c3b6.plan.md) | spreadsheet-cursor-roadmap | **pending** ×5（P3 池） |
| [langgraph-pydantic-ai-migration.plan.md](langgraph-pydantic-ai-migration.plan.md) | LangGraph + Pydantic AI | 母计划；Phase 0–5 **completed**（plan 路由迁 PA **cancelled**） |
| [langgraph-pa-phase-3.plan.md](langgraph-pa-phase-3.plan.md) | LangGraph PA Phase 3 | typed tools + structured `Plan`（**completed**） |
| [langgraph-pa-phase-4.plan.md](langgraph-pa-phase-4.plan.md) | LangGraph PA Phase 4 | SSE + sync API parity（**completed**） |
| [langgraph-pa-phase-5.plan.md](langgraph-pa-phase-5.plan.md) | LangGraph PA Phase 5 | 清理 legacy + 文档（**completed**） |
路径说明：计划 YAML 的 `name` 为 Cursor 计划标识。本表链接相对仓库根。
