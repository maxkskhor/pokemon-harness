#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POKERED_DIR="$ROOT_DIR/third_party/pokered"
ROMS_DIR="$ROOT_DIR/roms"

if ! command -v rgbasm >/dev/null 2>&1; then
  echo "Missing RGBDS. Install it with:"
  echo "  brew install rgbds"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Missing git."
  exit 1
fi

if ! command -v make >/dev/null 2>&1; then
  echo "Missing make."
  exit 1
fi

mkdir -p "$ROMS_DIR"

if [ ! -d "$POKERED_DIR/.git" ]; then
  git clone https://github.com/pret/pokered "$POKERED_DIR"
fi

cd "$POKERED_DIR"
make
make compare

for file in pokered.gbc pokeblue.gbc BLUEMONS.GB pokered.sym pokeblue.sym BLUEMONS.sym; do
  if [ -f "$file" ]; then
    cp "$file" "$ROMS_DIR/$file"
  fi
done

echo "Local ROM artifacts copied to $ROMS_DIR"

