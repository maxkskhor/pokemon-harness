from __future__ import annotations

from pathlib import Path

from env.symbols import parse_sym_file, read_pokemon_labels


def test_symbol_parser_reads_pokemon_labels(fake_sym: Path) -> None:
    symbols = parse_sym_file(fake_sym)
    values = {
        0xD35E: 1,
        0xD361: 6,
        0xD362: 3,
        0xD163: 0,
    }

    labels = read_pokemon_labels(symbols, lambda address: values[address])

    assert labels["map_id"] == 1
    assert labels["y"] == 6
    assert labels["x"] == 3
    assert labels["party_count"] == 0

