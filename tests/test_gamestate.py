from __future__ import annotations

from env.gamestate import read_game_status
from env.symbols import SymbolMap


def _encode_text(text: str) -> list[int]:
    out: list[int] = []
    for char in text:
        if "A" <= char <= "Z":
            out.append(0x80 + ord(char) - ord("A"))
        elif "a" <= char <= "z":
            out.append(0xA0 + ord(char) - ord("a"))
        else:
            out.append(0x7F)
    out.append(0x50)  # terminator
    return out


def _build_memory() -> dict[int, int]:
    memory: dict[int, int] = {}

    def write(address: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            memory[address + offset] = value

    write(0xD158, _encode_text("RED"))            # wPlayerName
    write(0xD347, [0x01, 0x23, 0x45])             # wPlayerMoney BCD -> 12345
    memory[0xD35E] = 38                            # wCurMap -> Reds House 2F
    memory[0xD356] = 0b0000_0011                   # wObtainedBadges -> Boulder, Cascade
    write(0xD2F7, [0b0000_0111] + [0] * 18)        # wPokedexOwned -> 3
    write(0xD30A, [0b1111_1111] + [0] * 18)        # wPokedexSeen -> 8
    memory[0xDA41] = 2                             # wPlayTimeHours
    memory[0xDA43] = 7                             # wPlayTimeMinutes

    memory[0xD163] = 1                             # wPartyCount
    mon = 0xD16B                                   # wPartyMon1
    memory[mon] = 0xB0                             # species: Charmander (internal $B0)
    memory[mon + 1], memory[mon + 2] = 0, 17       # HP = 17
    memory[mon + 4] = 0x08                         # status: PSN
    memory[mon + 8] = 33                           # move 1: Tackle
    memory[mon + 9] = 45                           # move 2: Growl
    memory[mon + 29] = 35                          # pp 1
    memory[mon + 30] = (1 << 6) | 40               # pp 2 with one PP-Up bit set
    memory[mon + 33] = 9                           # level
    memory[mon + 34], memory[mon + 35] = 0, 27     # max HP = 27
    write(0xD2B5, _encode_text("FLAME"))           # wPartyMonNicks slot 1

    memory[0xD057] = 1                             # wIsInBattle -> wild
    memory[0xCFE5] = 0xA5                          # wEnemyMonSpecies
    memory[0xCFF3] = 5                             # wEnemyMonLevel
    memory[0xCFE6], memory[0xCFE7] = 0, 11         # wEnemyMonHP = 11
    memory[0xCFF4], memory[0xCFF5] = 0, 16         # wEnemyMonMaxHP = 16

    memory[0xD014] = 0xB0                          # wBattleMon species: Charmander
    memory[0xD015], memory[0xD016] = 0, 17         # wBattleMonHP
    memory[0xD01C] = 10                            # wBattleMonMoves: Scratch
    memory[0xD022] = 9                             # wBattleMonLevel
    memory[0xD023], memory[0xD024] = 0, 27         # wBattleMonMaxHP
    memory[0xD02D] = 30                            # wBattleMonPP slot 1

    return memory


_LABELS = {
    "wPlayerName": 0xD158,
    "wPlayerMoney": 0xD347,
    "wCurMap": 0xD35E,
    "wObtainedBadges": 0xD356,
    "wPokedexOwned": 0xD2F7,
    "wPokedexSeen": 0xD30A,
    "wPlayTimeHours": 0xDA41,
    "wPlayTimeMinutes": 0xDA43,
    "wPartyCount": 0xD163,
    "wPartyMon1": 0xD16B,
    "wPartyMonNicks": 0xD2B5,
    "wIsInBattle": 0xD057,
    "wEnemyMonSpecies": 0xCFE5,
    "wEnemyMonLevel": 0xCFF3,
    "wEnemyMonHP": 0xCFE6,
    "wEnemyMonMaxHP": 0xCFF4,
    "wBattleMon": 0xD014,
    "wBattleMonHP": 0xD015,
    "wBattleMonMoves": 0xD01C,
    "wBattleMonLevel": 0xD022,
    "wBattleMonMaxHP": 0xD023,
    "wBattleMonPP": 0xD02D,
}


def test_read_game_status_full_snapshot() -> None:
    memory = _build_memory()
    symbols = SymbolMap(labels=dict(_LABELS))

    status = read_game_status(symbols, lambda address: memory.get(address, 0))

    assert status["player_name"] == "RED"
    assert status["money"] == 12345
    assert status["map_id"] == 38
    assert status["map_name"] == "Reds House 2F"
    assert status["badges"] == ["Boulder", "Cascade"]
    assert status["pokedex_owned"] == 3
    assert status["pokedex_seen"] == 8
    assert status["play_time"] == "2:07"

    assert len(status["party"]) == 1
    mon = status["party"][0]
    assert mon["species"] == "Charmander"
    assert mon["nickname"] == "FLAME"
    assert mon["level"] == 9
    assert mon["hp"] == 17
    assert mon["max_hp"] == 27
    assert mon["status"] == "PSN"
    assert mon["moves"] == [
        {"slot": 1, "name": "Tackle", "pp": 35},
        {"slot": 2, "name": "Growl", "pp": 40},
    ]

    battle = status["battle"]
    assert battle is not None
    assert battle["kind"] == "wild"
    assert battle["enemy_level"] == 5
    assert battle["enemy_hp"] == 11
    assert battle["enemy_max_hp"] == 16
    assert battle["my"]["species"] == "Charmander"
    assert battle["my"]["hp"] == 17
    assert battle["my"]["moves"] == [{"slot": 1, "name": "Scratch", "pp": 30}]


def test_read_game_status_no_party_no_battle() -> None:
    symbols = SymbolMap(labels=dict(_LABELS))
    status = read_game_status(symbols, lambda address: 0)
    assert status["party"] == []
    assert status["battle"] is None
    assert status["badges"] == []
    assert status["money"] == 0
