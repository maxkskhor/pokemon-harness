from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROMS_DIR = PROJECT_ROOT / "roms"
RUNS_DIR = PROJECT_ROOT / "runs"
STATES_DIR = PROJECT_ROOT / "states"


def default_rom_path() -> Path | None:
    for name in ("pokered.gbc", "pokeblue.gbc", "BLUEMONS.GB"):
        candidate = ROMS_DIR / name
        if candidate.exists():
            return candidate
    return None


def default_symbol_path(rom_path: Path) -> Path | None:
    candidates = [
        rom_path.with_suffix(".sym"),
        ROMS_DIR / f"{rom_path.stem}.sym",
        ROMS_DIR / f"{rom_path.name}.sym",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

