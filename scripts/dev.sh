#!/usr/bin/env bash
# Runs the API (http://127.0.0.1:8000) and the UI dev server (http://localhost:5173) together.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/restore_index.py
trap 'kill 0' EXIT
(cd backend && uv run uvicorn app.main:app --reload --port 8000) &
(cd web && npm run dev) &
wait
