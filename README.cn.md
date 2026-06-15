# Cursor for Spreadsheet — MVP

> 中文版 README · English: [README.md](README.md)

> **TL;DR** — 在浏览器表格里按 **Cmd+K**，用自然语言描述要改什么；**LangGraph Agent 多轮工具调用**（`get_schema` / `get_sample_rows` / `validate_expression`）→ 意图不明时触发澄清轮次 → 结构化 JSON Plan → 前端 **Diff 预览**（列高亮）→ **Apply** 写回并可 **撤销**。支持单表与多表（join / lookup 等）及 SSE 流式响应。个人开源项目，不作生产可用性承诺。

> **为什么不直接输出 CSV？** — 结构化 Plan 让每一步可 dry-run、可预览、可撤销；Agent 意图不明时主动触发 Clarification 澄清而非猜测——`Structured Plan + Agent clarification + interpretable Diff + undo` vs `opaque chat-to-CSV`。

![工作流：Cmd+K → Plan → Diff → Apply](docs/assets/demo-flow.svg)

## 项目声明与许可

- **性质**：个人开源项目，非商业产品，不承诺生产可用性与长期维护。
- **二次开发**：欢迎 fork、学习与在此基础上继续开发；使用时须**保留署名并注明来源**（见 [`LICENSE`](LICENSE)）。
- **许可**：采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)——允许非商业使用、修改与再分发；**禁止商业使用**（含直接或间接营利、企业内部生产环境商用等），商业合作须另行取得作者书面许可。
- **安全提示**：Demo 用途；`add_column` 表达式在浏览器内执行（`new Function`），对话与表格上下文可能以明文存于本机；**请勿上传敏感数据或在共享设备上使用**。

## 项目概述

- **Cmd+K 工作流**：自然语言 + 表 schema / 样本行 → LLM 生成 JSON 计划 → 表格内 Diff 预览 → Apply / 撤销。
- **单表**（`/api/plan`）与**多表项目**（`/api/plan-project`）：列/行变换、join、lookup、聚合等；前后端共享 Plan 契约。
- **Agent 模式**（实验性）：`/api/agent`、`/api/agent-stream` — 多轮工具调用，歧义时可先澄清再出 Plan。
- **技术栈**：React 18 + Vite + AG Grid；FastAPI + uv；**LangGraph · Pydantic AI**；OpenRouter / 本地 Ollama 双后端；SQLite 请求与 LLM 调用审计。
- **阶段目标**：[`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md)；功能详解见 [`docs/features.md`](docs/features.md)；技术索引 [`docs/README.md`](docs/README.md)；英文主 README [`README.md`](README.md)。

## 快速开始

**完整步骤**（OpenRouter、`.env` 全表、首次 Cmd+K）：[`docs/getting-started.md`](docs/getting-started.md)

### 推荐：Ollama（零 API Key）

1. **环境**：Python 3.10+、[uv](https://docs.astral.sh/uv/)、Node.js 18+、已安装 [Ollama](https://ollama.ai)。

```bash
git clone https://github.com/Pawpaw497/cursor-for-spreadsheet-mvp.git
cd cursor-for-spreadsheet-mvp
```

2. **本地模型**（保持 `ollama serve` 终端不关）：

```bash
ollama serve
ollama pull qwen2.5:7b
```

3. **后端**（`server/.venv` 仅由 `uv sync` 创建，勿用仓库根目录其他 venv）：

```bash
cd server
cp .env.example .env   # OPENROUTER_API_KEY 可留空；AUTO_START_OLLAMA=1 可尝试自动起 Ollama
uv sync
uv run uvicorn main:app --reload --port 8787
```

4. **前端**（新终端）：

```bash
cd client
npm install
npm run dev
```

5. 打开 **http://localhost:5173**，加载示例表后 **Cmd+K** → 选 **本地** / `qwen2.5:7b` → 输入指令（如 `在销售订单表新增金额列 = 数量 * 单价`）→ **Generate Plan** → **Apply**。示例提示词见 [`test-data/test-prompts.md`](test-data/test-prompts.md)。

### 可选：OpenRouter 云端

在 `server/.env` 填入 `OPENROUTER_API_KEY`；前端切换「云端」与模型下拉。详见 [`docs/getting-started.md`](docs/getting-started.md) Path B。

### 一键启动（可选）

```bash
make dev    # 后台起 API(8787) + Vite(5173)；结束请手动停进程
```

---

## 开发与测试

```bash
make test           # 后端 pytest + 前端 Vitest
make test-server    # cd server && uv sync && uv run pytest -q
make test-client    # cd client && npm ci && npm test
```

或分目录执行（与 CI 一致）：

```bash
cd server && uv sync && uv run pytest -q
cd client && npm ci && npm test
```

可选云端 E2E（需 Key，CI 不跑）：`RUN_CLOUD_LLM_E2E=1 uv run pytest tests/test_cloud_llm_sample_e2e.py -m integration -q`（在 `server/` 下）。

日志与 SQLite 审计：[`docs/logging-and-debug.md`](docs/logging-and-debug.md)

---

## 更多文档

| 类型 | 位置 |
|------|------|
| 许可与二次开发 | 本 README § 项目声明与许可、[`LICENSE`](LICENSE)、[`CONTRIBUTING.md`](CONTRIBUTING.md) |
| 完整环境与首次体验 | [`docs/getting-started.md`](docs/getting-started.md) |
| 功能详解（Agent 澄清、预览生命周期等） | [`docs/features.md`](docs/features.md) |
| 中文 README | [`README.cn.md`](README.cn.md) |
| 英文主 README | [`README.md`](README.md) |
| 技术参考（英文） | [`docs/README.md`](docs/README.md) |
| 里程碑 / 需求单 | [`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md) |
| 开发与测试 | 本 README § 开发与测试、根目录 [`Makefile`](Makefile) |
| 工作流示意图 | [`docs/assets/demo-flow.svg`](docs/assets/demo-flow.svg) |
| Cursor AI 可见范围 | [`.cursorignore`](.cursorignore)、[`.cursorindexingignore`](.cursorindexingignore) |
| 本地私人笔记（不提交） | `docs/local/`（见 [`.gitignore`](.gitignore)） |

`docs/` 下 canonical 文档随仓库分发；`scripts/`、`docs/local/`、**`.cursor/`** 默认不提交（见 [`.gitignore`](.gitignore)）。**`.cursor/`** 为维护者本机 Cursor 工作区（rules / plans / skills），公开 clone **不包含**；路人可忽略，公开路线图以 [`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md) 为准。
