"""Pokemon Fire Red / Leaf Green (Gen 3, GBA) game-state reader.

Offsets verified against the pret/pokefirered disassembly:
- SaveBlock2: playerName @0x000, playTimeHours u16 @0x00E, playTimeMinutes @0x010,
  encryptionKey u32 @0xF20.
- SaveBlock1: pos x/y s16 @0x0000/0x0002, location mapGroup/mapNum @0x0004/0x0005,
  money u32 @0x0290 (XOR encryptionKey), flags @0x0EE0 (badges = flags 0x820..0x827).
- Party mon (100 bytes): personality u32 @0, otId u32 @4, nickname @8 (10 bytes),
  status u32 @80, level u8 @84, hp u16 @86, maxHP u16 @88. Species lives in the
  encrypted Growth substructure (12-byte blocks starting @32, XOR personality^otId,
  block order keyed by personality % 24).
"""
from __future__ import annotations

from typing import Any, Callable

from env.pokefirered_names import (
    FIRERED_MAP_CONNECTIONS,
    FIRERED_MAP_NAMES,
    FIRERED_MAP_WARPS,
)
from env.pokered_names import DEX_SPECIES_NAMES
from env.symbols import SymbolMap

ReadByte = Callable[[int], int]

PARTY_MON_SIZE = 100
EWRAM_START, EWRAM_END = 0x02000000, 0x02040000

# Position of the Growth substructure for personality % 24 (from GetSubstruct
# in pret/pokefirered src/pokemon.c).
GROWTH_POSITION = [0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3]

BADGE_NAMES = (
    "Boulder",
    "Cascade",
    "Thunder",
    "Rainbow",
    "Soul",
    "Marsh",
    "Volcano",
    "Earth",
)
BADGE_FLAGS_START = 0x820
SAVEBLOCK1_FLAGS_OFFSET = 0x0EE0

# Gen 3 western text encoding — subset used in names.
_CHARMAP: dict[int, str] = {0x00: " ", 0xAD: ".", 0xAE: "-", 0xB4: "'", 0xBA: "é"}
_CHARMAP.update({0xA1 + i: str(i) for i in range(10)})
_CHARMAP.update({0xBB + i: chr(ord("A") + i) for i in range(26)})
_CHARMAP.update({0xD5 + i: chr(ord("a") + i) for i in range(26)})


def _decode_text(read_byte: ReadByte, address: int, max_length: int) -> str:
    chars: list[str] = []
    for offset in range(max_length):
        value = read_byte(address + offset)
        if value == 0xFF:  # terminator
            break
        chars.append(_CHARMAP.get(value, ""))
    return "".join(chars).strip()


def _u16(read_byte: ReadByte, address: int) -> int:
    return read_byte(address) | (read_byte(address + 1) << 8)


def _u32(read_byte: ReadByte, address: int) -> int:
    return (
        read_byte(address)
        | (read_byte(address + 1) << 8)
        | (read_byte(address + 2) << 16)
        | (read_byte(address + 3) << 24)
    )


def _status_condition(status_word: int) -> str | None:
    if status_word & 0x07:
        return "SLP"
    if status_word & 0x88:  # poison or bad poison
        return "PSN"
    if status_word & 0x10:
        return "BRN"
    if status_word & 0x20:
        return "FRZ"
    if status_word & 0x40:
        return "PAR"
    return None


def _species_name(species_id: int) -> str:
    return DEX_SPECIES_NAMES.get(species_id, f"#{species_id}")


def read_game_status_gen3(symbols: SymbolMap, read_byte: ReadByte) -> dict[str, Any]:
    out: dict[str, Any] = {
        "player_name": None,
        "money": None,
        "map_id": None,
        "map_name": None,
        "badges": [],
        "pokedex_owned": None,
        "pokedex_seen": None,
        "play_time": None,
        "party": [],
        "battle": None,
        "position": None,
        "exits": [],
        "connections": {},
    }

    sb1_ptr_addr = symbols.address("gSaveBlock1Ptr")
    sb2_ptr_addr = symbols.address("gSaveBlock2Ptr")
    sb1 = _u32(read_byte, sb1_ptr_addr) if sb1_ptr_addr is not None else 0
    sb2 = _u32(read_byte, sb2_ptr_addr) if sb2_ptr_addr is not None else 0
    sb1_ok = EWRAM_START <= sb1 < EWRAM_END
    sb2_ok = EWRAM_START <= sb2 < EWRAM_END

    if sb2_ok:
        out["player_name"] = _decode_text(read_byte, sb2, 8) or None
        out["play_time"] = f"{_u16(read_byte, sb2 + 0x0E)}:{read_byte(sb2 + 0x10):02d}"

    if sb1_ok:
        x = _u16(read_byte, sb1)
        y = _u16(read_byte, sb1 + 2)
        map_group = read_byte(sb1 + 4)
        map_num = read_byte(sb1 + 5)
        out["position"] = {"x": x, "y": y}
        map_id = (map_group << 8) | map_num
        out["map_id"] = map_id
        out["map_name"] = FIRERED_MAP_NAMES.get(map_id, f"Map {map_group}.{map_num}")
        # Warp tiles (doors/stairs) and outdoor connections, mined from the FRLG maps —
        # the navigation aid the agent relies on (surfaced as EXITS/CONNECTIONS).
        out["exits"] = [
            {
                "x": x,
                "y": y,
                "to": FIRERED_MAP_NAMES.get(dest, f"map {dest}") if dest is not None else "outside",
            }
            for x, y, dest in (FIRERED_MAP_WARPS.get(map_id) or [])
        ]
        out["connections"] = {
            direction: FIRERED_MAP_NAMES.get(dest, f"map {dest}")
            for direction, dest in (FIRERED_MAP_CONNECTIONS.get(map_id) or {}).items()
        }
        if sb2_ok:
            key = _u32(read_byte, sb2 + 0xF20)
            out["money"] = _u32(read_byte, sb1 + 0x290) ^ key
        badges = []
        for index, name in enumerate(BADGE_NAMES):
            flag = BADGE_FLAGS_START + index
            byte = read_byte(sb1 + SAVEBLOCK1_FLAGS_OFFSET + (flag >> 3))
            if byte & (1 << (flag & 7)):
                badges.append(name)
        out["badges"] = badges

    out["party"] = _read_party(symbols, read_byte)
    return out


def _read_party(symbols: SymbolMap, read_byte: ReadByte) -> list[dict[str, Any]]:
    count_addr = symbols.address("gPlayerPartyCount")
    base_addr = symbols.address("gPlayerParty")
    if count_addr is None or base_addr is None:
        return []
    count = min(read_byte(count_addr), 6)
    party: list[dict[str, Any]] = []
    for slot in range(count):
        mon = base_addr + slot * PARTY_MON_SIZE
        personality = _u32(read_byte, mon)
        ot_id = _u32(read_byte, mon + 4)
        key = personality ^ ot_id
        growth_offset = 32 + GROWTH_POSITION[personality % 24] * 12
        species_id = (_u32(read_byte, mon + growth_offset) ^ key) & 0xFFFF
        nickname = _decode_text(read_byte, mon + 8, 10)
        status_word = _u32(read_byte, mon + 80)
        level = read_byte(mon + 84)
        hp = _u16(read_byte, mon + 86)
        max_hp = _u16(read_byte, mon + 88)
        species = _species_name(species_id)
        party.append(
            {
                "slot": slot + 1,
                "species": species,
                "nickname": nickname or species,
                "level": level,
                "hp": hp,
                "max_hp": max_hp,
                "status": _status_condition(status_word),
            }
        )
    return party
