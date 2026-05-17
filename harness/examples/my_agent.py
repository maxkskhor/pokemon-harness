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
import os
import re

import openai
from dotenv import load_dotenv

from harness import PokemonAgent

load_dotenv()

MODEL = "qwen/qwen3.6-flash"
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


def _extract_reasoning(response: openai.types.chat.ChatCompletion) -> str | None:
    msg = response.choices[0].message
    # OpenRouter exposes reasoning as a direct field or in model_extra
    reasoning = getattr(msg, "reasoning", None)
    if not reasoning and hasattr(msg, "model_extra") and msg.model_extra:
        reasoning = msg.model_extra.get("reasoning")
    if reasoning:
        return str(reasoning).strip()
    # Fall back to <think>...</think> tags in content
    content = msg.content or ""
    match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class MyAgent(PokemonAgent):
    name = "My Agent"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._llm = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
        self._history: list[dict] = []

    def serialize_history(self) -> dict:
        # Snapshot the rolling LLM history so a checkpoint can rewind not just the
        # emulator but also the model's view of "what already happened".
        return {"history": list(self._history)}

    def restore_history(self, data: dict) -> None:
        history = data.get("history") if isinstance(data, dict) else None
        if isinstance(history, list):
            self._history = list(history)

    def run(self) -> None:
        turn = 0
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
            self._history.append(user_msg)

            response = self._llm.chat.completions.create(
                model=MODEL,
                messages=self._history,
            )

            raw = (response.choices[0].message.content or "").strip()
            reasoning = _extract_reasoning(response)
            # Keep history clean: strip think tags from stored assistant response
            clean_response = _strip_think_tags(raw)
            action = clean_response.upper().split()[0] if clean_response else ""

            self._history.append({"role": "assistant", "content": raw})

            # Keep rolling window: system msg + last N turn pairs
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
