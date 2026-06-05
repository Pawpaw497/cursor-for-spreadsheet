# Client-side storage

The UI persists data in the browser. All are **plaintext** on the user’s machine; do not use on shared devices with sensitive spreadsheets.

## Workspace memory (`localStorage`) — primary chat thread

**Module**: `client/src/workspaceMemory.ts`

| Item | Value |
|------|--------|
| Key pattern | `spreadsheet-cursor:memory:v1:<workspaceKey>` |
| Scope | Per workspace (same key as technical history) |
| Lifetime | Survives refresh **and backend restart** |

Unified fields:

| Field | Purpose |
|-------|---------|
| `chatTranscript` | AI chat bubbles |
| `agentTranscript` | User/assistant turns sent as Agent `history` |
| `applyLog` | Compact record per successful Apply / commit |
| `previewHistory` | Mirror of API `previewHistory` |
| `sessionMeta.sessionId` | Stable UUID per workspace → `X-Session-ID` on Agent calls |
| `sessionMeta.lastServerBootId` | Detect backend restart (shows restore banner) |

On first load, migrates once from legacy `sessionStorage` chat keys and recent workspace history into `applyLog`.

Saves are debounced (500 ms).

## Legacy chat bubbles (`sessionStorage`) — migrated

**Module**: `client/src/backendSessionChatStorage.ts`

| Item | Value |
|------|--------|
| Key pattern | `spreadsheet-cursor:chat:<serverBootId>:<workspaceKey>` |

Used only for **one-time migration** into `workspaceMemory` when v1 memory is empty. New sessions no longer write here from `App.tsx`.

## Technical history (`localStorage`)

**Module**: `client/src/workspaceHistoryStorage.ts`

| Item | Value |
|------|--------|
| Key pattern | `spreadsheet-cursor:workspace:<workspaceKey>` |
| Payload version | `2` (migrates from legacy `1`) |
| Max entries | 30 conversations per workspace (truncated on save) |

Each stored conversation includes: `prompt`, `payload`, `plan`, `diff`, timestamps, `modelSource`, `modelId`, optional `modelTag` (e.g. `cloud-Auto`).

### Workspace keys

| Source | `workspaceKey` |
|--------|----------------|
| Built-in sample `test-data/sample.xlsx` | `workspace:builtin:sample-xlsx` (`BUILTIN_SAMPLE_WORKSPACE_KEY`) |
| User-uploaded file | `workspace:file:<sha256-hex>` from file bytes |

Same file content → same key across refreshes and backend restarts.

## Model preference (`localStorage`)

**Module**: `client/src/modelPreferenceStorage.ts`

| Item | Value |
|------|--------|
| Key | `spreadsheet-cursor:model-pref` |
| Scope | Global (one preference per browser origin) |
| Payload version | `1` |

Fields: `modelSource` (`cloud` \| `local`), `cloudModelId`, `localModelId`.

On load, after `/api/config` returns model lists, saved IDs are restored **only if** they still appear in `openRouterModels` / `ollamaModels`; otherwise the UI falls back to server `.env` defaults (`openRouterModel` / `ollamaModel`) or the first list entry.

This is separate from per-conversation `modelTag` in workspace history (which records what was used for a past run, not the current picker default).

## UI mapping

| Panel | Storage |
|-------|---------|
| AI chat (bubbles) | `workspaceMemory` (`localStorage` per workspace) |
| History (technical view) | `workspaceHistoryStorage` (`localStorage` per workspace) |
| Model picker (cloud/local + model) | `modelPreferenceStorage` (global) |
| Apply memory / Agent summary | `workspaceMemory.applyLog` → `appliedPlansSummary` on API |

## Related server concepts

- Preview history compact records travel in API bodies (`previewHistory`), not in localStorage.
- Project-backed tables use `projectId` on the server; workspace key is still used for client history partitioning.

## Server audit DB (not client memory)

The backend may persist HTTP and LLM traffic to a local SQLite file (`AUDIT_DB_*` in `server/.env`). That audit store is for **debugging and replay**, not for restoring the UI history panels above. Client memory remains browser-first; audit rows are not fed into prompts unless you explicitly add compressed memory fields (e.g. `appliedPlansSummary`) in API requests.
