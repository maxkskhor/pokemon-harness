from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from env.app import create_app
from env.emulator import FakeEmulator
from env.trace import TraceStore


@pytest.fixture()
def fake_rom(tmp_path: Path) -> Path:
    rom = tmp_path / "pokered.gbc"
    data = bytearray(0x200)
    data[0x134:0x134 + len(b"POKEMON RED")] = b"POKEMON RED"
    rom.write_bytes(data)
    return rom


@pytest.fixture()
def fake_sym(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "pokered.sym"
    target = tmp_path / "pokered.sym"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        emulator_factory=FakeEmulator,
        trace_store=TraceStore(tmp_path / "runs"),
        states_dir=tmp_path / "states",
    )
    with TestClient(app) as test_client:
        yield test_client

