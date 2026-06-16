from __future__ import annotations

from env.gamestate_gen3 import read_game_status_gen3
from env.symbols import SymbolMap

SB1 = 0x02025000
SB2 = 0x02024588

_LABELS = {
    "gSaveBlock1Ptr": 0x03005008,
    "gSaveBlock2Ptr": 0x0300500C,
    "gPlayerPartyCount": 0x02024029,
    "gPlayerParty": 0x02024284,
    "gBattleTypeFlags": 0x02022B4C,
    "gBattlersCount": 0x02023BCC,
    "gBattleMons": 0x02023BE4,
    "gBattleOutcome": 0x02023E8A,
}


def _encode_gen3_text(text: str) -> list[int]:
    out: list[int] = []
    for char in text:
        if "A" <= char <= "Z":
            out.append(0xBB + ord(char) - ord("A"))
        elif "a" <= char <= "z":
            out.append(0xD5 + ord(char) - ord("a"))
        else:
            out.append(0x00)
    out.append(0xFF)
    return out


def _build_memory() -> dict[int, int]:
    memory: dict[int, int] = {}

    def write(address: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            memory[address + offset] = value

    def write_u32(address: int, value: int) -> None:
        write(address, [(value >> (8 * i)) & 0xFF for i in range(4)])

    def write_u16(address: int, value: int) -> None:
        write(address, [value & 0xFF, (value >> 8) & 0xFF])

    write_u32(_LABELS["gSaveBlock1Ptr"], SB1)
    write_u32(_LABELS["gSaveBlock2Ptr"], SB2)

    write(SB2, _encode_gen3_text("RED"))             # player name
    write_u16(SB2 + 0x0E, 3)                          # play hours
    memory[SB2 + 0x10] = 42                           # play minutes
    write_u32(SB2 + 0xF20, 0xDEADBEEF)                # encryption key

    write_u16(SB1, 6)                                 # x
    write_u16(SB1 + 2, 7)                             # y
    memory[SB1 + 4] = 4                               # mapGroup (Pallet Town indoor)
    memory[SB1 + 5] = 0                               # mapNum (Players House 1F)
    write_u32(SB1 + 0x290, 3000 ^ 0xDEADBEEF)         # money (encrypted)
    # Badge 1 (Boulder): flag 0x820 -> byte 0x104 bit 0
    memory[SB1 + 0x0EE0 + 0x104] = 0b0000_0001

    memory[_LABELS["gPlayerPartyCount"]] = 1
    mon = _LABELS["gPlayerParty"]
    personality = 7                                   # 7 % 24 = 7 -> growth block index 1
    ot_id = 0x12345678
    key = personality ^ ot_id
    write_u32(mon, personality)
    write_u32(mon + 4, ot_id)
    write(mon + 8, _encode_gen3_text("SPARKY"))       # nickname
    growth = mon + 32 + 1 * 12
    write_u32(growth, (25 | (42 << 16)) ^ key)        # species Pikachu (+ held item junk)
    write_u32(mon + 80, 0x40)                         # status: PAR
    memory[mon + 84] = 12                             # level
    write_u16(mon + 86, 19)                           # hp
    write_u16(mon + 88, 33)                           # max hp
    return memory


def test_read_game_status_gen3() -> None:
    memory = _build_memory()
    symbols = SymbolMap(labels=dict(_LABELS))

    status = read_game_status_gen3(symbols, lambda address: memory.get(address, 0))

    assert status["player_name"] == "RED"
    assert status["play_time"] == "3:42"
    assert status["money"] == 3000
    assert status["map_name"] == "Pallet Town Players House 1F"
    assert status["position"] == {"x": 6, "y": 7}
    assert status["badges"] == ["Boulder"]

    assert len(status["party"]) == 1
    mon = status["party"][0]
    assert mon["species"] == "Pikachu"
    assert mon["nickname"] == "SPARKY"
    assert mon["level"] == 12
    assert mon["hp"] == 19
    assert mon["max_hp"] == 33
    assert mon["status"] == "PAR"
    assert status["battle"] is None


def test_read_game_status_gen3_battle() -> None:
    memory = _build_memory()

    def write(address: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            memory[address + offset] = value

    def write_u16(address: int, value: int) -> None:
        write(address, [value & 0xFF, (value >> 8) & 0xFF])

    def write_u32(address: int, value: int) -> None:
        write(address, [(value >> (8 * i)) & 0xFF for i in range(4)])

    write_u32(_LABELS["gBattleTypeFlags"], 1 << 2)  # in a non-trainer battle
    memory[_LABELS["gBattlersCount"]] = 2
    mine = _LABELS["gBattleMons"]
    enemy = mine + 0x58
    write_u16(mine, 7)          # Squirtle
    write_u16(mine + 0x0C, 33)  # Tackle
    write_u16(mine + 0x0E, 39)  # Tail Whip
    memory[mine + 0x24] = 35
    memory[mine + 0x25] = 30
    write_u16(mine + 0x28, 18)
    memory[mine + 0x2A] = 6
    write_u16(mine + 0x2C, 21)

    write_u16(enemy, 16)        # Pidgey
    write_u16(enemy + 0x0C, 33)
    memory[enemy + 0x24] = 35
    write_u16(enemy + 0x28, 8)
    memory[enemy + 0x2A] = 2
    write_u16(enemy + 0x2C, 11)

    status = read_game_status_gen3(SymbolMap(labels=dict(_LABELS)), lambda address: memory.get(address, 0))

    battle = status["battle"]
    assert battle is not None
    assert battle["kind"] == "wild"
    assert battle["enemy_species"] == "Pidgey"
    assert battle["enemy_level"] == 2
    assert battle["enemy_hp"] == 8
    assert battle["enemy_max_hp"] == 11
    assert battle["my"]["species"] == "Squirtle"
    assert battle["my"]["hp"] == 18
    assert battle["my"]["moves"] == [
        {"slot": 1, "name": "Tackle", "pp": 35},
        {"slot": 2, "name": "Tail Whip", "pp": 30},
    ]


def test_read_game_status_gen3_ignores_stale_defeated_battle_struct() -> None:
    memory = _build_memory()

    def write(address: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            memory[address + offset] = value

    def write_u16(address: int, value: int) -> None:
        write(address, [value & 0xFF, (value >> 8) & 0xFF])

    def write_u32(address: int, value: int) -> None:
        write(address, [(value >> (8 * i)) & 0xFF for i in range(4)])

    # Looks like a leftover rival battle: enemy already defeated, but lead-party HP
    # has been restored/synced to overworld save data and no longer matches gBattleMons.
    write_u32(_LABELS["gBattleTypeFlags"], 1 << 3)
    memory[_LABELS["gBattlersCount"]] = 2
    mine = _LABELS["gBattleMons"]
    enemy = mine + 0x58
    write_u16(mine, 7)
    memory[mine + 0x2A] = 6
    write_u16(mine + 0x28, 9)
    write_u16(mine + 0x2C, 21)
    write_u16(enemy, 1)
    memory[enemy + 0x2A] = 5
    write_u16(enemy + 0x28, 0)
    write_u16(enemy + 0x2C, 19)

    status = read_game_status_gen3(SymbolMap(labels=dict(_LABELS)), lambda address: memory.get(address, 0))

    assert status["party"][0]["hp"] == 19
    assert status["battle"] is None


def test_read_game_status_gen3_ignores_resolved_battle_outcome() -> None:
    memory = _build_memory()

    def write(address: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            memory[address + offset] = value

    def write_u16(address: int, value: int) -> None:
        write(address, [value & 0xFF, (value >> 8) & 0xFF])

    def write_u32(address: int, value: int) -> None:
        write(address, [(value >> (8 * i)) & 0xFF for i in range(4)])

    write_u32(_LABELS["gBattleTypeFlags"], 1 << 2)
    memory[_LABELS["gBattlersCount"]] = 2
    memory[_LABELS["gBattleOutcome"]] = 1  # B_OUTCOME_WON
    mine = _LABELS["gBattleMons"]
    enemy = mine + 0x58
    write_u16(mine, 7)
    memory[mine + 0x2A] = 6
    write_u16(mine + 0x28, 12)
    write_u16(mine + 0x2C, 21)
    write_u16(enemy, 16)
    memory[enemy + 0x2A] = 3
    write_u16(enemy + 0x28, 0)
    write_u16(enemy + 0x2C, 16)

    status = read_game_status_gen3(SymbolMap(labels=dict(_LABELS)), lambda address: memory.get(address, 0))

    assert status["battle"] is None


def test_read_game_status_gen3_unloaded_saveblocks() -> None:
    symbols = SymbolMap(labels=dict(_LABELS))
    status = read_game_status_gen3(symbols, lambda address: 0)
    assert status["player_name"] is None
    assert status["money"] is None
    assert status["party"] == []
