# Contributing

Thank you for interest in this personal learning project. This repo is **CC BY-NC 4.0**: you may fork, learn, and adapt for **non-commercial** use if you keep attribution.

## Before you fork

1. Read [LICENSE](LICENSE) and the root [README](README.md) § **Project declaration & license** ([中文](README.cn.md#项目声明与许可)).
2. **Non-commercial only** — no production SaaS, paid services, or internal for-profit use without written permission from the copyright holder.
3. **Attribution required** — keep a visible notice, for example:

   ```
   Based on "Cursor for Spreadsheet" (cursor-for-spreadsheet-mvp)
   Original: https://github.com/Pawpaw497/cursor-for-spreadsheet-mvp
   (Clone directory name may differ from the historical repo slug.)
   License: CC BY-NC 4.0
   ```

## Development setup

Full setup (Ollama path, OpenRouter, `.env` keys): [docs/getting-started.md](docs/getting-started.md).

Minimal loop:

```bash
# Backend (server/.venv via uv)
cd server && uv sync && uv run uvicorn main:app --reload --port 8787

# Frontend (separate terminal)
cd client && npm install && npm run dev
```

Or from repo root: `make dev` (starts both in background — stop processes manually when done).

## Running tests

Match CI and the README dev section:

```bash
make test
# or separately:
make test-server   # cd server && uv sync && uv run pytest -q
make test-client   # cd client && npm ci && npm test
```

Cloud LLM E2E (`RUN_CLOUD_LLM_E2E=1`) is **not** run in CI; optional locally with `OPENROUTER_API_KEY`.

## Pull requests

1. Fork and create a branch from `main`.
2. Keep changes focused; avoid unrelated refactors.
3. Run `make test` (or both test targets) before opening a PR.
4. Update user-visible behavior in README or the relevant `docs/` file.
5. PRs should pass [.github/workflows/ci.yml](.github/workflows/ci.yml) (backend pytest + client Vitest).

## Maintainer notes

- `.cursor/` (rules, plans, skills) is **gitignored** and local-only; it is not the public roadmap.
- Do not commit secrets (`.env`), `server/data/`, or `logs/`.

Questions and small fixes are welcome via issues or PRs.
