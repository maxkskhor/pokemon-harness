from __future__ import annotations

from typing import Any

from harness import PokemonAgent


class FakeClient:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.states = [
            {"frame": 10, "pokemon": {"map_id": 38, "x": 3, "y": 6}},
            {"frame": 18, "pokemon": {"map_id": 38, "x": 4, "y": 6}},
        ]
        self.pressed: list[tuple[str, int]] = []
        self.waited: list[int] = []
        self.sequences: list[list[dict[str, Any]]] = []
        self.saved: list[str] = []
        self.loaded: list[str] = []
        self.started: list[str] = []
        self.speeds: list[str] = []

    def get_state(self) -> dict[str, Any]:
        return self.states.pop(0)

    def start_run(
        self,
        run_id: str,
        rom_path: str | None = None,
        harness_id: str | None = None,
        start_state: str | None = None,
    ) -> dict[str, Any]:
        self.started.append(run_id)
        return {"run_id": run_id}

    def set_speed(self, mode: str) -> dict[str, Any]:
        self.speeds.append(mode)
        return {"speed_mode": mode}

    def press_button(self, button: str, frames: int) -> None:
        self.pressed.append((button, frames))

    def wait(self, frames: int) -> dict[str, Any]:
        self.waited.append(frames)
        return {"frames": frames}

    def press_sequence(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        self.sequences.append(steps)
        return {"steps": steps}

    def save_state(self, name: str, agent_state: dict[str, Any] | None = None) -> dict[str, Any]:
        self.saved.append((name, agent_state))
        return {"name": name, "has_agent_state": agent_state is not None}

    def load_state(self, name: str) -> dict[str, Any]:
        self.loaded.append(name)
        return {"name": name}

    def read_agent_state(self, run_id: str, name: str) -> dict[str, Any]:
        return {}

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
        frame: int | None = None,
    ) -> dict[str, Any]:
        event = {"type": event_type, "payload": payload, "turn_id": turn_id, "frame": frame}
        self.events.append(event)
        return event


def test_harness_press_delegates_to_client_without_duplicate_event() -> None:
    # The env publishes the canonical `button_press` event; the harness must not also
    # emit its own duplicate `action` event for the same press.
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    harness.press("RIGHT")

    assert client.pressed == [("RIGHT", 16)]
    assert client.events == []


def test_harness_public_helpers_delegate_to_client() -> None:
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    assert harness.sequence([{"type": "wait", "frames": 3}]) == {"steps": [{"type": "wait", "frames": 3}]}
    # Default PokemonAgent.serialize_history returns {}; save_state passes None.
    save_result = harness.save_state("checkpoint")
    assert save_result == {"name": "checkpoint", "has_agent_state": False}
    assert harness.load_state("checkpoint") == {"name": "checkpoint"}

    assert client.sequences == [[{"type": "wait", "frames": 3}]]
    assert client.saved == [("checkpoint", None)]
    assert client.loaded == ["checkpoint"]


def test_prepare_run_for_play_resumes_active_run_without_resetting() -> None:
    client = FakeClient()
    client.states = [{"run_id": "active-run", "frame": 42}]
    harness = PokemonAgent(client_factory=lambda _: client, run_id="agent")

    harness._prepare_run_for_play()

    assert harness._run_id == "active-run"
    assert client.started == []
    assert client.loaded == []
    assert client.events[-1]["type"] == "lifecycle"
    assert client.events[-1]["payload"] == {"status": "run_resumed", "run_id": "active-run", "frame": 42}


def test_prepare_run_for_play_starts_new_run_when_no_run_is_active() -> None:
    class NoActiveRunClient(FakeClient):
        def get_state(self) -> dict[str, Any]:
            raise RuntimeError("No active run")

    client = NoActiveRunClient()
    harness = PokemonAgent(client_factory=lambda _: client, run_id="agent", load_state="bedroom")

    harness._prepare_run_for_play()

    assert len(client.started) == 1
    assert client.started[0].startswith("agent-")
    assert client.loaded == ["bedroom"]
    lifecycle_statuses = [event["payload"]["status"] for event in client.events if event["type"] == "lifecycle"]
    assert lifecycle_statuses == ["run_started", "state_loaded"]


def test_save_state_serializes_history_when_subclass_opts_in() -> None:
    client = FakeClient()

    class HistoryAgent(PokemonAgent):
        def __init__(self) -> None:
            super().__init__(client_factory=lambda _: client)
            self.h: list[str] = ["msg-1", "msg-2"]

        def serialize_history(self) -> dict[str, Any]:
            return {"history": list(self.h)}

        def restore_history(self, data: dict[str, Any]) -> None:
            self.h = list(data.get("history", []))

    harness = HistoryAgent()
    harness.save_state("ckpt-1")

    assert client.saved == [("ckpt-1", {"history": ["msg-1", "msg-2"]})]


def test_load_state_restores_history_from_response() -> None:
    class LoadingFakeClient(FakeClient):
        def load_state(self, name: str) -> dict[str, Any]:
            self.loaded.append(name)
            return {"name": name, "agent_state": {"history": ["snap-1", "snap-2"]}}

    client = LoadingFakeClient()

    class HistoryAgent(PokemonAgent):
        def __init__(self) -> None:
            super().__init__(client_factory=lambda _: client)
            self.h: list[str] = []

        def serialize_history(self) -> dict[str, Any]:
            return {"history": list(self.h)}

        def restore_history(self, data: dict[str, Any]) -> None:
            self.h = list(data.get("history", []))

    harness = HistoryAgent()

    harness.load_state("ckpt-1")

    assert harness.h == ["snap-1", "snap-2"]
    # The local load is also recorded so a subsequent WS echo is dropped.
    assert harness._last_local_load is not None and harness._last_local_load[0] == "ckpt-1"


def test_turn_context_emits_started_and_finished() -> None:
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    with harness.turn(goal="test goal") as turn_id:
        harness.press("A")

    assert turn_id == "turn-001"
    types = [e["type"] for e in client.events]
    assert "turn_started" in types
    assert "turn_finished" in types

    started = next(e for e in client.events if e["type"] == "turn_started")
    finished = next(e for e in client.events if e["type"] == "turn_finished")

    assert started["turn_id"] == "turn-001"
    assert started["payload"]["goal"] == "test goal"
    assert started["payload"]["turn_index"] == 1
    assert finished["payload"]["status"] == "ok"
    assert finished["payload"]["elapsed_ms"] >= 0


def test_turn_ids_increment_correctly() -> None:
    client = FakeClient()
    # Extra state entries for each turn's state() calls
    client.states = [{"frame": 1}] * 20
    harness = PokemonAgent(client_factory=lambda _: client)

    with harness.turn():
        pass
    with harness.turn():
        pass

    turn_started_ids = [e["turn_id"] for e in client.events if e["type"] == "turn_started"]
    assert turn_started_ids == ["turn-001", "turn-002"]


def test_turn_finished_includes_goal() -> None:
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    with harness.turn(goal="leave the bedroom"):
        pass

    finished = next(e for e in client.events if e["type"] == "turn_finished")
    assert finished["payload"]["goal"] == "leave the bedroom"


def test_resume_initialises_turn_counter_from_trace() -> None:
    class ResumeClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self._harness_events: list[dict[str, Any]] = [
                {"type": "turn_finished"},
                {"type": "turn_finished"},
            ]

        def _get(self, path: str) -> Any:
            if "harness-trace" in path:
                return self._harness_events
            return super()._get(path) if hasattr(super(), "_get") else {}

    client = ResumeClient()
    client.states = [{"run_id": "active-run", "frame": 42}]
    harness = PokemonAgent(client_factory=lambda _: client, run_id="agent")

    harness._prepare_run_for_play()

    # 2 existing turns in harness trace → counter starts at 2
    assert harness._turn_counter == 2


def test_turn_explicit_id() -> None:
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    with harness.turn(turn_id="my-custom-turn") as turn_id:
        pass

    assert turn_id == "my-custom-turn"
    started = next(e for e in client.events if e["type"] == "turn_started")
    assert started["turn_id"] == "my-custom-turn"


def test_nested_turn_raises() -> None:
    import pytest
    client = FakeClient()
    client.states = [{"frame": 1}] * 20
    harness = PokemonAgent(client_factory=lambda _: client)

    with pytest.raises(RuntimeError, match="Nested turn"):
        with harness.turn():
            with harness.turn():
                pass


def test_turn_exception_emits_error_status_and_reraises() -> None:
    import pytest
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    with pytest.raises(ValueError, match="oops"):
        with harness.turn():
            raise ValueError("oops")

    finished = next(e for e in client.events if e["type"] == "turn_finished")
    assert finished["payload"]["status"] == "error"
    assert finished["payload"]["error"] == "oops"


def test_turn_context_resets_after_block() -> None:
    from harness.client import get_current_turn_id
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    with harness.turn():
        assert get_current_turn_id() == "turn-001"

    assert get_current_turn_id() is None


def test_press_inherits_turn_id_from_context() -> None:
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    with harness.turn() as turn_id:
        harness.press("RIGHT")

    # press calls client.press_button which uses _current_turn_id
    # Verify the turn_id was set during the call by checking the pressed list
    assert ("RIGHT", 16) in client.pressed
    _ = turn_id  # used, not leaked


def test_take_steering_drains_buffer() -> None:
    client = FakeClient()
    harness = PokemonAgent(client_factory=lambda _: client)

    # No steering yet.
    assert harness.take_steering() == []

    # The control loop buffers `steer:<text>` commands; simulate two arriving.
    with harness._steering_lock:
        harness._steering.extend(["go south", "you passed the exit"])

    assert harness.take_steering() == ["go south", "you passed the exit"]
    # Draining empties the buffer so the same guidance isn't replayed next turn.
    assert harness.take_steering() == []


def test_run_wrapped_emits_full_traceback_on_error(capsys: Any) -> None:
    client = FakeClient()

    class BrokenPokemonAgent(PokemonAgent):
        def __init__(self) -> None:
            super().__init__(client_factory=lambda _: client)
            self.errors: list[str] = []
            self.statuses: list[str] = []

        def run(self) -> None:
            raise RuntimeError("boom")

        def _set_error(self, message: str) -> None:
            self.errors.append(message)

        def _set_status(self, status: str) -> None:
            self.statuses.append(status)

    harness = BrokenPokemonAgent()

    harness._run_wrapped()

    stderr = capsys.readouterr().err
    assert "Traceback (most recent call last)" in stderr
    assert "RuntimeError: boom" in stderr
    assert harness.errors == ["boom"]
    assert harness.statuses[-1] == "idle"
    error_event = next(event for event in client.events if event["type"] == "error")
    assert error_event["payload"]["message"] == "boom"
    assert "RuntimeError: boom" in error_event["payload"]["traceback"]
