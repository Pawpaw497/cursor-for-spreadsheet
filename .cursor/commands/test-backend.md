# /test-backend — 后端检查

用户通过 `/test-backend` 显式请求时执行。

## 目标

在不依赖云端 LLM 的前提下，验证 FastAPI 后端可安装、可导入、测试通过；可选对已运行实例做 HTTP smoke。

## 步骤（按序执行并汇报）

1. **依赖同步**  
   `cd server && uv sync`

2. **导入 smoke**  
   `cd server && uv run python -c "from app.main import app; print('ok')"`

3. **pytest（默认全量 `tests/`）**  
   `cd server && uv run pytest -q`  
   若用户只要快速回归，可改为：  
   `uv run pytest tests/test_agent_preview.py -q`

4. **可选 HTTP smoke**（仅当 8787 上已有 uvicorn）  
   - `curl -sS http://127.0.0.1:8787/health`  
   - `curl -sS http://127.0.0.1:8787/api/config`

## 约束

- 工作目录为 `server/`；使用 `uv run` 与 `server/.venv`。
- **不要**默认跑 `RUN_CLOUD_LLM_E2E=1` 或 `integration` 标记的云端用例（需用户另请）。
- 汇报：每步 pass/fail、失败时的 stderr 摘要、pytest 统计。

## 参考

- `.cursor/skills/test-server/SKILL.md`、`README.md` § 测试
