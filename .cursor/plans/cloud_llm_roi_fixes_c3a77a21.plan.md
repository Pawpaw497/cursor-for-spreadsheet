---
name: Cloud LLM ROI fixes
overview: 按「投入/收益」分三级，优先低成本对齐超时与错误边界、加固解析与载荷，再考虑重试与连接复用，最后处理 prompt 体积与流式行为一致性等结构性工作。
todos:
  - id: tier1-timeouts
    content: Align client TIMEOUT_LLM_MS with server LLM timeouts (+ buffer or config-driven)
    status: completed
  - id: tier1-httpx-map
    content: Map httpx/JSON decode failures to stable HTTP errors in llm layer or plan/agent routes
    status: completed
  - id: tier1-openrouter-parse
    content: Harden call_openrouter choice/message/content parsing + tests
    status: completed
  - id: tier2-preview-cap
    content: Cap or sample previewTables client+server with documented limits
    status: completed
  - id: tier2-retry
    content: Add bounded retry with backoff for 429/503/transient httpx errors in llm.py
    status: completed
  - id: tier2-abort-signal
    content: Merge external AbortSignal into fetchWithTimeout in client/src/llm.ts
    status: completed
  - id: tier3-shared-client
    content: "Optional: introduce a shared LLM httpx AsyncClient via FastAPI lifespan with limits, explicit ownership, and concurrency verification"
    status: completed
  - id: tier3-prompt-slim
    content: "Optional: reduce embedded Plan schema and prompt baseline, then protect Plan output quality with regression fixtures"
    status: completed
  - id: tier3-stream-parity
    content: "Optional: decide and implement SSE preview failure parity with sync orchestrator, or document the intentional contract difference"
    status: completed
  - id: tier3-tool-json
    content: "Optional: replace silent {} fallback for malformed tool JSON args with observable retry or explicit finish error behavior"
    status: completed
isProject: false
---

# Cloud LLM 稳定性改进（投入/收益分级）

> **索引：** 本文件 YAML `todos` 为验收清单；原独立的 `cloud_llm_tier3_execution` meta-plan 已删除并并入下文 Tier 3 章节。Tier 1–3 均已实现，用户可见说明见 [README.md](../../README.md)。

依据先前审计与当前代码核对：后端 OpenRouter 在 [server/app/services/llm.py](server/app/services/llm.py) 使用 `httpx.AsyncClient(timeout=60)`（普通 chat）与 `90`（tools）；前端 [client/src/llm.ts](client/src/llm.ts) 使用 `TIMEOUT_LLM_MS = 180000`。路由层 [server/app/api/routes/plan.py](server/app/api/routes/plan.py) 仅将 `ValueError`/`RuntimeError` 映射为 HTTP；`httpx` 传输异常会走通用路径。`call_openrouter`（约 189–205 行）仍对 `choices[0]["message"]["content"]` 硬索引，而 `call_openrouter_chat_dict` / `call_openrouter_with_tools` 已部分使用 `.get()`。

---

## Tier 1 — 低投入 / 高回报（建议先做）

**收益**：减少「长时间挂起 + 难归因错误」、降低 200 但畸形响应导致的 500、用户可见错误更一致。

- **前后端超时对齐**
  - **做法**：将 `TIMEOUT_LLM_MS` 设为「后端最大 LLM 超时 + 合理缓冲（如 10–30s）」，或从 `/api/config` 暴露后端超时供前端读取（若已有 config 端点可复用字段）。
  - **涉及**：[client/src/llm.ts](client/src/llm.ts)（常量与各 `fetchWithTimeout(..., TIMEOUT_LLM_MS)` 调用）；可选 [server/app/api/routes](server/app/api/routes) 或现有 config 响应。
  - **验收**：慢请求时前端在服务端断开前后结束，且 UI/日志能区分 Abort vs HTTP 4xx/5xx。

- **在 LLM 出口或路由层统一映射 `httpx` 与 JSON 解析失败**
  - **做法**：在 `call_llm` 族函数外层或 `plan`/`agent` 路由的 `try` 中捕获 `httpx.TimeoutException`、`httpx.RequestError`、`httpx.HTTPStatusError`（若未在 `_raise_openrouter_error` 内化）、以及对 `r.json()` 的 `json.JSONDecodeError`，转为与现有 `_http_exception_from_runtime` 类似的 **502 + 稳定 `detail` 文案**（避免裸 500）。
  - **涉及**：[server/app/services/llm.py](server/app/services/llm.py)、[server/app/api/routes/plan.py](server/app/api/routes/plan.py)、[server/app/api/routes/agent.py](server/app/api/routes/agent.py)（若 agent 路由有同类窄捕获）、[server/app/agent/decision.py](server/app/agent/decision.py) 中直接调 LLM 的路径（按需收窄或在上层统一）。
  - **验收**：人为断网/超时场景返回可预期状态码与 `detail`；可加 1–2 个单测 mock `httpx` 异常。

- **加固 `call_openrouter` 响应解析**
  - **做法**：与 `call_openrouter_chat_dict` 一致：校验 `choices` 非空、`message` 存在、`content` 类型与空串；缺失时 `RuntimeError` 或明确错误类型供路由映射。
  - **涉及**：[server/app/services/llm.py](server/app/services/llm.py) 中 `call_openrouter`。
  - **验收**：单测构造空 `choices` / 缺 `content` 的 JSON body，断言不再 KeyError。

---

## Tier 2 — 中等投入 / 中高回报

**收益**：显著降低大表与限流导致的失败率；减少重复 in-flight 请求；云侧短抖动可自愈。

- **`previewTables` 体积上限与降级**
  - **做法**：前端在序列化前限制行数或近似字节（与现有 `sampleRows` 策略对齐）；后端 [server/app/services/agent_preview.py](server/app/services/agent_preview.py) 对 `execution_tables_from_execute_tables` 再做硬上限或截断并记录 warning。
  - **涉及**：[client/src/llm.ts](client/src/llm.ts)（`previewTablesPayload`）、[server/app/services/agent_preview.py](server/app/services/agent_preview.py)。
  - **验收**：超大表请求不再触发反代 body 限制或 OOM；行为在 README 或类型注释中说明。

- **有限次重试 + 指数退避（429 / 503 / 连接错误）**
  - **做法**：在 [server/app/services/llm.py](server/app/services/llm.py) 对可重试状态与 `httpx` 连接类错误封装小循环（2–3 次），尊重 `Retry-After`；避免对 4xx（除 429）重试。
  - **验收**：单测 mock 429 后第二次成功；确保总耗时仍在客户端超时缓冲内或文档说明。

- **`fetchWithTimeout` 合并外部 `AbortSignal`**
  - **做法**：使用 `AbortSignal.any([userSignal, timeoutSignal])`（若目标浏览器矩阵允许）或等价 polyfill 模式；任一 abort 即取消 `fetch`。
  - **涉及**：[client/src/llm.ts](client/src/llm.ts) 中 `fetchWithTimeout` 及调用方传入的 `signal`。
  - **验收**：快速连续提交或路由切换时仅保留最后一次或已取消请求不再堆积（可按需配合调用方传 `signal`）。

---

## Tier 3 — 较高投入 / 长期或架构级回报

**收益**：高并发下更稳、token 基线下降、产品行为一致；开发与运维成本更高。

- **进程级共享 `httpx.AsyncClient`（连接池）**
  - **适用信号**：云模型请求并发上升、日志出现连接建立开销明显、OpenRouter/Ollama 请求在短时间内大量创建新连接，或需要统一设置连接数上限与 keep-alive 策略。
  - **当前状态**：[server/app/services/llm.py](server/app/services/llm.py) 的 `_httpx_post_json` 每次调用都在函数内新建 `httpx.AsyncClient(timeout=...)`，重试循环在同一个临时 client 内完成；[server/app/main.py](server/app/main.py) 已有 FastAPI `lifespan`，但目前只管理 Ollama 自动启动/清理。
  - **推荐设计**：先把 LLM HTTP 发送逻辑抽成可注入 client 的内部函数，例如 `_post_with_retries(client, ...)`；默认路径仍能为单测传入短生命周期 client，再在 `lifespan` 中创建共享 client 并在关闭时 `aclose()`。避免让底层 service 直接依赖全局 FastAPI `app`，优先用一个轻量 provider 或显式参数，让测试可以覆盖「共享 client」和「临时 client」两种路径。
  - **配置点**：集中定义 `httpx.Limits(max_connections=..., max_keepalive_connections=..., keepalive_expiry=...)`；保留 chat/tools/Ollama 不同 timeout；确认 `Retry-After` + 指数退避的总耗时仍与前端超时缓冲兼容。
  - **风险**：生命周期管理错误会导致 closed client 被复用；共享 client 如果 limits 过低会把排队时间转化为超时；若把 client 存成裸全局，测试隔离和多进程 worker 行为会变差。
  - **验收**：启动/关闭时日志能确认 client 创建与关闭；单测覆盖 `aclose()` 与注入 client 的请求路径；并发 smoke（例如 20–50 个 mock LLM 请求）下连接数受限、无 `RuntimeError: client has been closed`；现有重试测试仍通过。

- **压缩系统 prompt / Plan schema**
  - **适用信号**：OpenRouter 429/上下文长度错误仍频繁出现；小表请求也消耗大量 prompt tokens；新增 Plan step 类型后 system prompt 体积持续膨胀。
  - **当前状态**：[server/app/services/prompt_content.py](server/app/services/prompt_content.py) 在模块加载时把 `Plan.model_json_schema()` 以 `indent=2` 全量注入 `SPREADSHEET_SYSTEM` 与 `PROJECT_SYSTEM`，再拼接长规则文本。优点是契约完整，缺点是 token 基线固定偏高。
  - **第一阶段（低风险测量）**：增加 prompt size 日志或测试断言，记录 `SPREADSHEET_SYSTEM` / `PROJECT_SYSTEM` 字符数与近似 token 数；用现有计划生成 fixtures 固化当前输出质量，覆盖常见单表、多表、preview validation 场景。
  - **第二阶段（瘦身候选）**：将 schema 改成 compact JSON（无缩进、可去 `$defs` 中对模型帮助有限的描述字段）；或改为「allowed actions + required fields + examples」摘要，继续让后端 `Plan.model_validate` 做硬校验。优先避免一次性删除全部 schema，先比较 compact schema 的收益。
  - **第三阶段（回归门槛）**：对比同一批 prompts 的 plan validity、step selection、clarification rate、retry rate；若 compact schema 质量无明显回退，再考虑摘要式 schema。Agent tools 路径也要覆盖，因为它复用 `SpreadsheetPrompt` / `ProjectPrompt` system 内容。
  - **风险**：瘦身后模型可能更容易漏字段、错 action 名、输出解释性文本；摘要 prompt 会提高维护成本，因为 `Plan` 模型变更后需要同步手写契约。
  - **验收**：prompt 基线下降有量化结果（例如字符数或近似 token 数）；计划生成和 Agent 决策回归 fixtures 通过；畸形输出仍被 `Plan.model_validate` 拒绝并走现有错误/重试路径；README 或开发注释说明 schema 摘要与 Pydantic 校验的职责边界。

- **SSE `stream_agent_events` 与同步 `run_agent_orchestrated` 在 `preview_lifecycle` 下的失败恢复策略对齐**
  - **适用信号**：前端逐步依赖流式 Agent 作为主路径；用户在流式预览里遇到 dry-run/validation 失败时，需要与同步 API 一样自动修订，而不是直接 finish。
  - **当前状态**：[server/app/agent/orchestrator.py](server/app/agent/orchestrator.py) 的 `run_agent_orchestrated` 在 `preview_lifecycle` 下会对 dry-run 失败或 `validate_table` error 追加反馈并重新跑编排，直到 `MAX_AGENT_PREVIEW_REVISIONS`；`stream_agent_events` 遇到同类失败时直接发送 `finish`，不会自动重试，也不会产生同样的 preview revision history。
  - **产品决策**：二选一先定契约。选项 A：流式与同步完全对齐，失败时也自动修订，并通过 SSE 发出 `preview_revision`/`preview_retry` 之类的中间事件。选项 B：明确流式只做一次生成 + dry-run，失败直接 finish，UI 负责提示用户重试或切回同步路径。
  - **若选择 A 的实现步骤**：抽出共享 helper，例如 `evaluate_preview_or_revision_feedback(agent, plan, execution_tables)`，让同步和 SSE 都复用 dry-run、validation、revision cap、`preview_history` 更新逻辑；SSE 循环在可修订时追加 feedback 到 state.messages、递增 `revision_count`，再继续 `decision`；对外保持既有 `preview_ready` / `plan_done` 事件，新增事件必须向后兼容。
  - **若选择 B 的文档步骤**：在 API/README 中说明同步 endpoint 才提供自动 preview revision；SSE endpoint 的失败 `finish.reason` 是终态，不会自动修复。前端文案需要区分「生成失败」与「预览校验失败」。
  - **风险**：对齐实现会增加 SSE 状态机复杂度，可能改变事件顺序；如果同时发 `preview_ready` 和 `plan_done`，前端要确认不会重复渲染或重复应用；文档化差异虽然简单，但产品体验不一致。
  - **验收**：同一个 dry-run 失败 fixture 下，同步与 SSE 行为符合选定契约；若选择 A，测试覆盖「第一次失败、第二次成功」与「超过 revision cap」；若选择 B，测试断言 SSE finish reason 稳定，并更新用户可见文档。

- **Tool 参数 JSON 解码失败勿静默 `{}`**
  - **适用信号**：工具调用开始承载有副作用或高成本动作；日志里出现 tool args 为空但用户意图明显需要参数；模型偶发返回 malformed tool arguments。
  - **当前状态**：[server/app/agent/decision.py](server/app/agent/decision.py) 在解析 `tool_calls[0].arguments` 失败时直接 `args = {}`，随后仍返回 `CallToolAction`。这会把「模型输出格式错误」伪装成「空参数工具调用」，可能造成错误工具执行或难以排查的空结果。
  - **推荐行为**：先不要执行工具。解析失败时记录 tool name、tool_call_id、截断后的 raw arguments；如果 `current_turn + 1 < max_turns`，向 state.messages 追加一条 tool 或 user feedback，要求模型重新发出合法 JSON arguments；如果已达上限，则返回 `FinishAction(reason="invalid_tool_arguments: ...")`。
  - **实现边界**：保持 `CallToolPayload.tool_args` 只接收已验证的 dict；不要用 `{}` 作为 fallback。若后续工具 schema 更严格，可在 JSON 解析后增加 Pydantic/JSON Schema 校验，把 schema 错误走同一条 retry/finish 路径。
  - **风险**：改成 retry 会多消耗一次 LLM 调用；如果 feedback message role 选错，OpenRouter tools transcript 可能不接受。需要与 `_build_messages_dict_from_state` 支持的 `tool_calls` / `tool_call_id` 结构一致。
  - **验收**：单测构造 malformed `arguments`，断言不会调用工具且 state 可观测；测试覆盖可重试场景与 max_turns 场景；日志包含足够定位信息但不落完整敏感 payload；正常合法 tool args 行为不变。

---

## 建议实施顺序

1. 完成 **Tier 1**（超时 + 异常映射 + `call_openrouter` 解析）— 改动面集中、测试明确。  
2. 视线上数据量决定是否并行 **Tier 2** 中的 `previewTables` 上限与重试。  
3. **Tier 3** 按负载与产品优先级排期（连接池与 prompt 瘦身常可拆分独立 PR）。

## 文档与测试

- 用户可见超时/截断行为变化时更新 [README.md](README.md)。  
- 后端优先扩展现有 `server/tests/`（如 `test_agent_preview.py`、plan 相关测试）与针对 `llm.py` 的小单测；前端可为 `fetchWithTimeout` + signal 合并补 Vitest。
