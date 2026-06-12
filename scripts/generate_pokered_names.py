"""Generate env/pokered_names.py from the pret/pokered disassembly in third_party/.

Run manually after updating third_party/pokered:
    uv run python scripts/generate_pokered_names.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POKERED = ROOT / "third_party" / "pokered"
OUT = ROOT / "env" / "pokered_names.py"

SPECIAL_WORDS = {
    "M": "♂",
    "F": "♀",
    "2F": "2F",
    "3F": "3F",
    "4F": "4F",
    "5F": "5F",
    "B1F": "B1F",
    "B2F": "B2F",
    "B3F": "B3F",
    "B4F": "B4F",
    "SS": "S.S.",
    "PC": "PC",
    "NW": "NW",
    "NE": "NE",
    "SW": "SW",
    "SE": "SE",
}


def pretty(name: str) -> str:
    words = []
    for word in name.split("_"):
        if word in SPECIAL_WORDS:
            words.append(SPECIAL_WORDS[word])
        elif word.startswith("ROUTE") and word[5:].isdigit():
            words.append(f"Route {word[5:]}")
        else:
            words.append(word.capitalize())
    out = " ".join(words)
    # NIDORAN_M -> "Nidoran♂" (gender sign attaches without a space)
    out = out.replace(" ♂", "♂").replace(" ♀", "♀")
    return out


def parse_species() -> dict[int, str]:
    text = (POKERED / "constants" / "pokemon_constants.asm").read_text()
    species: dict[int, str] = {}
    index = 0
    for line in text.splitlines():
        if re.match(r"\s*const_skip\b", line):
            index += 1
            continue
        match = re.match(r"\s*const\s+([A-Z0-9_]+)", line)
        if not match:
            continue
        name = match.group(1)
        if name != "NO_MON":
            species[index] = pretty(name)
        index += 1
    return species


def parse_moves() -> dict[int, str]:
    text = (POKERED / "constants" / "move_constants.asm").read_text()
    moves: dict[int, str] = {}
    index = 0
    for line in text.splitlines():
        if re.match(r"\s*const_skip\b", line):
            index += 1
            continue
        match = re.match(r"\s*const\s+([A-Z0-9_]+)", line)
        if not match:
            continue
        name = match.group(1)
        if name != "NO_MOVE":
            moves[index] = pretty(name)
        index += 1
        if index > 165:  # moves end at STRUGGLE ($A5); later consts are animations
            break
    return moves


def parse_dex_order() -> dict[int, str]:
    """National dex number -> name (1..151). Also the Gen 3 internal species ids."""
    text = (POKERED / "constants" / "pokedex_constants.asm").read_text()
    out: dict[int, str] = {}
    index = 0
    for line in text.splitlines():
        match = re.match(r"\s*const\s+DEX_([A-Z0-9_]+)", line)
        if not match:
            continue
        index += 1
        out[index] = pretty(match.group(1))
    return out


def parse_maps() -> dict[int, str]:
    return {index: pretty(name) for index, name in parse_map_constants().items()}


def parse_map_constants() -> dict[int, str]:
    text = (POKERED / "constants" / "map_constants.asm").read_text()
    maps: dict[int, str] = {}
    index = 0
    for line in text.splitlines():
        match = re.match(r"\s*map_const\s+([A-Z0-9_]+),", line)
        if not match:
            continue
        maps[index] = match.group(1)
        index += 1
    return maps


def parse_warps_and_connections() -> tuple[dict[int, list], dict[int, dict[str, int]]]:
    """Warp tiles (doors/stairs) and outdoor edge connections for every map.

    Mined from data/maps/headers/*.asm (object label -> MAP_CONSTANT and
    `connection` lines) and data/maps/objects/<Label>.asm (`warp_event` lines).
    """
    constant_to_id = {name: index for index, name in parse_map_constants().items()}
    warps: dict[int, list] = {}
    connections: dict[int, dict[str, int]] = {}
    headers_dir = POKERED / "data" / "maps" / "headers"
    objects_dir = POKERED / "data" / "maps" / "objects"
    for header in sorted(headers_dir.glob("*.asm")):
        text = header.read_text()
        head = re.search(r"map_header\s+(\w+),\s+([A-Z0-9_]+)", text)
        if not head:
            continue
        label, constant = head.group(1), head.group(2)
        map_id = constant_to_id.get(constant)
        if map_id is None:
            continue
        for conn in re.finditer(r"connection\s+(north|south|east|west),\s*\w+,\s*([A-Z0-9_]+)", text):
            dest = constant_to_id.get(conn.group(2))
            if dest is not None:
                connections.setdefault(map_id, {})[conn.group(1)] = dest
        object_file = objects_dir / f"{label}.asm"
        if not object_file.exists():
            continue
        entries = []
        for warp in re.finditer(r"warp_event\s+(\d+),\s*(\d+),\s*([A-Z0-9_]+)", object_file.read_text()):
            x, y, dest_const = int(warp.group(1)), int(warp.group(2)), warp.group(3)
            dest = constant_to_id.get(dest_const)  # None for LAST_MAP ("outside")
            entries.append((x, y, dest))
        if entries:
            warps[map_id] = entries
    return warps, connections


def main() -> None:
    species = parse_species()
    maps = parse_maps()
    dex = parse_dex_order()
    moves = parse_moves()
    warps, connections = parse_warps_and_connections()
    lines = [
        '"""Gen 1 internal species index -> name and map id -> name tables.',
        "",
        "Generated by scripts/generate_pokered_names.py from pret/pokered constants.",
        "Do not edit by hand.",
        '"""',
        "",
        "SPECIES_NAMES: dict[int, str] = {",
    ]
    for index in sorted(species):
        lines.append(f"    {index}: {species[index]!r},")
    lines.append("}")
    lines.append("")
    lines.append("MAP_NAMES: dict[int, str] = {")
    for index in sorted(maps):
        lines.append(f"    {index}: {maps[index]!r},")
    lines.append("}")
    lines.append("")
    lines.append("# National dex number -> name. Doubles as Gen 3 internal species ids 1..151.")
    lines.append("DEX_SPECIES_NAMES: dict[int, str] = {")
    for index in sorted(dex):
        lines.append(f"    {index}: {dex[index]!r},")
    lines.append("}")
    lines.append("")
    lines.append("MOVE_NAMES: dict[int, str] = {")
    for index in sorted(moves):
        lines.append(f"    {index}: {moves[index]!r},")
    lines.append("}")
    lines.append("")
    lines.append("# map id -> [(x, y, destination map id | None for 'back outside')]")
    lines.append("MAP_WARPS: dict[int, list[tuple[int, int, int | None]]] = {")
    for map_id in sorted(warps):
        lines.append(f"    {map_id}: {warps[map_id]!r},")
    lines.append("}")
    lines.append("")
    lines.append("# map id -> {edge direction: neighbouring map id}")
    lines.append("MAP_CONNECTIONS: dict[int, dict[str, int]] = {")
    for map_id in sorted(connections):
        lines.append(f"    {map_id}: {connections[map_id]!r},")
    lines.append("}")
    lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"Wrote {OUT} ({len(species)} species, {len(maps)} maps, {len(dex)} dex, "
        f"{len(moves)} moves, {len(warps)} warp maps, {len(connections)} connected maps)"
    )


if __name__ == "__main__":
    main()
