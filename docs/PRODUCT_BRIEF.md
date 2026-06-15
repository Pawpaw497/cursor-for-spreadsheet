# Product brief & requirements

> Personal milestone sheet for **open-source readability** (2026-06). Maintainer Cursor plans live under local `.cursor/` (gitignored). **Do not use** `docs/goals.md`.

---

## 1. Document meta

| Field | Value |
| ----- | ----- |
| **Title** | Open-source readiness — first-time visitor experience |
| **Owner** | Pawpaw |
| **Status** | Active |
| **Last updated** | 2026-06-12 |
| **Related links** | PR #19 (open-source readiness), `main` |

---

## 2. Problem statement

- **Context**: The MVP is functionally rich (Plan / Agent / preview), but the root README was dense; no LICENSE/CI/demo asset; LLM setup looked like it required a cloud API key.
- **Pain**: External readers bounce before trying Cmd+K; forkers lack attribution/CI guardrails.
- **Why now**: Repo moved to public GitHub; goal is **star / try / fork** for learning, not commercial positioning.

---

## 3. Target users & scenarios

| Persona / role | Primary scenario | Out of scope for *this* iteration |
| -------------- | ---------------- | --------------------------------- |
| Casual visitor | Skim README, run Ollama path in ~15 min, one Plan → Apply | Production hardening, SaaS |
| Contributor | Fork with CC BY-NC notice, green CI on PR | Splitting all of `App.tsx` (deferred) |

---

## 4. Success criteria (measurable)

- Criterion 1: New reader sees TL;DR + workflow diagram without scrolling past one screen.
- Criterion 2: Quick Start **Ollama-first** with real `git clone` URL; full detail in `docs/getting-started.md`.
- Criterion 3: `push`/`PR` to `main` runs `uv run pytest -q` + `npm test` in GitHub Actions.
- Criterion 4: `LICENSE`, README declaration, and `CONTRIBUTING.md` agree on attribution + non-commercial use.

**Non-goals (explicit)**

- Commercial licensing, collaborative editing, full formula engine, `App.tsx` monolith split (follow-up PR).

---

## 5. Product requirements (backlog)

| ID | Priority | User story | Acceptance criteria | Notes |
| --- | -------- | ---------- | ------------------- | ----- |
| R1 | P0 | As a visitor I want a short README so I know what this is in 10s | TL;DR + `demo-flow.svg` linked from README | Done 2026-06-12 |
| R2 | P0 | As a clone I want CI so I trust PRs | `.github/workflows/ci.yml` green on main | Done 2026-06-12 |
| R3 | P1 | As a non-Chinese reader I want an English entry point | English root `README.md` + `README.cn.md` + `docs/README.md` audience note | Done 2026-06-12 |
| R4 | P2 | As a maintainer I want smaller UI files | Split `App.tsx` by panel (DiffPreviewBar, CmdKPanel, …) | **Pending** — defer follow-up PR |

**Open questions**

| # | Question | Owner | Resolution / date |
| --- | -------- | ----- | ----------------- |
| Q1 | Record `demo.gif` for README? | Maintainer | Optional; SVG workflow shipped; GIF still welcome in `docs/assets/` |

---

## 6. Technical constraints (optional)

- **Platforms / env**: Python 3.10+ (CI 3.11), Node 18+, `server/.venv` via uv only.
- **Security / privacy**: CC BY-NC; demo `new Function`; audit SQLite local-only.
- **Compat**: OpenRouter + Ollama; no cloud E2E in CI.

---

## 7. Rollout & verification

- **How to demo**: Ollama path → load sample → Cmd+K → Generate Plan → Apply → Undo.
- **Risks**: README drift vs code; mitigated by linking deep docs.
- **Follow-ups**: `split-app-tsx`, optional `demo.gif`.

---

## 8. Document changelog

| Date | Author | Summary |
| ---- | ------ | ------- |
| 2026-06-08 | Pawpaw | Seeded open-source readiness milestone (README trim, CI, demo asset, CONTRIBUTING). |
| 2026-06-12 | Agent | Filled P0/P1 rows; marked Phase 1–2 items complete; R4 split deferred. |

---

## Appendix A — Project baseline (reference only)

| Layer | Main pieces |
| ----- | ----------- |
| **Frontend** | React + Vite + AG Grid; `client/src/App.tsx`, `engine.ts`, `llm.ts` |
| **Backend** | FastAPI; `server/app/api/routes/` |
| **Agent** | `server/app/agent/`, `app/services/llm.py`, `tools.py` |
| **Contract** | JSON `Plan` shared by prompts, executor, client engine |

*User-facing run instructions: root README + `docs/getting-started.md`.*
