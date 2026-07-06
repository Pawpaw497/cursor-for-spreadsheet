# 功能亮点（当前能力）

> **维护约定**：行为变更时同步更新本文档、根目录 `README.md` 与对应 `docs/*.md` 技术页。Agent 记忆契约见 [`agent-memory.md`](agent-memory.md)。

---

## 产品形态

- **Cmd+K 式表格编辑**：自然语言 + 当前表上下文 → 结构化执行计划 → Diff 预览 → 一键 Apply。
- 支持**单表**与**多表/项目**（join、create_table、lookup 等）。

---

## 已实现能力

### 交互与计划

- **单表计划**（`/api/plan`）：列级与行级步骤与 [`plan-step-types-reference.md`](plan-step-types-reference.md) 一致；`add_column` 表达式支持 `row => body` 形式，Apply 前后端统一 strip。
- **多表计划**（`/api/plan-project`）：`join_tables`、`create_table`、`aggregate_table`、`union_tables`、`lookup_column` 等。
- **Agent 模式**（`/api/agent`、`/api/agent-stream`）：Pydantic AI + LangGraph 多轮工具调用；可返回 `plan`、`clarification`、`preview_ready` 或错误。
- **Diff 预览 + Apply + 撤销**：主表 dry-run 高亮；Apply 前快照，工具栏撤销恢复最近一次 Apply 前状态。

### 对话、记忆与存储

- **AI 对话气泡**：持久化在 `workspaceMemory.chatTranscript`（`localStorage`，按 `workspaceKey`）。**跨页面刷新与后端重启均可恢复**；后端重启时显示恢复横幅（`lastServerBootId` 变化）。
- **Agent 多轮记忆**：`agentTranscript`、`applyLog` → 滚动 `appliedPlansSummary`；每次 Agent 请求携带 `history` 与 `X-Session-ID`。
- **技术历史（History 标签）**：`workspaceHistoryStorage` 记录 payload / plan / diff（最多 30 条/工作区）。
- **工作区 rules**：`workspaceRulesStorage` 文本域，经 `context.workspaceRules` 注入 Agent。
- **可选服务端会话备份（Stage 6）**：`SESSION_MEMORY_DB_ENABLED=1` 时多 tab 同步与 TTL 内从 SQLite 恢复；见 [`agent-memory.md`](agent-memory.md)。
- **长对话压缩（Stage 5）**：客户端 `memoryCompaction.ts` 与服务端 `memory_compaction.py` middle-out 裁剪。

### Agent 澄清（clarification）

两条路径，前端均展示为 `kind: "clarification"`：

| 路径 | 触发 | 模块 |
|------|------|------|
| **LLM 主动** | PA 调用 `ask_user` 工具（意图不明时） | `pa_tools.py`, `pa_decision.py` |
| **规则拦截** | Plan 产出后多表步骤缺 `table` 等 | `clarification.py` → `maybe_need_clarification` |

- 续跑：`clarificationReply` + `clarificationTurnId`；Q/A 写入 `agentTranscript`（`[Clarification]` 格式）。
- 选区感知：当 `context.activeTable` / `focusedColumn` 已消歧时，规则路径可跳过澄清。
- SSE：`clarification` 终端事件；可选 `VITE_AGENT_USE_STREAM=true` 走 `/api/agent-stream`（事件契约见 [agent-stream-sse.md](./agent-stream-sse.md)）。
- 遥测：后端 `agent_clarification` / `clarification_resolved` 日志；前端 `logInfo` 同名事件。

### Agent 预览生命周期

多表 Generate Plan 可设 `previewLifecycle: true`：服务端 dry-run → `preview_ready` → confirm / abort / revise。详见 [`agent-preview-lifecycle.md`](agent-preview-lifecycle.md)。

### 后端与可观测性

- FastAPI：`/api/plan*`、`/api/agent*`、`/api/sessions/{id}`（可选）、`/api/config`、`/health`。
- SQLite 审计（默认开）：`http_request_logs` / `llm_call_logs`；与记忆表分离，不注入 prompt。
- 工具集：`get_schema`、`get_sample_rows`、`get_column_stats`、`validate_expression` 等。

### 数据加载

- `/api/load-sample` 有限重试 + 短超时；`/api/import-file` 前端约 20s 超时与明确状态文案。

---

## 安全与正确性（Demo）

- `add_column` 经 `new Function` 在浏览器执行，**不适合生产**。
- Agent 空回复 / Plan 校验失败映射为稳定 HTTP 错误（`422` / `502`）；见 `server/tests/test_agent_message_shape.py`。

## 非目标（当前范围）

- 协同编辑、完整公式引擎、多表血缘图、外部数据源连接。
