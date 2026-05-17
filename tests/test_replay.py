from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.client import PokemonEnvClient
from harness.replay import replay_env_trace


class ReplayFakeClient(PokemonEnvClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
        frame: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("emit", {"type": event_type, "payload": payload, "turn_id": turn_id, "frame": frame}))
        return {}

    def press_button(self, button: str, frames: int) -> dict[str, Any]:
        self.calls.append(("press_button", {"button": button, "frames": frames}))
        return {}

    def press_sequence(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(("press_sequence", steps))
        return {}

    def wait(self, frames: int) -> dict[str, Any]:
        self.calls.append(("wait", frames))
        return {}


def test_replay_emits_marker_before_replayed_action(tmp_path: Path) -> None:
    trace = tmp_path / "env.jsonl"
    trace.write_text(
        "\n".join(
            json.dumps(event)
            for event in [
                {
                    "run_id": "source-run",
                    "source": "env",
                    "type": "button_press",
                    "frame": 10,
                    "payload": {"button": "RIGHT", "frames": 8},
                },
                {
                    "run_id": "source-run",
                    "source": "harness",
                    "type": "decision",
                    "frame": 10,
                    "payload": {},
                },
                {
                    "run_id": "source-run",
                    "source": "env",
                    "type": "step",
                    "frame": 18,
                    "payload": {"frames": 12},
                },
            ]
        ),
        encoding="utf-8",
    )
    client = ReplayFakeClient()

    replay_env_trace(trace, client)

    assert client.calls == [
        (
            "emit",
            {
                "type": "replay_marker",
                "payload": {
                    "source_run_id": "source-run",
                    "source_frame": 10,
                    "source_event_type": "button_press",
                },
                "turn_id": None,
                "frame": None,
            },
        ),
        ("press_button", {"button": "RIGHT", "frames": 8}),
        (
            "emit",
            {
                "type": "replay_marker",
                "payload": {
                    "source_run_id": "source-run",
                    "source_frame": 18,
                    "source_event_type": "step",
                },
                "turn_id": None,
                "frame": None,
            },
        ),
        ("wait", 12),
    ]
