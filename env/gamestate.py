"""Rich Pokemon Red/Blue game-state reader.

Builds on the .sym label map: every address is looked up by label, so this works
for any ROM built from the pret/pokered disassembly (Red, Blue) without
hardcoded addresses.
"""
from __future__ import annotations

from typing import Any, Callable

from env.pokered_names import MAP_NAMES, SPECIES_NAMES
from env.symbols import SymbolMap

ReadByte = Callable[[int], int]

PARTY_MON_SIZE = 44
NAME_LENGTH = 11

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

# Gen 1 text encoding — the subset that appears in names.
_CHARMAP: dict[int, str] = {0x50: "", 0x7F: " ", 0xBA: "é", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: "."}
_CHARMAP.update({0x80 + i: chr(ord("A") + i) for i in range(26)})
_CHARMAP.update({0xA0 + i: chr(ord("a") + i) for i in range(26)})
_CHARMAP.update({0xF6 + i: str(i) for i in range(10)})


def _decode_text(read_byte: ReadByte, address: int, max_length: int) -> str:
    chars: list[str] = []
    for offset in range(max_length):
        value = read_byte(address + offset)
        if value == 0x50:  # terminator
            break
        chars.append(_CHARMAP.get(value, ""))
    return "".join(chars).strip()


def _read_u16_be(read_byte: ReadByte, address: int) -> int:
    return (read_byte(address) << 8) | read_byte(address + 1)


def _read_bcd(read_byte: ReadByte, address: int, length: int) -> int:
    total = 0
    for offset in range(length):
        value = read_byte(address + offset)
        total = total * 100 + ((value >> 4) * 10 + (value & 0x0F))
    return total


def _status_condition(status_byte: int) -> str | None:
    if status_byte & 0x07:
        return "SLP"
    if status_byte & 0x08:
        return "PSN"
    if status_byte & 0x10:
        return "BRN"
    if status_byte & 0x20:
        return "FRZ"
    if status_byte & 0x40:
        return "PAR"
    return None


def _bit_count(read_byte: ReadByte, address: int, length: int) -> int:
    return sum(bin(read_byte(address + offset)).count("1") for offset in range(length))


def read_game_status(symbols: SymbolMap, read_byte: ReadByte) -> dict[str, Any]:
    """Read a human-oriented status snapshot: trainer, party, badges, battle."""

    def addr(*names: str) -> int | None:
        return symbols.address(*names)

    out: dict[str, Any] = {}

    name_addr = addr("wPlayerName")
    out["player_name"] = _decode_text(read_byte, name_addr, NAME_LENGTH) if name_addr is not None else None

    money_addr = addr("wPlayerMoney")
    out["money"] = _read_bcd(read_byte, money_addr, 3) if money_addr is not None else None

    map_addr = addr("wCurMap")
    map_id = read_byte(map_addr) if map_addr is not None else None
    out["map_id"] = map_id
    out["map_name"] = MAP_NAMES.get(map_id) if map_id is not None else None

    badges_addr = addr("wObtainedBadges")
    if badges_addr is not None:
        bits = read_byte(badges_addr)
        out["badges"] = [name for index, name in enumerate(BADGE_NAMES) if bits & (1 << index)]
    else:
        out["badges"] = []

    owned_addr = addr("wPokedexOwned")
    seen_addr = addr("wPokedexSeen")
    out["pokedex_owned"] = _bit_count(read_byte, owned_addr, 19) if owned_addr is not None else None
    out["pokedex_seen"] = _bit_count(read_byte, seen_addr, 19) if seen_addr is not None else None

    hours_addr = addr("wPlayTimeHours")
    minutes_addr = addr("wPlayTimeMinutes")
    if hours_addr is not None and minutes_addr is not None:
        out["play_time"] = f"{read_byte(hours_addr)}:{read_byte(minutes_addr):02d}"
    else:
        out["play_time"] = None

    out["party"] = _read_party(symbols, read_byte)
    out["battle"] = _read_battle(symbols, read_byte)
    return out


def _read_party(symbols: SymbolMap, read_byte: ReadByte) -> list[dict[str, Any]]:
    count_addr = symbols.address("wPartyCount")
    base_addr = symbols.address("wPartyMon1")
    if count_addr is None or base_addr is None:
        return []
    count = min(read_byte(count_addr), 6)
    nicks_addr = symbols.address("wPartyMonNicks")
    party: list[dict[str, Any]] = []
    for slot in range(count):
        mon = base_addr + slot * PARTY_MON_SIZE
        species_id = read_byte(mon)
        hp = _read_u16_be(read_byte, mon + 1)
        status_byte = read_byte(mon + 4)
        level = read_byte(mon + 33)
        max_hp = _read_u16_be(read_byte, mon + 34)
        nickname = (
            _decode_text(read_byte, nicks_addr + slot * NAME_LENGTH, NAME_LENGTH)
            if nicks_addr is not None
            else ""
        )
        species = SPECIES_NAMES.get(species_id, f"#{species_id}")
        party.append(
            {
                "slot": slot + 1,
                "species": species,
                "nickname": nickname or species,
                "level": level,
                "hp": hp,
                "max_hp": max_hp,
                "status": _status_condition(status_byte),
            }
        )
    return party


def _read_battle(symbols: SymbolMap, read_byte: ReadByte) -> dict[str, Any] | None:
    in_battle_addr = symbols.address("wIsInBattle")
    if in_battle_addr is None:
        return None
    battle_type = read_byte(in_battle_addr)
    if battle_type == 0:
        return None
    species_addr = symbols.address("wEnemyMonSpecies")
    hp_addr = symbols.address("wEnemyMonHP")
    level_addr = symbols.address("wEnemyMonLevel")
    enemy_species = read_byte(species_addr) if species_addr is not None else None
    return {
        "kind": "trainer" if battle_type == 2 else "wild",
        "enemy_species": SPECIES_NAMES.get(enemy_species, f"#{enemy_species}") if enemy_species else None,
        "enemy_level": read_byte(level_addr) if level_addr is not None else None,
        "enemy_hp": _read_u16_be(read_byte, hp_addr) if hp_addr is not None else None,
    }
