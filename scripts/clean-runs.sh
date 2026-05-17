#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="$ROOT_DIR/runs"
STATES_DIR="$ROOT_DIR/states"
DAYS=30
DRY_RUN=false

usage() {
  echo "Usage: scripts/clean-runs.sh [--dry-run] [--days N]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --days)
      DAYS="${2:-}"
      if [[ ! "$DAYS" =~ ^[0-9]+$ ]]; then
        usage >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [ ! -d "$RUNS_DIR" ]; then
  echo "No runs directory found."
  exit 0
fi

found=false
while IFS= read -r -d '' run_dir; do
  run_id="$(basename "$run_dir")"
  if [ "$run_id" = "shared" ]; then
    continue
  fi
  found=true
  state_dir="$STATES_DIR/$run_id"
  if [ "$DRY_RUN" = true ]; then
    if [ -d "$state_dir" ]; then
      echo "Would remove $run_dir and $state_dir"
    else
      echo "Would remove $run_dir"
    fi
  else
    rm -rf "$run_dir"
    if [ -d "$state_dir" ]; then
      rm -rf "$state_dir"
    fi
    echo "Removed $run_id"
  fi
done < <(find "$RUNS_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +"$DAYS" -print0)

if [ "$found" = false ]; then
  echo "No run directories older than $DAYS days."
fi
