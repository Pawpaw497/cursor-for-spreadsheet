# Technical documentation

Canonical reference for **spreadsheet-cursor-mvp**, a personal side project under continuous development.

## Language & audience

| Surface | Language | Audience |
| ------- | -------- | -------- |
| [Root README](../README.md) | 中文为主 | First-time users, quick start, license |
| [README.en.md](../README.en.md) | English | Short TL;DR + links to Chinese setup |
| **`docs/`** (this tree) | English | APIs, contracts, architecture, Agent internals |
| [getting-started.md](./getting-started.md) | English | Detailed setup (Ollama + OpenRouter) |
| [features.md](./features.md) | 中文 | Feature deep dive moved from README |

**Out of scope**: `docs/goals.md` (unused). Milestone intent: [PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md). `.cursor/` is gitignored (local maintainer workspace only).

## Documents

| Document | Audience | Summary |
|----------|----------|---------|
| [architecture.md](./architecture.md) | Full-stack | Components, API surface, plan execution paths, observability |
| [plan-step-types-reference.md](./plan-step-types-reference.md) | LLM / backend / frontend | Plan JSON contract: every `action`, fields, and semantics |
| [agent-preview-lifecycle.md](./agent-preview-lifecycle.md) | Agent / API | Server-side preview, confirm / abort / revise, fingerprints |
| [client-storage.md](./client-storage.md) | Frontend | Browser `sessionStorage` / `localStorage` keys and privacy |
| [PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md) | Personal planning | Open-source readiness milestone, backlog |
| [getting-started.md](./getting-started.md) | Setup | Full Quick Start beyond root README |
| [features.md](./features.md) | Users / devs | MVP features, Agent clarification, preview |
| [logging-and-debug.md](./logging-and-debug.md) | Dev / ops | Trace IDs, audit SQLite, LLM debug NDJSON |

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
- **Runbooks**: dev start and test commands in [README](../README.md) (§ 快速开始, § 开发与测试).

## When you change the codebase

When you change plan steps, preview APIs, or storage keys:

1. Update the matching doc under `docs/`.
2. If behavior is user-visible, add a short note to the root README.
3. Add or extend tests under `server/tests/` or `client/src/*.test.ts`.
