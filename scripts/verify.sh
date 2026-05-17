#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/ -v
UV_CACHE_DIR=/private/tmp/uv-cache uv run pyright env harness

cd "$ROOT_DIR/ui"
npm run lint
npm run build
npm run test:smoke
