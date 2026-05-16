from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness.client import PokemonEnvClient


def replay_env_trace(trace_path: Path, client: PokemonEnvClient) -> None:
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("source") != "env":
            continue
        payload = event.get("payload", {})
        event_type = event.get("type")
        if event_type == "button_press":
            client.press_button(payload["button"], payload["frames"])
        elif event_type == "button_sequence":
            client.press_sequence(payload["steps"])
        elif event_type == "step":
            client.wait(payload["frames"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay env action events into a running Pokemon environment.")
    parser.add_argument("trace_path", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    client = PokemonEnvClient(args.base_url)
    try:
        client.wait_for_server()
        replay_env_trace(args.trace_path, client)
    finally:
        client.close()


if __name__ == "__main__":
    main()

