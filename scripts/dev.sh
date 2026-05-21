#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS_YAML="$ROOT_DIR/agents.yaml"
LOG_DIR="$ROOT_DIR/logs"

# Kill the entire process group on exit so uv/npm child processes (python, vite, etc.)
# don't survive as orphans after Ctrl+C. kill 0 = send to every process in this
# process group, which includes all background jobs and their children.
cleanup() {
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR"

# Kill any stale processes from a previous run on the ports we need.
for port in 8000 5173; do
  pids=$(lsof -ti :"$port" 2>/dev/null) && [ -n "$pids" ] && kill $pids 2>/dev/null || true
done

cd "$ROOT_DIR"
uv run uvicorn env.app:app --host 127.0.0.1 --port 8000 >"$LOG_DIR/backend.log" 2>&1 &

cd "$ROOT_DIR/ui"
npm run dev -- --host 127.0.0.1 --port 5173 >"$LOG_DIR/frontend.log" 2>&1 &

echo "Backend:  http://127.0.0.1:8000  →  $LOG_DIR/backend.log"
echo "Frontend: http://127.0.0.1:5173  →  $LOG_DIR/frontend.log"

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
    PYTHONUNBUFFERED=1 uv run python -m "$module" >"$log_file" 2>&1 &
  done < <(cd "$ROOT_DIR" && uv run python -c "
import yaml
with open('$AGENTS_YAML') as f:
    data = yaml.safe_load(f)
for agent in data.get('agents', []):
    print(agent['module'])
")
fi

wait
