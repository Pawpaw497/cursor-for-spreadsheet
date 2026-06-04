# Product brief & requirements

> **How to use this doc**  
> Personal project milestone sheet: capture what you want next, constraints, and how to verify it. The coding agent uses this (with code and `.cursor/plans/`) to refine tasks—**not** `docs/goals.md`, which is unused.  
> 中文说明：个人持续开发项目的**阶段需求单**；每轮迭代更新优先级与 *Document changelog* 即可。

---

## 1. Document meta


| Field             | Value                                          |
| ----------------- | ---------------------------------------------- |
| **Title**         | *(short name for this initiative / milestone)* |
| **Owner**         | *(you)*                                       |
| **Status**        | *Draft / Active / Parked*                      |
| **Last updated**  | *YYYY-MM-DD*                                   |
| **Related links** | *e.g. PRs, issues, Figma, internal wiki*       |


---

## 2. Problem statement

*What user pain or product gap are we addressing? 1–3 sentences.*

- **Context**:
- **Pain**:
- **Why now**:

---

## 3. Target users & scenarios

*Who uses this and in what flow? Be specific enough to test against.*


| Persona / role | Primary scenario | Out of scope for *this* iteration |
| -------------- | ---------------- | --------------------------------- |
|                |                  |                                   |
|                |                  |                                   |


---

## 4. Success criteria (measurable)

*How we know we are done. Prefer testable statements.*

- Criterion 1: *(metric or demo script)*
- Criterion 2:
- Criterion 3:

**Non-goals (explicit)**: *what we will not build in this pass*

- 

---

## 5. Product requirements (backlog)

*Order by **Priority** (P0 = must, P1 = should, P2 = could). One row per feature slice.*


| ID  | Priority | User story (As a … I want … so that …) | Acceptance criteria (Given / When / Then) | Notes / dependencies |
| --- | -------- | -------------------------------------- | ----------------------------------------- | -------------------- |
| R1  | P0       |                                        |                                           |                      |
| R2  | P1       |                                        |                                           |                      |


**Open questions** *(blocking vs nice-to-have)*


| #   | Question | Owner | Resolution / date |
| --- | -------- | ----- | ----------------- |
| Q1  |          |       |                   |


---

## 6. Technical constraints (optional)

*Only if they matter for this initiative.*

- **Platforms / env**:
- **Performance / scale**:
- **Security / privacy**:
- **Compat** *(browsers, Excel limits, model providers)*:

---

## 7. Rollout & verification

- **How to demo** *(steps to verify in UI or API)*:
- **Risks**:
- **Follow-ups** *(next milestone ideas — do not scope creep this doc without a new section)*:

---

## 8. Document changelog


| Date | Author | Summary |
| ---- | ------ | ------- |
|      |        |         |


---

## Appendix A — Project baseline (reference only, do not duplicate README)

*The agent can refresh this table when architecture shifts; you usually do not edit it by hand.*


| Layer        | Main pieces                                                                                                            |
| ------------ | ---------------------------------------------------------------------------------------------------------------------- |
| **Frontend** | React + Vite + AG Grid; `client/src/App.tsx`, `client/src/engine.ts`, `client/src/llm.ts`                              |
| **Backend**  | FastAPI; routes under `server/app/api/routes/` (`plan`, `agent`, `chat`, `config`, `export`, `load`, `health`)         |
| **Agent**    | `server/app/agent/` (state, decision loop, sub-agents, tools in `app/services/tools.py`, LLM in `app/services/llm.py`) |
| **Contract** | JSON `Plan` / project plans shared by prompts, executor, and client engine                                             |


*Update README for user-facing "how to run"; use this file for **your** next milestone requirements.*