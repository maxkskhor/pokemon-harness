"""
Pokemon agent using OpenRouter (vision LLM).

Setup:
  1. scripts/dev.sh                          # start backend + UI
  2. uv run python scripts/setup_bedroom.py  # create bedroom save state (run once)

Add your OpenRouter key to .env:
  OPENROUTER_API_KEY=sk-or-...

Run:
  uv run python -m harness.examples.my_agent
"""
from __future__ import annotations

import base64
import threading
from typing import Any

from dotenv import load_dotenv

from harness import PokemonAgent
from harness.llm import (
    LLMCallError,
    LLMClient,
    PROVIDER_PRESETS,
    extract_reasoning as _extract_reasoning,
    provider_from_env,
    strip_think_tags as _strip_think_tags,
)

load_dotenv()

MODEL = PROVIDER_PRESETS["openrouter"].default_model
VALID_BUTTONS = {"A", "B", "UP", "DOWN", "LEFT", "RIGHT", "START", "SELECT"}
MAX_HISTORY_TURNS = 5

SYSTEM_PROMPT = (
    "You are playing Pokemon Red. Your goal is to explore — leave the bedroom, walk through "
    "Pallet Town, and reach Route 1.\n"
    "Use UP/DOWN/LEFT/RIGHT to walk. Press A only to talk to someone or confirm a menu. "
    "Press B to cancel. Prefer movement buttons unless a dialogue box is open.\n"
    "Reply with ONLY one button name: A  B  UP  DOWN  LEFT  RIGHT  START  SELECT\n"
    "No explanation, just the single button."
)

USER_TURN_TEXT = "What button should I press next?"


def _strip_image_data(value: Any) -> Any:
    """Return a JSON-safe copy of an OpenAI message tree without inline base64."""
    if isinstance(value, list):
        return [_strip_image_data(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "url" and isinstance(item, str) and item.startswith("data:image/"):
                out[key] = "<image omitted: see frame thumbnail>"
            else:
                out[key] = _strip_image_data(item)
        return out
    return value


class MyAgent(PokemonAgent):
    name = "My Agent"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm = LLMClient(provider_from_env("openrouter"))
        self._history: list[dict[str, Any]] = []
        # restore_history runs on the control-loop thread (WS-triggered rewinds);
        # run() mutates _history on the run thread. Guard every access.
        self._history_lock = threading.Lock()

    def serialize_history(self) -> dict:
        with self._history_lock:
            return {"history": list(self._history)}

    def restore_history(self, data: dict) -> None:
        history = data.get("history") if isinstance(data, dict) else None
        if isinstance(history, list):
            with self._history_lock:
                self._history = list(history)

    def run(self) -> None:
        turn = 0
        with self._history_lock:
            self._history = [{"role": "system", "content": SYSTEM_PROMPT}]

        while not self.should_stop():
            turn += 1
            turn_id = f"turn-{turn:03d}"

            png = self.screenshot_bytes()
            user_msg: dict = {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
                    },
                    {"type": "text", "text": USER_TURN_TEXT},
                ],
            }
            with self._history_lock:
                self._history.append(user_msg)
                messages_snapshot = list(self._history)

            try:
                response = self._llm.chat(messages_snapshot, model=MODEL)
            except LLMCallError as exc:
                self.emit("llm_error", exc.to_payload(), turn_id=turn_id)
                raise

            raw = response.content
            reasoning = response.reasoning
            self.emit("llm_call", {
                "provider": response.provider,
                "model": response.model,
                "messages": _strip_image_data(messages_snapshot),
                "response": raw,
                "usage": {
                    **response.usage,
                    "latency_ms": response.latency_ms,
                    "attempts": response.attempts,
                },
            }, turn_id=turn_id)

            # Keep history clean: strip think tags from stored assistant response
            clean_response = _strip_think_tags(raw)
            action = clean_response.upper().split()[0] if clean_response else ""

            with self._history_lock:
                self._history.append({"role": "assistant", "content": raw})
                max_msgs = 1 + MAX_HISTORY_TURNS * 2
                if len(self._history) > max_msgs:
                    self._history = [self._history[0]] + self._history[-(MAX_HISTORY_TURNS * 2):]

            self.emit("decision", {
                "turn": turn,
                "action": action,
                "reasoning": reasoning,
                "raw_response": clean_response,
            }, turn_id=turn_id)

            if action in VALID_BUTTONS:
                self.press(action)


if __name__ == "__main__":
    MyAgent().serve()
