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

    def get_state(self) -> dict[str, Any]:
        return self.states.pop(0)

    def press_button(self, button: str, frames: int) -> None:
        self.pressed.append((button, frames))

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
