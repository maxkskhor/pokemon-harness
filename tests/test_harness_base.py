from __future__ import annotations

from typing import Any

from harness.harness import Harness


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

    def save_state(self, name: str) -> dict[str, Any]:
        self.saved.append(name)
        return {"name": name}

    def load_state(self, name: str) -> dict[str, Any]:
        self.loaded.append(name)
        return {"name": name}

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


def test_harness_press_emits_action_event() -> None:
    harness = Harness()
    client = FakeClient()
    harness._client = client  # type: ignore[assignment]

    harness.press("RIGHT", frames=8)

    assert client.pressed == [("RIGHT", 8)]
    assert client.events == [
        {
            "type": "action",
            "payload": {
                "kind": "button_press",
                "button": "RIGHT",
                "frames": 8,
                "before": {"frame": 10, "map_id": 38, "x": 3, "y": 6},
                "after": {"frame": 18, "map_id": 38, "x": 4, "y": 6},
            },
            "turn_id": None,
            "frame": None,
        }
    ]


def test_harness_public_helpers_delegate_to_client() -> None:
    harness = Harness()
    client = FakeClient()
    harness._client = client  # type: ignore[assignment]

    assert harness.wait(12) == {"frames": 12}
    assert harness.sequence([{"type": "wait", "frames": 3}]) == {"steps": [{"type": "wait", "frames": 3}]}
    assert harness.save_state("checkpoint") == {"name": "checkpoint"}
    assert harness.load_state("checkpoint") == {"name": "checkpoint"}

    assert client.waited == [12]
    assert client.sequences == [[{"type": "wait", "frames": 3}]]
    assert client.saved == ["checkpoint"]
    assert client.loaded == ["checkpoint"]


def test_run_wrapped_emits_full_traceback_on_error(capsys: Any) -> None:
    class BrokenHarness(Harness):
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

    harness = BrokenHarness()
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
