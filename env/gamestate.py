"""Rich Pokemon Red/Blue game-state reader.

Builds on the .sym label map: every address is looked up by label, so this works
for any ROM built from the pret/pokered disassembly (Red, Blue) without
hardcoded addresses.
"""
from __future__ import annotations

from typing import Any, Callable

from env.pokered_names import MAP_CONNECTIONS, MAP_NAMES, MAP_WARPS, MOVE_NAMES, SPECIES_NAMES
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


def _read_moves(read_byte: ReadByte, moves_addr: int, pp_addr: int) -> list[dict[str, Any]]:
    """Four move slots: id list + PP list (top 2 PP bits are PP-Up count)."""
    moves: list[dict[str, Any]] = []
    for slot in range(4):
        move_id = read_byte(moves_addr + slot)
        if move_id == 0:
            continue
        moves.append(
            {
                "slot": slot + 1,
                "name": MOVE_NAMES.get(move_id, f"#{move_id}"),
                "pp": read_byte(pp_addr + slot) & 0x3F,
            }
        )
    return moves


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
    # Static map knowledge mined from the disassembly: warp tiles (doors,
    # stairs, mats) and outdoor edge connections. Gold for navigation.
    out["exits"] = [
        {
            "x": x,
            "y": y,
            "to": MAP_NAMES.get(dest, f"map {dest}") if dest is not None else "outside",
        }
        for x, y, dest in (MAP_WARPS.get(map_id) or [])
    ] if map_id is not None else []
    out["connections"] = (
        {
            direction: MAP_NAMES.get(dest, f"map {dest}")
            for direction, dest in (MAP_CONNECTIONS.get(map_id) or {}).items()
        }
        if map_id is not None
        else {}
    )

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
                "moves": _read_moves(read_byte, mon + 8, mon + 29),
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

    def byte_at(label: str) -> int | None:
        address = symbols.address(label)
        return read_byte(address) if address is not None else None

    def u16_at(label: str) -> int | None:
        address = symbols.address(label)
        return _read_u16_be(read_byte, address) if address is not None else None

    enemy_species = byte_at("wEnemyMonSpecies")
    out: dict[str, Any] = {
        "kind": "trainer" if battle_type == 2 else "wild",
        "enemy_species": SPECIES_NAMES.get(enemy_species, f"#{enemy_species}") if enemy_species else None,
        "enemy_level": byte_at("wEnemyMonLevel"),
        "enemy_hp": u16_at("wEnemyMonHP"),
        "enemy_max_hp": u16_at("wEnemyMonMaxHP"),
    }
    # My active battle mon (wBattleMon mirrors the party mon while fighting).
    my_species = byte_at("wBattleMon")
    moves_addr = symbols.address("wBattleMonMoves")
    pp_addr = symbols.address("wBattleMonPP")
    if my_species:
        out["my"] = {
            "species": SPECIES_NAMES.get(my_species, f"#{my_species}"),
            "level": byte_at("wBattleMonLevel"),
            "hp": u16_at("wBattleMonHP"),
            "max_hp": u16_at("wBattleMonMaxHP"),
            "moves": (
                _read_moves(read_byte, moves_addr, pp_addr)
                if moves_addr is not None and pp_addr is not None
                else []
            ),
        }
    return out
