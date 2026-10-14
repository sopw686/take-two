#!/usr/bin/env bash
# Run Take Two (macOS / Linux / Git Bash). See run.ps1 for the Windows version.
#   ./run.sh              start on http://127.0.0.1:8765
#   REBUILD=1 ./run.sh    force a frontend rebuild (it also rebuilds by itself when sources are newer than the build)
#   TAKE_TWO_STT_DEVICE=cpu ./run.sh                force CPU speech-to-text (the CUDA libraries stay installed)
#   TAKE_TWO_STT_MODEL=base.en ./run.sh             pick the local speech-to-text model
#   TAKE_TWO_TAKES_DIR=~/take-two-takes ./run.sh    save takes there, e.g. outside a synced folder
#   TAKE_TWO_STT=openai ./run.sh                    cloud transcription (needs OPENAI_API_KEY; installs the "cloud" extra)
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
# uv sync is exact: an extra left out is uninstalled. So a CPU run keeps the gpu extra and only picks the device.
extras=()
if command -v nvidia-smi >/dev/null 2>&1; then extras+=(--extra gpu); fi
if [ "${TAKE_TWO_STT:-}" = "openai" ]; then extras+=(--extra cloud); fi
uv sync ${extras[@]+"${extras[@]}"} || { echo "uv sync failed; not starting." >&2; exit 1; }

# Rebuild when any frontend source is newer than the last build, so a pulled or edited UI is never served stale.
stale=""
if [ -f frontend/dist/index.html ] && \
   [ -n "$(find frontend/src frontend/index.html frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
             frontend/tsconfig.json -newer frontend/dist/index.html -print 2>/dev/null | head -n 1)" ]; then
  echo "Frontend sources changed since the last build; rebuilding."
  stale=1
fi
if [ -n "${REBUILD:-}" ] || [ -n "$stale" ] || [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null; then
    (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build) \
      || { echo "The frontend build failed; not starting." >&2; exit 1; }
  else
    echo "npm not found; the API will run without the UI."
  fi
fi

PORT="${PORT:-8765}"
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  echo "Port $PORT is already in use; is Take Two already running? Stop it, or start on another port: PORT=8766 ./run.sh" >&2
  exit 1
fi
echo "Take Two -> http://127.0.0.1:$PORT"
exec uv run uvicorn take_two.app:app --host 127.0.0.1 --port "$PORT"
