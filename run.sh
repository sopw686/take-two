#!/usr/bin/env bash
# Run Marked (macOS / Linux / Git Bash). See run.ps1 for the Windows version.
#   ./run.sh              start on http://127.0.0.1:8765
#   REBUILD=1 ./run.sh    force a frontend rebuild (it also rebuilds by itself when sources are newer than the build)
#   MARKED_STT_DEVICE=cpu ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
if command -v nvidia-smi >/dev/null 2>&1 && [ "${MARKED_STT_DEVICE:-}" != "cpu" ]; then
  uv sync --extra gpu
else
  uv sync
fi

# Rebuild when any frontend source is newer than the last build, so a pulled or edited UI is never served stale.
stale=""
if [ -f frontend/dist/index.html ] && \
   [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html -print 2>/dev/null | head -n 1)" ]; then
  echo "Frontend sources changed since the last build; rebuilding."
  stale=1
fi
if [ -n "${REBUILD:-}" ] || [ -n "$stale" ] || [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null; then
    (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build)
  else
    echo "npm not found; the API will run without the UI."
  fi
fi

PORT="${PORT:-8765}"
echo "Marked -> http://127.0.0.1:$PORT"
exec uv run uvicorn marked.app:app --host 127.0.0.1 --port "$PORT"
