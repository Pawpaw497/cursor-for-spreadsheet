# Troubleshooting

Known issues and common developer pitfalls. For setup see [getting-started.md](./getting-started.md); for trace IDs and audit logs see [logging-and-debug.md](./logging-and-debug.md).

---

## Open issues

| Symptom | Detail | Status |
|---------|--------|--------|
| Apply interrupted while a new request is in flight | User sends a new message without applying the previous plan; clicks Apply while the prior call is still running — frontend shows apply was aborted | Open |
| `Error: [422] structured_plan_missing: enable AGENT_PA_PLAN_JSON_FALLBACK` | PA returned no structured Plan; production path requires valid Pydantic AI `final_result`. Debug-only fallback: `AGENT_PA_PLAN_JSON_FALLBACK=1` in `server/.env` | Open |

---

## Session memory (Stage 6)

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| `GET /api/sessions/...` returns 503 | Store disabled | `SESSION_MEMORY_DB_ENABLED=1` in `server/.env`; `/api/config` → `sessionMemoryEnabled: true` |
| Hydrate never runs | Config not loaded yet | Client waits for `/api/config` before `hydrateWorkspaceMemoryFromServer` |
| PUT 409, changes not syncing | Version conflict | `sessionMeta.serverVersion` in `localStorage`; next debounced PUT retries with merged state |
| Restored chat is stale | TTL expired | `SESSION_MEMORY_TTL_DAYS` (default 7); row pruned from `session_memory` |

---

## Preview lifecycle

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| HTTP 409 `stale_preview` on Confirm | Tables changed after preview | `staleReason`: `structure` (row count / schema) vs `content` (cell values within row cap). Regenerate preview; see [agent-preview-lifecycle.md](./agent-preview-lifecycle.md) § Fingerprint |
| HTTP 429 on Revise | Revision cap | `MAX_AGENT_PREVIEW_REVISIONS = 5` in `agent_preview.py` |
| No `preview_ready` | Missing execution tables | Need `projectId` or `previewTables` on the request |
| Preview tables truncated | Row cap | `PREVIEW_TABLES_MAX_ROWS_PER_TABLE = 5000`; warning in server log |

---

## Agent SSE stream

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| `agent-stream ended without a terminal event` | Stream closed early | Network/proxy buffering; malformed SSE chunk skipped in `agentStream.ts` |
| `agent-stream finish: max_turns` | Loop cap hit | `max_turns` on `AgentState` (default from request) |
| Sync works, stream missing tools | Graph event routing | `stream_agent_events` listens for `llm_decide` / `tool_exec` `on_chain_end`; see [agent-stream-sse.md](./agent-stream-sse.md) |
| `preview_ready` but UI shows plan only | Client mapping | `mapAgentStreamEventsToResult` prefers `preview_ready` over `plan_done`; ensure `VITE_AGENT_USE_STREAM=true` if testing stream path |

---

## Agent / clarification

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| Unexpected clarification on multi-table prompt | Rule gate: step missing `table` | `clarification.py`; or model called `ask_user` — check backend `agent_clarification` log `source` |
| Clarification loop after answering | Reply not wired | Request must include `clarificationReply` + `clarificationTurnId`; see `agentProjectPlan.ts` |
| `422 empty_response` | PA turn had no plan, tools, or text | Model or upstream issue; grep `[trace=…]` in uvicorn log |
| `422 plan_validation_failed` | Plan JSON failed `Plan.model_validate` | Invalid step shape; not the same as `structured_plan_missing` |

---

## Storage / memory

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| Chat cleared after refresh | Site data cleared or wrong workspace | Key `spreadsheet-cursor:memory:v1:<workspaceKey>`; builtin sample uses `workspace:builtin:sample-xlsx` |
| Banner after backend restart | Expected | `lastServerBootId` changed; memory still in `localStorage` |
| Long thread missing early turns | Compaction (Stage 5) | Summary block `Earlier in this workspace:`; caps in [`agent-memory.md`](agent-memory.md) |

---

## LLM / network

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| `[400]` on cloud plan | Missing key | `OPENROUTER_API_KEY` in `server/.env` |
| `[502]` auth / upstream | Bad key or provider error | README § 步骤 2; `spreadsheet.services.llm` logs |
| Request hangs then aborts | Timeout | `/api/config` → `llmClientTimeoutRecommendedMs`; frontend `AbortSignal` |
| Ollama 503 locally | VPN / proxy | Direct `localhost:11434`; `OLLAMA_BASE` |

---

## Quick trace workflow

1. Browser console: `cmdk_prompt_submit` or `request_error` → copy `traceId`.
2. Backend terminal: `grep trace=<id>` or search audit SQLite `http_request_logs` / `llm_call_logs`.
3. Cross-check `X-Session-ID` and `X-Workspace-Key` (hashed server-side) on Agent calls.
