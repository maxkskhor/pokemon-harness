from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def start_fake_run(client: TestClient, fake_rom: Path, fake_sym: Path, run_id: str = "test-run") -> dict:
    response = client.post(
        "/api/run/start",
        json={"run_id": run_id, "rom_path": str(fake_rom), "sym_path": str(fake_sym)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_invalid_button_rejected(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)

    response = client.post("/api/action/press", json={"button": "NOPE", "frames": 8})

    assert response.status_code == 422


def test_state_and_screenshot(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    state = start_fake_run(client, fake_rom, fake_sym)

    assert state["running"] is True
    assert state["rom"]["title"] == "POKEMON RED"
    assert state["pokemon"]["x"] == 3
    assert state["pokemon"]["y"] == 6

    screenshot = client.get("/api/screenshot.png")

    assert screenshot.status_code == 200
    assert screenshot.headers["content-type"] == "image/png"
    assert screenshot.content.startswith(b"\x89PNG")


def test_trace_separation(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)

    client.post("/api/action/press", json={"button": "RIGHT", "frames": 8})
    client.post(
        "/api/harness/event",
        json={"type": "tool_call", "turn_id": "turn-001", "payload": {"tool": "press_button"}},
    )

    env_trace = client.get("/api/runs/test-run/env-trace").json()
    harness_trace = client.get("/api/runs/test-run/harness-trace").json()

    assert any(event["type"] == "button_press" for event in env_trace)
    assert all(event["source"] == "env" for event in env_trace)
    assert any(event["type"] == "tool_call" for event in harness_trace)
    assert all(event["source"] == "harness" for event in harness_trace)


def test_save_load_restores_fake_state(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    baseline = start_fake_run(client, fake_rom, fake_sym)

    save = client.post("/api/save-state", json={"name": "baseline"})
    assert save.status_code == 200

    moved = client.post("/api/action/press", json={"button": "RIGHT", "frames": 8}).json()
    assert moved["pokemon"]["x"] == baseline["pokemon"]["x"] + 1

    restored = client.post("/api/load-state", json={"name": "baseline"}).json()
    assert restored["pokemon"]["x"] == baseline["pokemon"]["x"]
    assert restored["pokemon"]["y"] == baseline["pokemon"]["y"]


def test_websocket_receives_env_and_harness_events(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    with client.websocket_connect("/ws/events") as websocket:
        start_fake_run(client, fake_rom, fake_sym)
        first = websocket.receive_json()
        assert first["source"] == "env"
        assert first["type"] == "run_started"

        response = client.post(
            "/api/harness/event",
            json={"type": "memory_write", "turn_id": "turn-001", "payload": {"key": "goal"}},
        )
        assert response.status_code == 200
        second = websocket.receive_json()
        assert second["source"] == "harness"
        assert second["type"] == "memory_write"


def test_harness_registry_tracks_status_timestamps(client: TestClient) -> None:
    registered = client.post("/api/harness/register", json={"name": "Smoke Agent"}).json()
    harness_id = registered["id"]

    play = client.post(f"/api/harness/{harness_id}/play")
    assert play.status_code == 200

    listed = client.get("/api/harness/list").json()
    agent = next(agent for agent in listed if agent["id"] == harness_id)
    assert agent["status"] == "running"
    assert agent["error"] is None
    assert agent["created_at"]
    assert agent["updated_at"]

    status = client.post(f"/api/harness/{harness_id}/status", json={"status": "starting"})
    assert status.status_code == 200

    invalid = client.post(f"/api/harness/{harness_id}/status", json={"status": "wedged"})
    assert invalid.status_code == 422
