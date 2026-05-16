from __future__ import annotations

import argparse
from typing import Any

import httpx

from harness.client import PokemonEnvClient, press, wait


SCRIPTED_TURNS: list[dict[str, Any]] = [
    {
        "summary": "boot to title screen and open main menu",
        "steps": [wait(1700), press("A", 12), wait(240)],
    },
    {
        "summary": "select new game",
        "steps": [press("A", 12), wait(300)],
    },
    {
        "summary": "advance Oak introduction to player naming",
        "steps": [
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
        ],
    },
    {
        "summary": "choose preset player name",
        "steps": [press("DOWN", 12), wait(80), press("A", 12), wait(360)],
    },
    {
        "summary": "advance to rival naming",
        "steps": [
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
            press("A", 12),
            wait(160),
        ],
    },
    {
        "summary": "choose preset rival name",
        "steps": [press("DOWN", 12), wait(80), press("A", 12), wait(360)],
    },
    {
        "summary": "finish intro and wait for bedroom control",
        "steps": [
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            press("A", 12),
            wait(220),
            wait(900),
        ],
    },
    {
        "summary": "exit bedroom toward stairs",
        "steps": [
            press("RIGHT", 16),
            press("RIGHT", 16),
            press("RIGHT", 16),
            press("UP", 16),
            press("UP", 16),
            press("UP", 16),
            press("UP", 16),
            press("RIGHT", 16),
            press("RIGHT", 16),
            wait(90),
        ],
    },
    {
        "summary": "leave house and walk north toward grass",
        "steps": [
            press("DOWN", 16),
            press("DOWN", 16),
            press("DOWN", 16),
            press("DOWN", 16),
            press("DOWN", 16),
            press("LEFT", 16),
            press("LEFT", 16),
            press("LEFT", 16),
            press("LEFT", 16),
            press("DOWN", 16),
            wait(120),
            press("UP", 16),
            press("UP", 16),
            press("UP", 16),
            press("UP", 16),
            press("UP", 16),
            wait(240),
        ],
    },
    {
        "summary": "advance Oak lab dialogue",
        "steps": [press("A", 12), wait(60), press("A", 12), wait(60), press("A", 12), wait(60), press("A", 12)],
    },
    {
        "summary": "attempt starter selection",
        "steps": [
            press("RIGHT", 16),
            press("UP", 16),
            press("A", 12),
            wait(60),
            press("A", 12),
            wait(60),
            press("A", 12),
            wait(180),
        ],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Pokemon Red starter-route verification harness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", default="verify-starter")
    parser.add_argument("--rom-path", default=None)
    args = parser.parse_args()

    client = PokemonEnvClient(args.base_url)
    try:
        client.wait_for_server()
        state = client.start_run(args.run_id, rom_path=args.rom_path)
        client.set_speed("paused")
        client.emit("run_note", {"message": "deterministic starter-route harness started"}, turn_id="setup")
        client.save_state("baseline")

        for index, turn in enumerate(SCRIPTED_TURNS, start=1):
            turn_id = f"turn-{index:03d}"
            before = client.get_state()
            client.emit(
                "turn_started",
                {
                    "summary": turn["summary"],
                    "before_frame": before["frame"],
                    "before_pokemon": before.get("pokemon"),
                },
                turn_id=turn_id,
            )
            after = client.press_sequence(turn["steps"])
            client.emit(
                "tool_result",
                {
                    "tool": "press_sequence",
                    "summary": turn["summary"],
                    "after_frame": after["frame"],
                    "after_pokemon": after.get("pokemon"),
                    "screen_sha256": after["screen"]["sha256"],
                },
                turn_id=turn_id,
            )

        final_state = client.get_state()
        party_count = final_state.get("pokemon", {}).get("party_count")
        starter_obtained = isinstance(party_count, int) and party_count > 0
        marker = {
            "status": "starter_obtained" if starter_obtained else "deterministic_smoke_complete",
            "starter_obtained": starter_obtained,
            "frame": final_state["frame"],
            "pokemon": final_state.get("pokemon"),
            "screen_sha256": final_state["screen"]["sha256"],
        }
        client.emit("completion_marker", marker, turn_id="complete")
        print(marker)
    except httpx.HTTPStatusError as exc:
        print(exc.response.text)
        raise
    finally:
        client.close()


if __name__ == "__main__":
    main()
