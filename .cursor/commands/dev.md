# /dev — 启动全栈开发环境

用户通过 `/dev` 显式请求时执行（不要在没有 `/dev` 时自动跑完整起栈流程）。

## 目标

在 **8787**（FastAPI）和 **5173**（Vite）上启动 spreadsheet-cursor-mvp，并确认两者可用。

## 步骤

1. **检查是否已在运行**：查看 terminals 状态；若 `uvicorn`（8787）或 `npm run dev`（5173）已在跑，只报告 URL，不要重复起进程。
2. **后端一次性准备**（仅当需要时）：
   - `cd server`
   - 若无 `.env`：`cp .env.example .env`（提醒用户配置 `OPENROUTER_API_KEY` 或 Ollama）
   - `uv sync`
3. **启动 API（后台）**：在 `server/` 运行  
   `uv run uvicorn main:app --reload --port 8787`
4. **启动前端（后台）**：在 `client/` 运行  
   `npm install`（若缺 `node_modules`）→ `npm run dev`
5. **验证**：
   - `curl -sS http://127.0.0.1:8787/health` → `{"ok":true}`
   - 前端日志中的 Local URL（默认 `http://localhost:5173`）

## 约束

- 后端只用 `server/.venv`（`uv run`）；不要用仓库根 `env/`、`.venv`、`venv`。
- 两个长驻进程各用一个 terminal/后台任务。
- 完成后用简短中文汇报：两个 URL、是否新建进程、LLM 配置是否可能缺失（无 key 时 UI 仍可开，AI 功能需 `.env` 或 Ollama）。

## 参考

- 细节与排障：`.cursor/skills/run-project/SKILL.md`、`README.md`
