from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from env.app import create_app
from env.paths import PROJECT_ROOT
from env.trace import TraceStore


ROM_PATH = PROJECT_ROOT / "roms" / "pokered.gbc"
SYM_PATH = PROJECT_ROOT / "roms" / "pokered.sym"


@pytest.mark.skipif(not ROM_PATH.exists(), reason="roms/pokered.gbc is generated locally by scripts/setup_pokered.sh")
def test_real_pokered_rom_loads_and_advances(tmp_path: Path) -> None:
    app = create_app(trace_store=TraceStore(tmp_path / "runs"), states_dir=tmp_path / "states")
    with TestClient(app) as client:
        started = client.post(
            "/api/run/start",
            json={"run_id": "real-rom-test", "rom_path": str(ROM_PATH), "sym_path": str(SYM_PATH)},
        )
        assert started.status_code == 200, started.text
        first_hash = started.json()["screen"]["sha256"]

        advanced = client.post("/api/step", json={"frames": 1600})
        assert advanced.status_code == 200, advanced.text

        state = advanced.json()
        assert state["frame"] == 1600
        assert state["rom"]["title"] == "POKEMON RED"
        assert state["screen"]["sha256"] != first_hash

        screenshot = client.get("/api/screenshot.png")
        assert screenshot.status_code == 200
        assert screenshot.content.startswith(b"\x89PNG")

