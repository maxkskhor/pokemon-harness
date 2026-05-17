from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from env.app import create_app
from env.harness_registry import HarnessRegistry
from env.emulator import FakeEmulator
from env.trace import TraceStore


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


def test_save_state_writes_agent_sidecar_and_load_state_returns_it(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)

    save = client.post(
        "/api/save-state",
        json={"name": "withhistory", "agent_state": {"history": ["a", "b"]}},
    ).json()
    assert save["has_agent_state"] is True

    load = client.post("/api/load-state", json={"name": "withhistory"}).json()

    assert load["agent_state"] == {"history": ["a", "b"]}


def test_load_state_returns_null_agent_state_when_no_sidecar(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    client.post("/api/save-state", json={"name": "plain"})  # no agent_state

    load = client.post("/api/load-state", json={"name": "plain"}).json()

    assert load["agent_state"] is None


def test_load_state_pushes_load_command_to_running_harness(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    client.post(
        "/api/save-state",
        json={"name": "ckpt", "agent_state": {"history": ["m"]}},
    )
    registered = client.post("/api/harness/register", json={"name": "Listener"}).json()
    harness_id = registered["id"]
    client.post(f"/api/harness/{harness_id}/play")  # status -> "running"
    # Clear the "play" command so we only see the load_state push.
    client.get(f"/api/harness/{harness_id}/poll")

    client.post("/api/load-state", json={"name": "ckpt"})

    assert client.get(f"/api/harness/{harness_id}/poll").json() == {"command": "load_state:ckpt"}


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


def test_harness_registry_queues_commands_fifo() -> None:
    registry = HarnessRegistry()
    harness_id = registry.register("Queue Agent")

    registry.enqueue(harness_id, "play")
    registry.enqueue(harness_id, "stop")

    assert registry.poll(harness_id) == "play"
    assert registry.poll(harness_id) == "stop"
    assert registry.poll(harness_id) is None


def test_harness_poll_preserves_rapid_play_stop(client: TestClient) -> None:
    registered = client.post("/api/harness/register", json={"name": "Smoke Agent"}).json()
    harness_id = registered["id"]

    assert client.post(f"/api/harness/{harness_id}/play").status_code == 200
    assert client.post(f"/api/harness/{harness_id}/stop").status_code == 200

    assert client.get(f"/api/harness/{harness_id}/poll").json() == {"command": "play"}
    assert client.get(f"/api/harness/{harness_id}/poll").json() == {"command": "stop"}
    assert client.get(f"/api/harness/{harness_id}/poll").json() == {"command": None}


def test_harness_control_ws_delivers_queued_commands_in_order(client: TestClient) -> None:
    registered = client.post("/api/harness/register", json={"name": "WS Agent"}).json()
    harness_id = registered["id"]

    # Enqueue before WS connects — drain-on-connect must deliver these.
    assert client.post(f"/api/harness/{harness_id}/play").status_code == 200
    assert client.post(f"/api/harness/{harness_id}/stop").status_code == 200

    with client.websocket_connect(f"/api/harness/{harness_id}/control") as ws:
        assert ws.receive_json() == {"command": "play"}
        assert ws.receive_json() == {"command": "stop"}


def test_harness_control_ws_pushes_commands_enqueued_after_connect(client: TestClient) -> None:
    registered = client.post("/api/harness/register", json={"name": "WS Agent"}).json()
    harness_id = registered["id"]

    with client.websocket_connect(f"/api/harness/{harness_id}/control") as ws:
        # Enqueue while connected — must be pushed within the server-side poll interval.
        client.post(f"/api/harness/{harness_id}/play")
        assert ws.receive_json() == {"command": "play"}


def test_harness_control_ws_closes_for_unknown_id(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/api/harness/does-not-exist/control") as ws:
            ws.receive_json()
        raise AssertionError("expected the WS to be closed for an unknown harness id")
    except WebSocketDisconnect as exc:
        assert exc.code == 4404


def test_state_screen_hash_is_cached_until_frame_changes(tmp_path: Path, fake_rom: Path, fake_sym: Path) -> None:
    class CountingFakeEmulator(FakeEmulator):
        def __init__(self, rom_path: Path | None = None, sym_path: Path | None = None):
            super().__init__(rom_path, sym_path)
            self.screenshot_calls = 0

        def screenshot_png(self) -> bytes:
            self.screenshot_calls += 1
            return super().screenshot_png()

    app = create_app(
        emulator_factory=CountingFakeEmulator,
        trace_store=TraceStore(tmp_path / "runs"),
        states_dir=tmp_path / "states",
    )
    with TestClient(app) as local_client:
        start_fake_run(local_client, fake_rom, fake_sym)
        session = app.state.manager.session
        assert session is not None
        emulator = session.emulator

        local_client.get("/api/state")
        local_client.get("/api/state")
        assert emulator.screenshot_calls == 1

        local_client.post("/api/step", json={"frames": 1})
        local_client.get("/api/state")
        assert emulator.screenshot_calls == 2


def test_frame_thumbnails_persist_and_serve(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    press = client.post("/api/action/press", json={"button": "RIGHT", "frames": 8}).json()
    frame = press["frame"]

    response = client.get(f"/api/runs/test-run/frames/{frame}.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_frame_thumbnails_404_for_unknown_frame(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)

    response = client.get("/api/runs/test-run/frames/99999.png")

    assert response.status_code == 404


def test_frame_thumbnails_dedup_by_frame(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    # Multiple env events at the same emulator frame must share one PNG.
    start_fake_run(client, fake_rom, fake_sym)  # emits run_started at frame 0
    client.post("/api/speed", json={"mode": "paused"})  # emits speed_changed at frame 0

    session = client.app.state.manager.session  # type: ignore[attr-defined]
    assert session is not None
    frames_dir = session.trace_store.run_dir("test-run") / "frames"
    pngs = sorted(p.name for p in frames_dir.iterdir() if p.suffix == ".png")
    assert pngs == ["0.png"]


def test_list_runs_marks_active_run(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    client.post("/api/action/press", json={"button": "RIGHT", "frames": 8})

    runs = client.get("/api/runs").json()

    assert len(runs) >= 1
    active = next((r for r in runs if r["run_id"] == "test-run"), None)
    assert active is not None
    assert active["active"] is True
    assert active["has_env"] is True
    assert active["bytes"] > 0


def test_list_runs_sorted_newest_first(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    # Two runs, second is newer.
    start_fake_run(client, fake_rom, fake_sym, run_id="run-old")
    client.post("/api/run/stop")
    start_fake_run(client, fake_rom, fake_sym, run_id="run-new")

    runs = client.get("/api/runs").json()
    ordered_ids = [r["run_id"] for r in runs]

    assert ordered_ids.index("run-new") < ordered_ids.index("run-old")


def test_list_run_states_includes_frame_from_trace(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    client.post("/api/action/press", json={"button": "RIGHT", "frames": 8})
    save = client.post("/api/save-state", json={"name": "after_right"}).json()

    listed = client.get("/api/runs/test-run/states").json()

    assert len(listed) == 1
    entry = listed[0]
    assert entry["name"] == "after_right"
    assert entry["size"] > 0
    assert entry["modified_at"]
    assert entry["frame"] == save["frame"]


def test_list_run_states_newest_first(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    client.post("/api/save-state", json={"name": "first"})
    client.post("/api/action/press", json={"button": "RIGHT", "frames": 8})
    client.post("/api/save-state", json={"name": "second"})

    listed = client.get("/api/runs/test-run/states").json()

    assert [entry["name"] for entry in listed] == ["second", "first"]


def test_list_shared_states(client: TestClient, tmp_path: Path, fake_rom: Path, fake_sym: Path) -> None:
    shared = client.app.state.manager.states_dir / "shared"  # type: ignore[attr-defined]
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "bedroom.state").write_bytes(b"x")

    listed = client.get("/api/states/shared").json()

    assert any(entry["name"] == "bedroom" for entry in listed)


def test_delete_state(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    client.post("/api/save-state", json={"name": "doomed"})

    listed = client.get("/api/runs/test-run/states").json()
    assert any(entry["name"] == "doomed" for entry in listed)

    response = client.delete("/api/runs/test-run/states/doomed")

    assert response.status_code == 200
    listed = client.get("/api/runs/test-run/states").json()
    assert not any(entry["name"] == "doomed" for entry in listed)


def test_delete_state_rejects_traversal(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)

    # The path param ".." cannot match the validator's safe alphabet.
    response = client.delete("/api/runs/test-run/states/..%2Fbedroom")

    assert response.status_code in (404, 422)


def test_reset_run_clears_frame_thumbnails(client: TestClient, fake_rom: Path, fake_sym: Path) -> None:
    start_fake_run(client, fake_rom, fake_sym)
    press_frame = client.post("/api/action/press", json={"button": "RIGHT", "frames": 8}).json()["frame"]

    session = client.app.state.manager.session  # type: ignore[attr-defined]
    assert session is not None
    frames_dir = session.trace_store.run_dir("test-run") / "frames"
    assert (frames_dir / f"{press_frame}.png").exists()

    # Reusing the same run_id resets the run; the prior press's PNG must go.
    start_fake_run(client, fake_rom, fake_sym)

    assert not (frames_dir / f"{press_frame}.png").exists()
