# Agent streaming (SSE)

`POST /api/agent-stream` exposes the same LangGraph orchestrator as sync `POST /api/agent`, but emits **step-level** Server-Sent Events while the agent runs. This is **not** token-level LLM streaming — underlying `call_llm` / Pydantic AI calls remain non-streaming.

For preview confirm / abort / revise and table fingerprints, see [agent-preview-lifecycle.md](./agent-preview-lifecycle.md).

## Request

Same JSON body as `/api/agent` (`AgentProjectPlanRequest`). Built on the client by `buildAgentProjectPlanRequestBody` in `client/src/llm.ts` and sent by `consumeAgentStream` in `client/src/agentStream.ts`.

| Header | Purpose |
|--------|---------|
| `Content-Type: application/json` | Request body |
| `X-Session-ID` | Optional; audit + optional session memory |
| `X-Workspace-Key` | Optional; hashed server-side for audit |

Response: `Content-Type: text/event-stream` — blocks of `event: …` + `data: …` (JSON).

## Event types

Emitted by `stream_agent_events` in `server/app/agent/orchestrator.py`:

| Event | When | `data` fields (high level) |
|-------|------|----------------------------|
| `tool_call` | PA chose a spreadsheet tool | `tool`, `args`, `state` |
| `tool_result` | Tool finished | `tool`, `state` |
| `plan_done` | Terminal: plan produced | `plan` (wire aliases), `state` |
| `preview_ready` | Terminal: preview lifecycle dry-run succeeded | `plan`, `preview`, `previewHistory`, `state` |
| `clarification` | Terminal: `ask_user` or rule gate | `question`, `options`, `context`, `state` |
| `finish` | Terminal: error cap or internal stop | `reason`, `state` |

`state` is `AgentState.to_dict()` — useful for debugging; the UI normally reads terminal payloads only.

### Tool pairing

Each `tool_call` must be followed by a matching `tool_result` with the same `tool` name before the next `tool_call`. Enforced in `server/tests/test_agent_stream_sse_order.py`.

### Terminal ordering

| Outcome | SSE terminal sequence |
|---------|----------------------|
| Plain plan (no preview lifecycle) | `plan_done` |
| Preview lifecycle success | `preview_ready`, then **`plan_done`** (both sent; client treats `preview_ready` as the outcome) |
| Clarification | `clarification` |
| `max_turns`, preview revision cap, orchestrator error | `finish` with `reason` |

With `previewLifecycle: true`, sync `/api/agent` returns a single JSON `kind: "preview_ready"`; SSE splits that into `preview_ready` + `plan_done` so step observers still see a plan event. Payload keys align (`plan`, `preview`, `previewHistory`) — see `server/tests/test_agent_sync_order.py`.

## Sync / SSE parity

Both paths share:

- `agent_react_step` → `pa_decision_step` (same PA + tools)
- `evaluate_output_plan_preview` for preview lifecycle dry-run and auto-revise loops
- `plan_to_wire_dict` / `preview_record_to_wire_dict` for Plan wire aliases (`from`, `as`)

| Concern | Sync | SSE |
|---------|------|-----|
| Orchestrator entry | `run_agent_orchestrated` | `stream_agent_events` (wraps compiled graph `astream_events`) |
| Plan terminal | `PlanResponse` (`plan` field, no `kind`) | `plan_done` event |
| Preview terminal | `{ kind: "preview_ready", … }` | `preview_ready` (+ `plan_done`) |
| Clarification | `{ kind: "clarification", … }` | `clarification` event |
| Failure | HTTP 422 / 400 / 502 via `_map_agent_result_to_response` | `finish` event; HTTP 200 unless route-level error |

Preview **decision** paths (`previewDecision: confirm | abort | revise`) are handled only on sync `POST /api/agent` today — not streamed.

## Frontend integration

| Module | Role |
|--------|------|
| `client/src/agentStream.ts` | Low-level SSE parser; `consumeAgentStream`, clarification history helpers |
| `client/src/agentProjectPlan.ts` | `mapAgentStreamEventsToResult` → same `AgentProjectPlanResult` as sync; `requestAgentProjectPlanViaStream` |
| `client/src/llm.ts` | Shared request body + sync `requestAgentProjectPlan` |

`mapAgentStreamEventsToResult` resolution order (first match wins, scanning from the end): `clarification` → `preview_ready` → `plan_done` → `finish` (throws with `reason`).

### Enabling SSE in the UI

Default: sync `/api/agent`. Opt in with a client env flag:

```bash
# client/.env.local (or export before npm run dev)
VITE_AGENT_USE_STREAM=true
```

`App.tsx` checks `import.meta.env.VITE_AGENT_USE_STREAM === "true"` and calls `requestAgentProjectPlanViaStream` instead of `requestAgentProjectPlan` for multi-table Agent generate.

Other client flags: `VITE_ENABLE_CONSOLE_LOG=0` to quiet dev logs — see [logging-and-debug.md](./logging-and-debug.md).

## Observability

- Stream lifecycle: `agent_stream_done` / `agent_stream_clarification` in browser console (`client/src/agentStream.ts`).
- Backend: `agent_stream start …` in `api.agent` logs; same trace ID as sync agent.
- Dev globals (browser console): `window.__spreadsheetCursorConsumeAgentStream`, `__spreadsheetCursorBuildClarificationHistoryEntry`.

## Tests

| File | Covers |
|------|--------|
| `server/tests/test_agent_stream_sse_order.py` | Event order, tool pairing, terminal exclusivity |
| `server/tests/test_agent_sync_order.py` | Sync vs SSE `preview_ready` payload parity |
| `server/tests/test_plan_wire_serialization.py` | Wire aliases in `plan_done` / `preview_ready` SSE payloads |
| `server/tests/test_agent_orchestrator_preview.py` | Preview retry / cap over SSE |
| `client/src/agentProjectPlan.test.ts` | `mapAgentStreamEventsToResult` terminal mapping |
