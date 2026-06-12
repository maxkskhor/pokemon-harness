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


def test_read_game_status_gen3_unloaded_saveblocks() -> None:
    symbols = SymbolMap(labels=dict(_LABELS))
    status = read_game_status_gen3(symbols, lambda address: 0)
    assert status["player_name"] is None
    assert status["money"] is None
    assert status["party"] == []
