# Cursor for Spreadsheet — MVP (English)

Personal learning project (beginner-level demo): **Cmd+K** natural language → structured **Plan** → previewable **Diff** → **Apply** with undo — not chat-to-CSV.

**Differentiator:** Structured JSON plans you can inspect, dry-run in the grid, apply, or roll back — vs. opaque text dumps.

## License

[CC BY-NC 4.0](LICENSE) — **non-commercial** use only; **attribution required** when you fork or adapt. No production warranty. Demo only: `add_column` expressions run via `new Function` in the browser. Do not use sensitive data. Full terms: [README.md](README.md) § 项目声明与许可.

## Quick links

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Main readme (Chinese) — setup, declaration, doc index |
| [docs/getting-started.md](docs/getting-started.md) | Full setup: Ollama (no API key) or OpenRouter |
| [docs/features.md](docs/features.md) | Feature deep dive |
| [docs/README.md](docs/README.md) | English technical reference index |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Fork, attribution, tests, PRs |

## Run (Ollama, recommended)

```bash
git clone https://github.com/Pawpaw497/cursor-for-spreadsheet-mvp.git
cd cursor-for-spreadsheet-mvp
ollama serve   # separate terminal
ollama pull qwen2.5:7b
cd server && cp .env.example .env && uv sync && uv run uvicorn main:app --reload --port 8787
# new terminal from repo root:
cd client && npm install && npm run dev   # http://localhost:5173
```

Workflow: ![Cmd+K → Plan → Diff → Apply](docs/assets/demo-flow.svg)

## Tests

```bash
make test
```
