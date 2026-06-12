#!/usr/bin/env bash
# Build Pokemon Fire Red from the pret decompilation and the mGBA Python
# bindings that run it. Everything is built from upstream source into
# third_party/; artifacts land in roms/.
#
# Requirements (macOS): brew install cmake libpng pkg-config arm-none-eabi-binutils
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THIRD_PARTY="$ROOT_DIR/third_party"
ROMS_DIR="$ROOT_DIR/roms"
MGBA_TAG="0.10.5"

mkdir -p "$THIRD_PARTY" "$ROMS_DIR"

for tool in cmake make git arm-none-eabi-as arm-none-eabi-nm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. Install build deps first:"
    echo "  brew install cmake libpng pkg-config arm-none-eabi-binutils"
    exit 1
  fi
done

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "Project venv missing. Run scripts/setup.sh (or 'uv sync') first."
  exit 1
fi

echo "==> 1/5 Building agbcc (GBA compiler)"
if [ ! -d "$THIRD_PARTY/agbcc/.git" ]; then
  git clone --depth 1 https://github.com/pret/agbcc "$THIRD_PARTY/agbcc"
fi
if [ ! -d "$THIRD_PARTY/pokefirered/.git" ]; then
  git clone --depth 1 https://github.com/pret/pokefirered "$THIRD_PARTY/pokefirered"
fi
if [ ! -x "$THIRD_PARTY/pokefirered/tools/agbcc/bin/agbcc" ]; then
  (cd "$THIRD_PARTY/agbcc" && ./build.sh && ./install.sh ../pokefirered)
fi

echo "==> 2/5 Building Pokemon Fire Red ROM (this takes a few minutes)"
(cd "$THIRD_PARTY/pokefirered" && make -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)")
(cd "$THIRD_PARTY/pokefirered" && make compare) || echo "WARNING: ROM does not byte-match the retail checksum"
cp "$THIRD_PARTY/pokefirered/pokefirered.gba" "$ROMS_DIR/"

echo "==> 3/5 Extracting RAM symbols"
(cd "$THIRD_PARTY/pokefirered" \
  && arm-none-eabi-nm pokefirered.elf \
  | grep -E "^0[23][0-9a-f]{6} [BbDdGg] " \
  | awk '{print $1, $3}' > "$ROMS_DIR/pokefirered.sym")

echo "==> 4/5 Building mGBA $MGBA_TAG Python bindings"
if [ ! -d "$THIRD_PARTY/mgba/.git" ]; then
  git clone --depth 1 --branch "$MGBA_TAG" https://github.com/mgba-emu/mgba "$THIRD_PARTY/mgba"
fi
# Guard the e-Reader scan API (only built with FFmpeg) so the cffi glue does
# not reference symbols that a no-FFmpeg build leaves out.
if ! grep -q "ifdef USE_FFMPEG" "$THIRD_PARTY/mgba/include/mgba/internal/gba/cart/ereader.h"; then
  (cd "$THIRD_PARTY/mgba" && git apply "$ROOT_DIR/scripts/patches/mgba-ereader-ffmpeg-guard.patch")
fi

PY_LIBDIR="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
PY_INCLUDE="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
PY_VERSION="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("LDVERSION"))')"

mkdir -p "$THIRD_PARTY/mgba/build"
(cd "$THIRD_PARTY/mgba/build" && cmake \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DBUILD_PYTHON=ON -DBUILD_SHARED=OFF -DBUILD_STATIC=ON \
  -DBUILD_QT=OFF -DBUILD_SDL=OFF -DUSE_FFMPEG=OFF -DUSE_DISCORD_RPC=OFF -DUSE_DEBUGGERS=ON \
  -DPYTHON_EXECUTABLE="$PYTHON_BIN" \
  -DPYTHON_LIBRARY="$PY_LIBDIR/libpython$PY_VERSION.dylib" \
  -DPYTHON_INCLUDE_DIR="$PY_INCLUDE" \
  .. && make -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)")

echo "==> 5/5 Creating the Fire Red bedroom start state"
BACKEND_PID=""
if ! curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "Starting temporary backend..."
  (cd "$ROOT_DIR" && uv run uvicorn env.app:app --host 127.0.0.1 --port 8000 \
    >/tmp/pokemon-harness-firered-backend.log 2>&1) &
  BACKEND_PID=$!
fi
(cd "$ROOT_DIR" && uv run python scripts/setup.py --create-bedroom-state --rom pokefirered.gba)
if [ -n "$BACKEND_PID" ]; then
  kill "$BACKEND_PID" 2>/dev/null || true
fi

echo
echo "Verifying..."
"$PYTHON_BIN" - <<EOF
import sys
from pathlib import Path
build = Path("$THIRD_PARTY/mgba/build/python")
libdir = next(p for p in build.glob("lib*") if (p / "mgba").exists())
sys.path.insert(0, str(libdir))
import mgba.core
core = mgba.core.load_path("$ROMS_DIR/pokefirered.gba")
assert core is not None
print("Fire Red ROM + mGBA bindings OK")
EOF
echo "Done. Select POKEMON FIRE in the UI's game dropdown."
