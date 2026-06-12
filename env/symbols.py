from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SYMBOL_RE = re.compile(r"^(?P<bank>[0-9A-Fa-f]{2}):(?P<addr>[0-9A-Fa-f]{4})\s+(?P<label>[A-Za-z0-9_.$@]+)$")
# GBA symbols (from arm-none-eabi-nm): full 32-bit address + label.
SYMBOL_GBA_RE = re.compile(r"^(?P<addr>[0-9A-Fa-f]{8})\s+(?P<label>[A-Za-z0-9_.$@]+)$")


@dataclass(frozen=True)
class SymbolMap:
    labels: dict[str, int]
    source: str | None = None

    def address(self, *names: str) -> int | None:
        for name in names:
            if name in self.labels:
                return self.labels[name]
        return None


def parse_sym_file(path: Path | None) -> SymbolMap:
    if path is None or not path.exists():
        return SymbolMap(labels={}, source=None)

    labels: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        match = SYMBOL_RE.match(stripped)
        if match:
            labels[match.group("label")] = int(match.group("addr"), 16)
            continue
        gba_match = SYMBOL_GBA_RE.match(stripped)
        if gba_match:
            labels[gba_match.group("label")] = int(gba_match.group("addr"), 16)
    return SymbolMap(labels=labels, source=str(path))


POKEMON_LABEL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "map_id": ("wCurMap",),
    "x": ("wXCoord",),
    "y": ("wYCoord",),
    "direction": ("wPlayerMovingDirection", "wPlayerDirection", "wSpritePlayerStateData1FacingDirection"),
    "menu_state": ("wCurrentMenuItem", "wMenuSelection", "wMenuWatchedKeys"),
    "text_state": ("wTextBoxID", "wTextDest", "wTextDelayFrames"),
    "party_count": ("wPartyCount",),
    "joy_ignore": ("wJoyIgnore",),
    "ignore_input_counter": ("wIgnoreInputCounter",),
    "map_script": ("wCurMapScript",),
}


def read_pokemon_labels(symbols: SymbolMap, read_byte) -> dict[str, int | None]:
    values: dict[str, int | None] = {}
    for field, candidates in POKEMON_LABEL_CANDIDATES.items():
        address = symbols.address(*candidates)
        if address is None:
            values[field] = None
            continue
        try:
            values[field] = int(read_byte(address))
        except Exception:
            values[field] = None
    return values
