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

    def get_state(self) -> dict[str, Any]:
        return self.states.pop(0)

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
    harness = PokemonAgent()
    client = FakeClient()
    harness._client = client  # type: ignore[assignment]

    harness.press("RIGHT", frames=8)

    assert client.pressed == [("RIGHT", 8)]
    assert client.events == []


def test_harness_public_helpers_delegate_to_client() -> None:
    harness = PokemonAgent()
    client = FakeClient()
    harness._client = client  # type: ignore[assignment]

    assert harness.wait(12) == {"frames": 12}
    assert harness.sequence([{"type": "wait", "frames": 3}]) == {"steps": [{"type": "wait", "frames": 3}]}
    # Default PokemonAgent.serialize_history returns {}; save_state passes None.
    save_result = harness.save_state("checkpoint")
    assert save_result == {"name": "checkpoint", "has_agent_state": False}
    assert harness.load_state("checkpoint") == {"name": "checkpoint"}

    assert client.waited == [12]
    assert client.sequences == [[{"type": "wait", "frames": 3}]]
    assert client.saved == [("checkpoint", None)]
    assert client.loaded == ["checkpoint"]


def test_save_state_serializes_history_when_subclass_opts_in() -> None:
    class HistoryAgent(PokemonAgent):
        def __init__(self) -> None:
            super().__init__()
            self.h: list[str] = ["msg-1", "msg-2"]

        def serialize_history(self) -> dict[str, Any]:
            return {"history": list(self.h)}

        def restore_history(self, data: dict[str, Any]) -> None:
            self.h = list(data.get("history", []))

    harness = HistoryAgent()
    client = FakeClient()
    harness._client = client  # type: ignore[assignment]

    harness.save_state("ckpt-1")

    assert client.saved == [("ckpt-1", {"history": ["msg-1", "msg-2"]})]


def test_load_state_restores_history_from_response() -> None:
    class HistoryAgent(PokemonAgent):
        def __init__(self) -> None:
            super().__init__()
            self.h: list[str] = []

        def serialize_history(self) -> dict[str, Any]:
            return {"history": list(self.h)}

        def restore_history(self, data: dict[str, Any]) -> None:
            self.h = list(data.get("history", []))

    class LoadingFakeClient(FakeClient):
        def load_state(self, name: str) -> dict[str, Any]:
            self.loaded.append(name)
            return {"name": name, "agent_state": {"history": ["snap-1", "snap-2"]}}

    harness = HistoryAgent()
    client = LoadingFakeClient()
    harness._client = client  # type: ignore[assignment]

    harness.load_state("ckpt-1")

    assert harness.h == ["snap-1", "snap-2"]
    # The local load is also recorded so a subsequent WS echo is dropped.
    assert harness._last_local_load is not None and harness._last_local_load[0] == "ckpt-1"


def test_run_wrapped_emits_full_traceback_on_error(capsys: Any) -> None:
    class BrokenPokemonAgent(PokemonAgent):
        def __init__(self) -> None:
            super().__init__()
            self.errors: list[str] = []
            self.statuses: list[str] = []

        def run(self) -> None:
            raise RuntimeError("boom")

        def _set_error(self, message: str) -> None:
            self.errors.append(message)

        def _set_status(self, status: str) -> None:
            self.statuses.append(status)

    harness = BrokenPokemonAgent()
    client = FakeClient()
    harness._client = client  # type: ignore[assignment]

    harness._run_wrapped()

    stderr = capsys.readouterr().err
    assert "Traceback (most recent call last)" in stderr
    assert "RuntimeError: boom" in stderr
    assert harness.errors == ["boom"]
    assert harness.statuses[-1] == "idle"
    error_event = next(event for event in client.events if event["type"] == "error")
    assert error_event["payload"]["message"] == "boom"
    assert "RuntimeError: boom" in error_event["payload"]["traceback"]
