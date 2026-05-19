#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_URL="http://127.0.0.1:8000/api/health"
BACKEND_PID=""

cleanup() {
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cd "$ROOT_DIR"

echo "Installing Python dependencies..."
uv sync --dev

echo "Installing UI dependencies..."
(cd ui && npm install)

echo "Building local ROM artifacts..."
scripts/setup_pokered.sh

if curl -fsS "$BACKEND_URL" >/dev/null 2>&1; then
  echo "Using existing backend at http://127.0.0.1:8000"
else
  echo "Starting temporary backend for bedroom save-state setup..."
  uv run uvicorn env.app:app --host 127.0.0.1 --port 8000 >/tmp/pokemon-harness-setup-backend.log 2>&1 &
  BACKEND_PID=$!
fi

echo "Creating default bedroom save state..."
uv run python scripts/setup.py --create-bedroom-state

echo "Setup complete. Run scripts/dev.sh to start the backend and UI."
