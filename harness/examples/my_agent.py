"""
Pokemon agent using OpenRouter (vision LLM).

Setup:
  1. scripts/dev.sh                          # start backend + UI
  2. uv run python scripts/setup_bedroom.py  # create bedroom save state (run once)

Add your OpenRouter key to .env:
  OPENROUTER_API_KEY=sk-or-...

Run:
  uv run python harness/examples/my_agent.py
"""
from __future__ import annotations

import base64
import os

import openai
from dotenv import load_dotenv

from harness.harness import Harness

load_dotenv()

MODEL = "qwen/qwen3.6-flash"
VALID_BUTTONS = {"A", "B", "UP", "DOWN", "LEFT", "RIGHT", "START", "SELECT"}

PROMPT = (
    "You are playing Pokemon Red. Your goal is to explore — leave the bedroom, walk through "
    "Pallet Town, and reach Route 1.\n"
    "Use UP/DOWN/LEFT/RIGHT to walk. Press A only to talk to someone or confirm a menu. "
    "Press B to cancel. Prefer movement buttons unless a dialogue box is open.\n"
    "Reply with ONLY one button name: A  B  UP  DOWN  LEFT  RIGHT  START  SELECT\n"
    "No explanation, just the single button."
)


class MyAgent(Harness):
    name = "My Agent"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._llm = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def run(self) -> None:
        turn = 0
        while not self.should_stop():
            turn += 1
            turn_id = f"turn-{turn:03d}"

            png = self.screenshot_bytes()
            game = self.state()
            pos = game.get("pokemon", {})

            response = self._llm.chat.completions.create(
                model=MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }],
            )

            raw = (response.choices[0].message.content or "").strip()
            action = raw.upper().split()[0] if raw else ""

            self.emit("decision", {
                "turn": turn,
                "action": action,
                "raw_response": raw,
                "map_id": pos.get("map_id"),
                "x": pos.get("x"),
                "y": pos.get("y"),
            }, turn_id=turn_id)

            if action in VALID_BUTTONS:
                self.press(action)


if __name__ == "__main__":
    MyAgent().serve()
