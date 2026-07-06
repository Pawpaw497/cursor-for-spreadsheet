.PHONY: dev test test-server test-client

dev:
	@echo "Starting backend (8787) and frontend (5173) in background."
	@test -f server/.env || (cp server/.env.example server/.env && echo "Created server/.env from .env.example")
	@echo "Stop manually from repo root (narrows to this project path):"
	@echo "  pkill -f 'cursor-for-spreadsheet/server.*uvicorn main:app' || true"
	@echo "  pkill -f 'cursor-for-spreadsheet/client.*vite' || true"
	@cd server && uv sync && uv run uvicorn main:app --reload --port 8787 & \
	cd client && npm install && npm run dev & \
	wait

test: test-server test-client

test-server:
	cd server && uv sync && uv run pytest -q

test-client:
	cd client && npm ci && npm test
