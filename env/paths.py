from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROMS_DIR = PROJECT_ROOT / "roms"
RUNS_DIR = PROJECT_ROOT / "runs"
STATES_DIR = PROJECT_ROOT / "states"


ROM_SUFFIXES = (".gb", ".gbc", ".gba")


def list_rom_files() -> list[Path]:
    if not ROMS_DIR.exists():
        return []
    return sorted(
        path for path in ROMS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in ROM_SUFFIXES
    )


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

