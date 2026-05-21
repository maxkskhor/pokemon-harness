"""
Tool-calling Pokemon agent — uses LLM function calling instead of raw text parsing.

The model has three tools:
  - get_state()          read current position (x, y, map_id)
  - move(dir, steps)     walk N tiles in a direction, returns new position
  - press_button(btn)    press a single button (A/B for menus, directions for menu nav)

Within each harness turn the agent runs a tool-call loop: the model can call multiple
tools and see results before ending the turn, so it can react to position feedback.

Setup:
  1. scripts/setup.sh        # first-time setup
  2. Add OPENROUTER_API_KEY to .env
  3. scripts/dev.sh          # starts backend, UI, and all agents in agents.yaml
"""
from __future__ import annotations

import base64
import json
from typing import Any

from dotenv import load_dotenv

from harness import PokemonAgent
from harness.llm import LLMCallError, LLMClient, provider_from_env

load_dotenv()

MODEL = "qwen/qwen3.6-flash"
MAX_TOOL_CALLS_PER_TURN = 8
MAX_HISTORY_TURNS = 12
SPEND_LIMIT_USD = 0.50

SYSTEM_PROMPT = (
    "You are playing Pokemon Red. You start in your bedroom on the second floor of your house.\n"
    "Goal: leave the bedroom, explore Pallet Town, and reach Route 1.\n\n"
    "Tools:\n"
    "  get_state()          — read your current position (x, y, map_id) and frame\n"
    "  move(direction, steps) — walk N tiles; returns new position so you can verify movement\n"
    "  press_button(button) — press A to talk/confirm, B to cancel, UP/DOWN to navigate menus\n\n"
    "Press A when a dialogue box is open."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_state",
            "description": "Read current game state: your position (x, y, map_id) and the frame counter.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": (
                "Walk a number of tiles in one direction on the overworld. "
                "Returns your new position — if x/y didn't change you hit a wall."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["UP", "DOWN", "LEFT", "RIGHT"],
                        "description": "Direction to walk.",
                    },
                    "steps": {
                        "type": "integer",
                        "description": "Number of tiles to walk (1-10).",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["direction", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_button",
            "description": (
                "Press a single Game Boy button. Use A to confirm or interact, "
                "B to cancel, UP/DOWN/LEFT/RIGHT to navigate menus or cursor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["A", "B", "UP", "DOWN", "LEFT", "RIGHT", "START", "SELECT"],
                    }
                },
                "required": ["button"],
            },
        },
    },
]


def _pos_from_state(state: dict[str, Any]) -> dict[str, Any]:
    p = state.get("pokemon", {})
    return {"map_id": p.get("map_id"), "x": p.get("x"), "y": p.get("y")}


def _action_summary(actions: list[dict[str, Any]]) -> str:
    parts = []
    for a in actions:
        tool, result = a["tool"], a["result"]
        if tool == "move":
            pos = result.get("position", {})
            parts.append(f"move {result['moved']}×{result['steps']}→(x={pos.get('x')},y={pos.get('y')},map={pos.get('map_id')})")
        elif tool == "press_button":
            parts.append(f"press {result['pressed']}")
        elif tool == "get_state":
            parts.append(f"get_state→(x={result.get('x')},y={result.get('y')},map={result.get('map_id')})")
        else:
            parts.append(tool)
    return ", ".join(parts) if parts else "(no actions)"


def _cached_system(text: str) -> dict[str, Any]:
    return {"role": "system", "content": [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]}


def _strip_image_urls(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_image_urls(item) for item in value]
    if isinstance(value, dict):
        return {
            k: "<image>" if k == "url" and isinstance(v, str) and v.startswith("data:image/") else _strip_image_urls(v)
            for k, v in value.items()
        }
    return value


class ToolAgent(PokemonAgent):
    name = "Tool Agent"
    model = MODEL

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm = LLMClient(provider_from_env("openrouter"))
        # Cross-turn history: [system] + alternating [user, assistant] pairs (no tool call details)
        self._history: list[dict[str, Any]] = [_cached_system(SYSTEM_PROMPT)]

    def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "get_state":
            state = self.state()
            pos = _pos_from_state(state)
            return pos

        if name == "move":
            direction = args["direction"]
            steps = max(1, min(10, int(args.get("steps", 1))))
            for _ in range(steps):
                self.press(direction)
            state = self.state()
            pos = _pos_from_state(state)
            return {"moved": direction, "steps": steps, "position": pos}

        if name == "press_button":
            button = args["button"]
            self.press(button)
            return {"pressed": button}

        return {"error": f"unknown tool: {name}"}

    def run(self) -> None:
        self._history = [_cached_system(SYSTEM_PROMPT)]
        self._run_cost: float = 0.0  # resets every Play

        while not self.should_stop():
            with self.turn(goal="leave bedroom, explore Pallet Town, reach Route 1"):
                # Build the user message: screenshot + current position
                state = self.state()
                pos = _pos_from_state(state)
                png = self.screenshot_bytes()
                b64 = base64.b64encode(png).decode()

                user_msg: dict[str, Any] = {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {
                            "type": "text",
                            "text": (
                                f"Current position: map={pos.get('map_id')} x={pos.get('x')} y={pos.get('y')}\n"
                                "What do you want to do?"
                            ),
                        },
                    ],
                }

                # Full message list for this turn (grows with tool call rounds)
                messages: list[dict[str, Any]] = self._history + [user_msg]

                actions_taken: list[dict[str, Any]] = []
                final_text = ""

                for _ in range(MAX_TOOL_CALLS_PER_TURN):
                    try:
                        response = self._llm.chat(messages, model=MODEL, tools=TOOLS, tool_choice="auto")
                    except LLMCallError as exc:
                        self.emit("llm_error", exc.to_payload())
                        raise

                    self._run_cost += response.cost_usd
                    raw_msg = response.raw_response.choices[0].message
                    tool_calls = raw_msg.tool_calls or []

                    self.emit("llm_call", {
                        "provider": response.provider,
                        "model": response.model,
                        "messages": _strip_image_urls(messages),
                        "response": {
                            "content": response.content,
                            "tool_calls": [
                                {"name": tc.function.name, "arguments": tc.function.arguments}
                                for tc in tool_calls
                            ],
                            "reasoning": response.reasoning,
                        },
                        "usage": {
                            **response.usage,
                            "latency_ms": response.latency_ms,
                            "attempts": response.attempts,
                            "cost_usd": response.cost_usd,
                            "run_cost_usd": self._run_cost,
                        },
                    })

                    if self._run_cost >= SPEND_LIMIT_USD:
                        self.emit("budget_exceeded", {
                            "run_cost_usd": self._run_cost,
                            "limit_usd": SPEND_LIMIT_USD,
                        })
                        return

                    if not tool_calls:
                        final_text = response.content
                        messages.append({"role": "assistant", "content": final_text})
                        break

                    # Add assistant message as a plain dict (JSON-serializable, OpenAI SDK accepts both)
                    messages.append({
                        "role": "assistant",
                        "content": raw_msg.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                            }
                            for tc in tool_calls
                        ],
                    })

                    # Execute each tool and collect results
                    for tc in tool_calls:
                        args = json.loads(tc.function.arguments)
                        result = self._execute_tool(tc.function.name, args)
                        actions_taken.append({"tool": tc.function.name, "args": args, "result": result})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        })

                summary = _action_summary(actions_taken)
                self.emit("actions", {
                    "tool_calls": actions_taken,
                    "summary": summary,
                })

                # Store text-only user message + action summary in cross-turn history.
                # cache_control on the last assistant message marks the full history prefix
                # as the cache boundary — grows each turn, hits threshold after a few turns.
                text_only = next(c["text"] for c in user_msg["content"] if c["type"] == "text")
                # Remove cache_control from previous tail (only the latest entry should carry it)
                if len(self._history) >= 2 and isinstance(self._history[-1].get("content"), list):
                    self._history[-1]["content"] = [
                        {k: v for k, v in b.items() if k != "cache_control"}
                        for b in self._history[-1]["content"]
                    ]
                self._history.append({"role": "user", "content": text_only})
                self._history.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": final_text or summary, "cache_control": {"type": "ephemeral"}}],
                })
                # Trim: system + last N turn pairs
                max_msgs = 1 + MAX_HISTORY_TURNS * 2
                if len(self._history) > max_msgs:
                    self._history = [self._history[0]] + self._history[-(MAX_HISTORY_TURNS * 2):]


if __name__ == "__main__":
    ToolAgent().serve()
