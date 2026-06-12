# Technical documentation

Canonical reference for **spreadsheet-cursor-mvp**, a personal side project under continuous development. User-facing setup and demos stay in the [repository README](../README.md).

**Out of scope for agents and docs**: `docs/goals.md` (not used; do not create or cite). Milestone intent lives in [PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md). Maintainer Cursor workspace (`.cursor/`) is gitignored and not in the public tree.

## Documents

| Document | Audience | Summary |
|----------|----------|---------|
| [architecture.md](./architecture.md) | Full-stack | Components, API surface, plan execution paths, observability |
| [plan-step-types-reference.md](./plan-step-types-reference.md) | LLM / backend / frontend | Plan JSON contract: every `action`, fields, and semantics |
| [agent-preview-lifecycle.md](./agent-preview-lifecycle.md) | Agent / API | Server-side preview, confirm / abort / revise, fingerprints |
| [client-storage.md](./client-storage.md) | Frontend | Browser `sessionStorage` / `localStorage` keys and privacy |
| [PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md) | Personal planning | Milestone template: scope, backlog, acceptance criteria |
| [interview-simulation-transcript.md](./interview-simulation-transcript.md) | Interview prep | Mock AI Agent Developer screen: Q&A + mentor debrief (2026-06-10) |

## Source of truth in code

| Concern | Primary files |
|---------|----------------|
| Plan schema (backend) | `server/app/models/plan.py` |
| Plan types (frontend) | `client/src/types.ts` |
| Plan execution (browser) | `client/src/engine.ts` |
| Plan execution (server) | `server/app/services/plan_executor.py` |
| LLM prompts / step rules | `server/app/services/prompt_content.py` |
| Agent orchestration | `server/app/agent/orchestrator.py`, `pa_decision.py`, `pa_tools.py` |
| Agent preview | `server/app/services/agent_preview.py` |

## What is not here

- **Maintainer backlog**: local `.cursor/plans/` (gitignored); use [PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md) for published milestone notes.
- **Personal notes**: optional `docs/local/` (gitignored).
- **Runbooks**: dev start and test commands in [README](../README.md) § Quick start and § 开发与测试.

## When you change the codebase

When you change plan steps, preview APIs, or storage keys:

1. Update the matching doc under `docs/`.
2. If behavior is user-visible, add a short note to the root README.
3. Add or extend tests under `server/tests/` or `client/src/*.test.ts`.
