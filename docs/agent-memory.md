# Agent memory contract

This document defines how **workspace memory** is stored, injected into LLM prompts, and kept separate from **audit logs** and **LangGraph checkpoints**. Implementation is staged; see the [memory blueprint](../.cursor/plans/cursor-like_memory_blueprint_7f844b73.plan.md) for the full roadmap.

Browser storage details live in [`docs/client-storage.md`](client-storage.md).

---

## Schemas

### WorkspaceMemory (client, durable)

Keyed by `workspaceKey` (see [`workspaceHistoryStorage.ts`](../client/src/workspaceHistoryStorage.ts)). Target unified module: `client/src/workspaceMemory.ts` (Stage 2).

| Field | Purpose |
|-------|---------|
| `chatTranscript` | UI chat bubbles (`ChatMessage[]`) |
| `agentTranscript` | Backend-facing turns: user/assistant + optional tool summary refs |
| `applyLog` | Compact record per successful Apply / Agent commit |
| `previewHistory` | Mirror of API `previewHistory` (preview lineage) |
| `sessionMeta` | `{ sessionId, lastServerBootId, schemaFingerprint }` |

**Apply log entry** (Stage 3 shape, conceptual):

- `prompt`, plan `intent`, step type list, diff columns, ISO timestamp, `modelTag`

### AgentSessionMemory (server, optional Stage 6)

Same logical fields as `WorkspaceMemory`, keyed by client-generated `sessionId` (not plaintext `workspaceKey` on the wire). Stored in SQLite `session_memory` table when Stage 6 lands.

---

## Prompt injection order

Each Agent / plan request assembles LLM input in this order:

1. **System** — spreadsheet rules (`SpreadsheetPrompt` / `ProjectPrompt`)
2. **Memory block** — `appliedPlansSummary` (+ later: last N apply-log lines, pinned notes)
3. **Selection / context user snippet** — active table, grid selection, focused column, optional workspace rules (Stage 4)
4. **Table context user message** — schema + sample rows for current prompt
5. **Transcript** — prior user/assistant (and tool) turns from `state.messages` / `history`
6. **Current prompt** — user's latest natural-language request

Backend helpers: `build_memory_context_block()` in `server/app/agent/memory_context.py`; `assemble_agent_context()` in `server/app/agent/context_assembler.py`. Wired into PA `system_instructions_for_state`, `initial_state_from_agent_project_request`, and legacy `_build_messages_dict_from_state`.

---

## Audit vs Memory vs Checkpoint

| System | Stores | Used by | In prompt? |
|--------|--------|---------|------------|
| **Memory** (this doc, Stages 0–7) | Compressed session / workspace state | User continuity, model context | **Yes** |
| **Audit** ([SQLite audit plan concept](../.cursor/plans/sqlite_请求审计日志_d28e8248.plan.md)) | Raw HTTP + LLM request/response/errors | Dev debug, replay | **No** |
| **Checkpoint** (Stage 6+ optional) | LangGraph graph runtime state | Server resume / interrupt | **Indirect** |

### Rules

1. **Memory is product SSOT** — browser-first `WorkspaceMemory`; optional server backup in Stage 6.
2. **Audit is observability only** — never auto-injected into prompts; does not drive UI history or compaction input.
3. **Checkpoint is orchestrator infra** — same SQLite file as audit in the target design, **different tables**; not a substitute for `appliedPlansSummary` or apply log.

Target DB layout (Stage 6):

```
server/data/audit.sqlite3
├── http_request_logs / llm_call_logs   ← Audit
├── session_memory                      ← AgentSessionMemory
└── langgraph checkpoints               ← optional SqliteSaver
```

---

## `/api/chat-history` (Cursor IDE only)

`GET /api/chat-history` reads **Cursor IDE** agent transcripts from the developer machine (`agent-transcripts/`), not spreadsheet Agent chat.

- Implemented in `server/app/api/routes/chat.py` → `load_chat_history`.
- **Not** used by `App.tsx` for product memory.
- Do not confuse with workspace chat in [`backendSessionChatStorage.ts`](../client/src/backendSessionChatStorage.ts) or future `WorkspaceMemory`.

When server session APIs exist (Stage 6), this route may be deprecated or renamed; until then treat it as dev/Cursor-IDE tooling only.

---

## Stage 1 (shipped in Week A)

- Client maintains rolling `appliedPlansSummary` (last ~3 applies) and sends it on every `/api/agent` request.
- Server injects it into the system prompt via `build_memory_context_block`.
- Field mapping: request `appliedPlansSummary` → `AgentState.applied_plans_summary`.

Later stages add compaction and optional server sync — without changing the injection-order contract above.

## Stage 2–3 (shipped in Week B)

- **`workspaceMemory.ts`**: unified `localStorage` thread keyed by `workspaceKey` (not `serverBootId`); migrates legacy session chat + history apply records.
- Chat + Agent `history` survive uvicorn restart; banner when `lastServerBootId` changes.
- **`applyLog`**: structured entries on Apply/commit; rolling `appliedPlansSummary` built deterministically from log.
- Cmd+K context strip: active table, grid selection hint, last apply summary.
- Agent requests send `X-Session-ID` (`sessionMeta.sessionId`).
- Server memory block includes preview lineage for aborted/revised previews.

## Stage 4 (context assembler)

- **`context_assembler.py`**: `assemble_agent_context(state)` returns an `AgentContextPackage` with tables, selection, workspace rules, memory block, and transcript summary.
- **Request field** `context` on `AgentProjectPlanRequest`: optional `activeTable`, `selectedRange`, `focusedColumn`, `workspaceRules`.
- **Client**: AI panel workspace rules textarea persisted to `localStorage` key `spreadsheet-cursor:rules:<workspaceKey>`; grid selection/focus sent on each Agent call via `buildAgentRequestContext`.
- **Injection**: selection + rules render as a dedicated user snippet **before** the table-context user message on the current turn.
