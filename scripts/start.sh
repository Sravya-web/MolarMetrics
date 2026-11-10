#!/usr/bin/env bash
# MolarMetrics: start the local app (one server on http://127.0.0.1:8000).
#
#   ./scripts/start.sh            build the web app if needed, then serve it
#   ./scripts/start.sh --open     ...and open it in your browser
#
# Everything runs on this computer only. Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${MOLARMETRICS_API_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

if [ ! -x .venv/bin/python ]; then
  echo "The Python environment (.venv) is missing. See README: 'First-time setup'." >&2
  exit 1
fi
if ! .venv/bin/python -c "import fastapi, uvicorn, multipart" 2>/dev/null; then
  echo "Python packages are missing. Run: .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js (npm) is needed to build the web app the first time. Install Node 22, then retry." >&2
  exit 1
fi

# Build the web app when it is missing or older than its source files.
if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html -print -quit)" ]; then
  echo "Building the web app..."
  (cd web && { [ -d node_modules ] || npm ci --no-fund --no-audit; } && npm run build)
fi

echo "MolarMetrics is starting at ${URL}"
if [ "${1:-}" = "--open" ]; then
  (sleep 2 && open "${URL}") &
fi
exec .venv/bin/python -m molarmetrics.api --port "${PORT}"
