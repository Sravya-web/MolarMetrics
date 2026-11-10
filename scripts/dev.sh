#!/usr/bin/env bash
# MolarMetrics development mode:
#   API with auto-reload on http://127.0.0.1:8000
#   web app with hot reload on http://127.0.0.1:5173  (open this one)
# Both listen on this computer only. Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -x .venv/bin/python ] || { echo "The Python environment (.venv) is missing. See README." >&2; exit 1; }
[ -d web/node_modules ] || (cd web && npm ci --no-fund --no-audit)

.venv/bin/python -m molarmetrics.api --reload &
API_PID=$!
trap 'kill "${API_PID}" 2>/dev/null || true' EXIT INT TERM

echo "Open http://127.0.0.1:5173"
cd web && npx vite
