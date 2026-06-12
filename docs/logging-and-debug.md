# Logging & debug

Structured logging on both tiers; use `traceId` / `X-Request-ID` to correlate browser console with uvicorn stdout.

## Identifiers

| Field | Location | Meaning |
|-------|----------|---------|
| `sessionId` | Frontend `[APP]` logs | Browser tab id (independent of `serverBootId`). |
| `serverBootId` | `/health`, `/api/config`, chat bubbles | One id per uvicorn/FastAPI process start. |
| `traceId` / `X-Request-ID` | Request header + logs | Per HTTP request; shared by `cmdk_prompt_submit`, `plan_apply_click`, etc. |

## Frontend (browser DevTools → Console)

- Prefix **`[APP]`**; fields include `level`, `event`, `sessionId`, `ts`.
- Common events: `app_open`, `cmdk_open`, `cmdk_prompt_submit`, `request_start` / `request_success` / `request_error`, `plan_response`, `diff_preview_shown`, `plan_apply_click`, `plan_apply_success` / `plan_apply_error`.
- Dev builds log `info` by default; set `VITE_ENABLE_CONSOLE_LOG=0` to quiet non-errors.

## Backend (uvicorn terminal)

- **`LOG_LEVEL`** (default `INFO`); `DEBUG` enables per-step `plan_executor` logs.
- Each line includes **`[trace=<id>]`** from `X-Request-ID`.
- **`LOG_FULL_TRACEBACK`**: full stack on uncaught errors unless set to `0` / `false`.
- Key loggers: `spreadsheet.http`, `spreadsheet.api.*`, `spreadsheet.services.llm`, `spreadsheet.agent.*`.

## SQLite request audit (default on)

**`AUDIT_DB_ENABLED`** (default `1`) writes HTTP and upstream LLM calls to **`data/audit.sqlite3`** under `server/`. Separate from browser `localStorage` / `sessionStorage`; audit data is **not** injected into Agent prompts.

Optional **`SESSION_MEMORY_DB_ENABLED=1`** reuses the same SQLite file for compressed workspace session backup — see [agent-memory.md](./agent-memory.md).

- Tables **`http_request_logs`** / **`llm_call_logs`** join on **`trace_id`**.
- **`AUDIT_MAX_BODY_CHARS`** (default `50000`) truncates bodies; large import/export and SSE routes log metadata only.
- Optional headers: `X-Session-ID`, `X-Model-Tag`; `X-Workspace-Key` stored as SHA-256 hash only.
- **Privacy:** may contain prompts and table samples; `server/data/` is gitignored.

## Optional LLM NDJSON debug

Set **`LLM_DEBUG_LOG_DIR`** (e.g. `logs/llm-debug`) in `server/.env` to append one JSON line per upstream LLM call:

`logs/llm-debug/2026-05-18/<trace_id>.jsonl`

- Same `trace_id` as audit DB and frontend header when audit is enabled.
- **`LLM_DEBUG_MAX_CHARS`** (default `50000`) caps message text.
- Unset `LLM_DEBUG_LOG_DIR` to disable. `logs/` is gitignored.

## Typical triage

1. Find **`traceId`** in the browser console (`cmdk_prompt_submit` or `request_error`).
2. Grep the backend terminal for the same id.
3. Follow: request start → LLM / plan → request end.
