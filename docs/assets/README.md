# Demo assets

Visual demos for the root [README](../../README.md).

## Files

| File | Purpose | Status |
|------|---------|--------|
| [`demo-flow.svg`](./demo-flow.svg) | Cmd+K → Plan → Diff → Apply workflow diagram | **Committed** — linked from README |
| `demo.gif` or `demo.png` | Optional screen recording or screenshot of live UI | **TODO** — not yet committed |

## Suggested capture script (for GIF/PNG)

1. Start the stack (README Quick Start — Ollama path).
2. Open `http://localhost:5173` with the built-in sample tables loaded.
3. Press **Cmd+K** (Windows/Linux: **Ctrl+K**).
4. Enter: `在销售订单表新增金额列 = 数量 * 单价`
5. Click **Generate Plan** — show green/yellow column highlights and Diff Preview bar.
6. Click **Apply** — show updated grid and optional Undo.

Record at 1280×720 or similar; keep file size reasonable for GitHub (< 5 MB for GIF).
