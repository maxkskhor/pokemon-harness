#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS_YAML="$ROOT_DIR/agents.yaml"
LOG_DIR="$ROOT_DIR/logs"

PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"
uv run uvicorn env.app:app --host 127.0.0.1 --port 8000 &
PIDS+=($!)

cd "$ROOT_DIR/ui"
npm run dev -- --host 127.0.0.1 --port 5173 &
PIDS+=($!)

echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5173"

# Wait for backend to be ready before spawning agents.
echo "Waiting for backend..."
until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do
  sleep 0.5
done
echo "Backend ready."

# Launch each agent defined in agents.yaml.
if [ -f "$AGENTS_YAML" ]; then
  while IFS= read -r module; do
    [ -z "$module" ] && continue
    log_file="$LOG_DIR/${module##*.}.log"
    echo "Starting agent: $module  →  $log_file"
    cd "$ROOT_DIR"
    uv run python -m "$module" >"$log_file" 2>&1 &
    PIDS+=($!)
  done < <(python3 -c "
import yaml, sys
with open('$AGENTS_YAML') as f:
    data = yaml.safe_load(f)
for agent in data.get('agents', []):
    print(agent['module'])
")
fi

wait
