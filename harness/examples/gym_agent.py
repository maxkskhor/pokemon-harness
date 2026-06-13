"""
Gym Agent — a harness built to actually reach and beat the first gym.

What makes it stronger than the earlier examples:
- Rich text observation from RAM every turn (location, party with moves/PP,
  battle state with both sides' HP) alongside the screenshot, so even a very
  cheap model has the facts it needs.
- Deterministic battle macros: `battle_move(slot)` navigates the FIGHT menu
  using live cursor reads instead of hoping the LLM presses the right buttons.
- Learned wall map: failed moves are remembered per map and replayed into the
  observation, so the agent stops bumping into the same furniture.
- Persistent scratchpad notes that survive checkpoints and rollbacks.
- A MetaHarness supervisor (harness/meta.py): milestone curriculum with goal
  prompts, auto-checkpoint per milestone, blackout/stuck rollback, model
  escalation, and a hard budget.

Model defaults to openai/gpt-5-nano (see harness/meta.py); override with
POKEMON_AGENT_MODEL / POKEMON_ESCALATION_MODEL.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from typing import Any

from dotenv import load_dotenv

from harness import PokemonAgent
from harness.llm import LLMCallError, LLMClient, provider_from_env
from harness.meta import MetaConfig, MetaHarness

load_dotenv()

MAX_TOOL_CALLS_PER_TURN = 6
MAX_HISTORY_TURNS = 10
BUDGET_USD = float(os.environ.get("POKEMON_BUDGET_USD", "2.0"))
# A Gen 1 step takes ~16 frames AFTER the input registers, and pressing a
# direction you are not facing spends ~8 frames just turning. Read position
# only after the step animation has fully committed.
MOVE_SETTLE_FRAMES = 24
MAX_NOTES_CHARS = 1200
MAX_WALLS_PER_MAP = 200

SYSTEM_PROMPT = """\
You are playing Pokemon Red on a Game Boy. Your mission: get the Boulder Badge from \
Brock's gym in Pewter City. A GOAL line in each observation tells you the current \
objective — follow it.

How the world works:
- The overworld is a tile grid; (x,y) has y increasing DOWNWARD (UP decreases y).
- EXITS lists this map's door/stair/mat tiles and where they lead — walk ONTO an exit \
tile to use it. Use goto(x,y) to reach any exact tile: exits, pokeballs, NPCs, doors.
- CONNECTIONS lists neighbouring outdoor maps — walk past the map edge in that \
direction to cross (goto a tile on that edge, then move once more in that direction).
- Buildings are entered through their door at the bottom-front.
- goto() is precise; use move() only for short freestyle exploration.
- When text/dialogue is on screen, advance it with press(["A"]). Choose YES/NO with \
the cursor (UP/DOWN) then A. B cancels/backs out of menus.
- KNOWN WALLS lists directions that failed before from nearby tiles — do not retry them.
- To pick up a pokeball on a table (e.g. your starter in Oak's lab), goto the tile next \
to it, move INTO it to face it, then call take_starter() — it handles the "Do you want \
X?" and nickname prompts for you. Do not mash A through that dialogue.
- If a HUMAN STEER line is present, a person is actively watching: do exactly what it \
says THIS turn, even if it differs from the GOAL.
- In battle, use battle_move(slot). Pick the strongest damaging move (Bubble/Water Gun \
vs Rock; Tackle/Scratch otherwise). Status moves like Tail Whip/Growl are usually a \
waste. After "X fainted!" keep pressing A through the messages.

Rules:
- ALWAYS call exactly one tool per response. Plain text does nothing.
- Movement that doesn't change (x,y) means a wall or closed dialog — try another \
direction or press A.
- If the same approach failed twice, do something different.
- Use note() to record discoveries worth remembering (exits found, NPC hints, plans).
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Walk up to 8 tiles in one direction. Returns new position and whether you actually moved (false = wall/obstacle).",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["UP", "DOWN", "LEFT", "RIGHT"]},
                    "steps": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["direction", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "goto",
            "description": "Walk toward an exact tile (x,y) on the CURRENT map. Handles obstacles using known walls; stops on arrival, on a map change, or if truly blocked. Use this to reach exits, pokeballs, NPCs, and doors precisely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "minimum": 0, "maximum": 255},
                    "y": {"type": "integer", "minimum": 0, "maximum": 255},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press",
            "description": "Press a short sequence of buttons (for dialogue, menus, signs). A=confirm/advance text, B=cancel/back, START=main menu, arrows=cursor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "buttons": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["A", "B", "UP", "DOWN", "LEFT", "RIGHT", "START", "SELECT"]},
                        "minItems": 1,
                        "maxItems": 6,
                    }
                },
                "required": ["buttons"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "battle_move",
            "description": "In battle: use the move in the given slot (1-4). Handles the FIGHT menu automatically and reports the resulting HP on both sides.",
            "parameters": {
                "type": "object",
                "properties": {"slot": {"type": "integer", "minimum": 1, "maximum": 4}},
                "required": ["slot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_starter",
            "description": "In Oak's lab, when standing next to a pokeball and FACING it (goto the tile below/beside it and move into it first): pick it up. Confirms the 'Do you want X?' prompt with YES and declines the nickname prompt automatically, without overshooting into the naming screen. Use this instead of pressing A through the pickup.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_away",
            "description": "In a WILD battle: try to flee. Does not work against trainers.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note",
            "description": "Save a short note to your persistent scratchpad (shown every turn, survives checkpoints). Use for discoveries, plans, and reminders.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "maxLength": 300}},
                "required": ["text"],
            },
        },
    },
]


def _strip_image_urls(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_image_urls(item) for item in value]
    if isinstance(value, dict):
        return {
            k: "<image>" if k == "url" and isinstance(v, str) and v.startswith("data:image/") else _strip_image_urls(v)
            for k, v in value.items()
        }
    return value


def _cached(text: str) -> dict[str, Any]:
    return {"role": "system", "content": [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]}


class GymAgent(PokemonAgent):
    name = "Gym Agent"
    model = os.environ.get("POKEMON_AGENT_MODEL") or "openai/gpt-5-nano"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm = LLMClient(provider_from_env("openrouter"))
        self._lock = threading.Lock()
        self._history: list[dict[str, Any]] = []
        self._notes: str = ""
        # walls[map_id] = set of "x,y,DIR" strings that failed to move.
        self._walls: dict[int, set[str]] = {}
        # Structured, checkpointed world map: every map_id the agent has actually
        # set foot on, with its name, when it was first seen, a visit count, and
        # the outdoor connections observed from it. Inspectable (emitted as
        # `world_update` on discovery) and rides along in checkpoints.
        self._world: dict[int, dict[str, Any]] = {}
        # Rolling (map,x,y) of recent turn-starts for micro-loop detection.
        self._recent_positions: list[tuple[Any, Any, Any]] = []
        self._loop_streak = 0
        self._run_cost = 0.0
        # Optional hard turn cap for benchmarking (scripts/bench.py). 0/unset = no cap.
        self._max_turns = int(os.environ.get("POKEMON_MAX_TURNS", "0")) or None
        self._meta = MetaHarness(
            emit=self.emit,
            save_checkpoint=self.save_state,
            load_checkpoint=self.load_state,
            config=MetaConfig(budget_usd=BUDGET_USD),
        )

    # ── checkpoint round-trip (includes meta progress + notes + walls) ──

    def serialize_history(self) -> dict[str, Any]:
        with self._lock:
            return {
                "history": list(self._history),
                "notes": self._notes,
                "walls": {str(k): sorted(v) for k, v in self._walls.items()},
                "world": {str(k): v for k, v in self._world.items()},
                "meta": self._meta.serialize(),
            }

    def restore_history(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            history = data.get("history")
            if isinstance(history, list):
                self._history = list(history)
            self._notes = str(data.get("notes") or "")
            walls = data.get("walls")
            if isinstance(walls, dict):
                self._walls = {
                    int(k): set(v) for k, v in walls.items() if isinstance(v, list)
                }
                # Drop tiles claiming to be boxed in on all four sides — those
                # came from moves attempted while the game ignored input.
                for wall_set in self._walls.values():
                    for entry in list(wall_set):
                        try:
                            x, y, _ = entry.split(",")
                            self._purge_boxed_tiles(wall_set, int(x), int(y))
                        except ValueError:
                            continue
            world = data.get("world")
            if isinstance(world, dict):
                self._world = {
                    int(k): v for k, v in world.items() if isinstance(v, dict)
                }
            self._meta.restore(data.get("meta") or {})

    # ── observation ────────────────────────────────────────────────────

    def _status(self) -> dict[str, Any]:
        return self.state().get("status") or {}

    def _position(self, status: dict[str, Any]) -> tuple[int | None, int | None]:
        state = self.state()
        pokemon = state.get("pokemon") or {}
        return pokemon.get("x"), pokemon.get("y")

    def _input_locked(self) -> bool:
        """True while the game runs a scripted scene (player not controllable).

        Covers both wJoyIgnore and wStatusFlags5 bit 6 (simulated movement),
        which together catch the Oak-walks-you-to-the-lab style cutscenes that
        wJoyIgnore alone misses.
        """
        pokemon = self.state().get("pokemon") or {}
        if pokemon.get("joy_ignore"):
            return True
        flags5 = pokemon.get("status_flags5")
        return bool(isinstance(flags5, int) and flags5 & 0x40)

    def _observation_text(self, status: dict[str, Any], steer: list[str] | None = None) -> str:
        state = self.state()
        pokemon = state.get("pokemon") or {}
        map_id = status.get("map_id")
        x, y = pokemon.get("x"), pokemon.get("y")
        lines = [
            f"LOCATION: {status.get('map_name') or f'map {map_id}'} (map {map_id}), position ({x},{y})",
        ]
        if steer:
            lines.append(
                "!! HUMAN STEER (a person is watching — follow this instruction NOW, "
                "above the GOAL): " + " | ".join(steer)
            )
        party = status.get("party") or []
        if party:
            for mon in party:
                moves = ", ".join(f"{m['slot']}:{m['name']}({m['pp']}pp)" for m in mon.get("moves", []))
                flag = f" [{mon['status']}]" if mon.get("status") else ""
                lines.append(
                    f"PARTY {mon['slot']}: {mon['nickname']} Lv{mon['level']} "
                    f"{mon['hp']}/{mon['max_hp']}HP{flag} — {moves or 'no moves'}"
                )
        else:
            lines.append("PARTY: none yet")
        lines.append(
            f"MONEY: ₽{status.get('money')} | BADGES: {', '.join(status.get('badges') or []) or 'none'}"
        )
        if self._input_locked():
            lines.append(
                "!! CUTSCENE / SCRIPTED SCENE ACTIVE: movement is locked by the game. "
                'Use press(["A","A","A"]) to advance — do NOT try to move.'
            )
        battle = status.get("battle")
        if battle:
            enemy = (
                f"{battle.get('enemy_species')} Lv{battle.get('enemy_level')} "
                f"{battle.get('enemy_hp')}/{battle.get('enemy_max_hp')}HP"
            )
            mine = battle.get("my") or {}
            my_moves = ", ".join(f"{m['slot']}:{m['name']}({m['pp']}pp)" for m in mine.get("moves", []))
            lines.append(
                f"** IN {battle.get('kind', 'wild').upper()} BATTLE ** enemy {enemy} | "
                f"your {mine.get('species')} {mine.get('hp')}/{mine.get('max_hp')}HP — moves: {my_moves}"
            )
        exits = status.get("exits") or []
        if exits:
            lines.append(
                "EXITS on this map: "
                + "; ".join(f"({e['x']},{e['y']}) -> {e['to']}" for e in exits[:10])
            )
        conns = status.get("connections") or {}
        if conns:
            lines.append(
                "CONNECTIONS: " + ", ".join(f"{d} -> {name}" for d, name in conns.items())
            )
        if self._world:
            visited = ", ".join(sorted({e.get("name", "?") for e in self._world.values()}))
            lines.append(f"VISITED MAPS (already explored — don't backtrack needlessly): {visited}")
        walls = self._nearby_walls(map_id, x, y)
        if walls:
            lines.append(f"KNOWN WALLS (from failed moves): {'; '.join(walls)}")
        if self._is_looping(map_id, x, y):
            self._loop_streak += 1
            lines.append(
                "!! LOOP DETECTED: you have hovered around this spot for many turns. "
                "Stop oscillating. Pick the direction that gets you closer to the GOAL "
                "coordinates, commit to 4+ steps, and do not re-enter a door you just left."
            )
        else:
            self._loop_streak = 0
        if self._notes:
            lines.append(f"NOTES: {self._notes}")
        lines.append(f"GOAL: {self._meta.goal()}")
        return "\n".join(lines)

    def _is_looping(self, map_id: Any, x: Any, y: Any) -> bool:
        self._recent_positions.append((map_id, x, y))
        self._recent_positions = self._recent_positions[-10:]
        if len(self._recent_positions) < 8 or not isinstance(x, int) or not isinstance(y, int):
            return False
        recent = self._recent_positions[-8:]
        return all(
            m == map_id and isinstance(px, int) and isinstance(py, int)
            and abs(px - x) + abs(py - y) <= 2
            for m, px, py in recent
        )

    def _nearby_walls(self, map_id: Any, x: Any, y: Any) -> list[str]:
        if not isinstance(map_id, int) or not isinstance(x, int) or not isinstance(y, int):
            return []
        out = []
        for entry in sorted(self._walls.get(map_id, ())):
            try:
                ex, ey, direction = entry.split(",")
                if abs(int(ex) - x) + abs(int(ey) - y) <= 5:
                    out.append(f"({ex},{ey})->{direction}")
            except ValueError:
                continue
        return out[:12]

    def _update_world(self, status: dict[str, Any]) -> None:
        """Record the current map in the structured world memory.

        First visit to a map emits a `world_update` trace event so the discovery
        is observable in the UI; subsequent visits just bump the count and fold in
        any newly observed outdoor connections.
        """
        map_id = status.get("map_id")
        if not isinstance(map_id, int):
            return
        entry = self._world.get(map_id)
        if entry is None:
            entry = {
                "name": status.get("map_name") or f"map {map_id}",
                # _turn_counter is the 1-based current turn (incremented on turn()
                # entry); meta.state.turns isn't bumped until the end-of-turn
                # observe(), so it would record a turn too low here.
                "first_turn": self._turn_counter,
                "visits": 0,
                "connections": {},
            }
            self._world[map_id] = entry
            self.emit(
                "world_update",
                {
                    "map_id": map_id,
                    "name": entry["name"],
                    "discovered_turn": entry["first_turn"],
                    "known_maps": len(self._world),
                },
            )
        entry["visits"] += 1
        conns = status.get("connections") or {}
        if conns:
            entry["connections"].update(conns)

    # ── tools ──────────────────────────────────────────────────────────

    def _single_step(self, direction: str, before_map: Any) -> bool:
        """One tile in `direction`. Returns True if position or map changed."""
        px, py = self._position(self._status())
        self.press(direction)
        self.sequence([{"type": "wait", "frames": MOVE_SETTLE_FRAMES}])
        status = self._status()
        nx, ny = self._position(status)
        if (nx, ny) == (px, py) and status.get("map_id") == before_map:
            # The first press may have only TURNED the player to face this
            # direction. Try once more before calling it a wall.
            self.press(direction)
            self.sequence([{"type": "wait", "frames": MOVE_SETTLE_FRAMES}])
            status = self._status()
            nx, ny = self._position(status)
        if (nx, ny) == (px, py) and status.get("map_id") == before_map:
            self._record_wall(before_map, px, py, direction)
            return False
        return True

    def _is_wall(self, map_id: Any, x: Any, y: Any, direction: str) -> bool:
        return f"{x},{y},{direction}" in self._walls.get(map_id, set())

    def _tool_move(self, direction: str, steps: int) -> dict[str, Any]:
        steps = max(1, min(8, int(steps)))
        status = self._status()
        before_map = status.get("map_id")
        bx, by = self._position(status)
        walked = 0
        for _ in range(steps):
            if not self._single_step(direction, before_map):
                break
            walked += 1
            if self._status().get("map_id") != before_map:
                break  # entered a door / new map
        after = self._status()
        ax, ay = self._position(after)
        return {
            "requested": steps,
            "walked": walked,
            "moved": walked > 0,
            "from": {"x": bx, "y": by, "map": before_map},
            "to": {"x": ax, "y": ay, "map": after.get("map_id"), "map_name": after.get("map_name")},
            "entered_new_map": after.get("map_id") != before_map,
            "in_battle": bool(after.get("battle")),
        }

    def _tool_goto(self, tx: int, ty: int) -> dict[str, Any]:
        """Greedy local navigation to (tx,ty) on the current map.

        Prefers the axis with the larger remaining gap, consults the learned
        wall map, sidesteps when the direct direction is blocked, and avoids
        bouncing straight back to the previous tile. No collision data needed.
        """
        status = self._status()
        before_map = status.get("map_id")
        sx, sy = self._position(status)
        previous: tuple[Any, Any] | None = None
        for _ in range(24):
            status = self._status()
            if status.get("map_id") != before_map:
                break
            x, y = self._position(status)
            if (x, y) == (tx, ty):
                break
            dx, dy = tx - (x or 0), ty - (y or 0)
            ordered: list[str] = []
            x_dir = "RIGHT" if dx > 0 else "LEFT"
            y_dir = "DOWN" if dy > 0 else "UP"
            if abs(dy) >= abs(dx):
                if dy: ordered.append(y_dir)
                if dx: ordered.append(x_dir)
            else:
                if dx: ordered.append(x_dir)
                if dy: ordered.append(y_dir)
            # Sidestep candidates if both useful directions are walls.
            for fallback in ("UP", "DOWN", "LEFT", "RIGHT"):
                if fallback not in ordered:
                    ordered.append(fallback)
            stepped = False
            for direction in ordered:
                delta = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}[direction]
                nxt = ((x or 0) + delta[0], (y or 0) + delta[1])
                if nxt == previous and direction not in ordered[:1]:
                    continue  # don't ping-pong unless it's the primary direction
                if self._is_wall(before_map, x, y, direction):
                    continue
                if self._single_step(direction, before_map):
                    previous = (x, y)
                    stepped = True
                    break
            if not stepped:
                break  # boxed in (by current knowledge) — let the LLM decide
        after = self._status()
        ax, ay = self._position(after)
        return {
            "target": {"x": tx, "y": ty},
            "arrived": (ax, ay) == (tx, ty) and after.get("map_id") == before_map,
            "position": {"x": ax, "y": ay, "map": after.get("map_id"), "map_name": after.get("map_name")},
            "entered_new_map": after.get("map_id") != before_map,
            "in_battle": bool(after.get("battle")),
        }

    def _record_wall(self, map_id: Any, x: Any, y: Any, direction: str) -> None:
        if not (isinstance(map_id, int) and isinstance(x, int) and isinstance(y, int)):
            return
        # A failed move while the game holds the input lock (cutscene/dialog)
        # says nothing about walls.
        if self._input_locked():
            return
        walls = self._walls.setdefault(map_id, set())
        if len(walls) < MAX_WALLS_PER_MAP:
            walls.add(f"{x},{y},{direction}")
        self._purge_boxed_tiles(walls, x, y)

    @staticmethod
    def _purge_boxed_tiles(walls: set[str], x: int, y: int) -> None:
        """All four directions 'blocked' from one tile means the inputs were
        being ignored, not that walls exist — drop the bogus entries."""
        directions = ("UP", "DOWN", "LEFT", "RIGHT")
        if all(f"{x},{y},{d}" in walls for d in directions):
            for d in directions:
                walls.discard(f"{x},{y},{d}")

    def _tool_press(self, buttons: list[str]) -> dict[str, Any]:
        for button in buttons[:6]:
            self.press(button)
            self.sequence([{"type": "wait", "frames": 30}])
        after = self._status()
        x, y = self._position(after)
        return {
            "pressed": buttons[:6],
            "position": {"x": x, "y": y, "map": after.get("map_id"), "map_name": after.get("map_name")},
            "in_battle": bool(after.get("battle")),
        }

    def _menu_cursor(self) -> int | None:
        return (self.state().get("pokemon") or {}).get("menu_state")

    def _party_count(self) -> int:
        """Raw wPartyCount byte (not the level-gated 'real' count).

        This is the signal that increments the *instant* a Pokemon is added to
        the party, which is exactly what take_starter uses to stop pressing A.
        """
        value = (self.state().get("pokemon") or {}).get("party_count")
        return value if isinstance(value, int) else 0

    def _tool_take_starter(self) -> dict[str, Any]:
        """Deterministically pick up the pokeball the player is FACING in Oak's lab.

        The flaky part for a cheap model is the two prompts: "Do you want X?" (answer
        YES) and "Give a nickname?" (answer NO). Pressing A blindly through them either
        picks NO on the first or opens the naming screen on the second, leaving a
        phantom level-0 party slot. This macro:
          1. Pins the cursor on YES and presses A to confirm, stopping the *instant*
             wPartyCount increments — so it can never press A again into the nickname
             box (the move that opens the keyboard).
          2. Drives the nickname YES/NO to NO using the live menu cursor.
        """
        if self._status().get("battle"):
            return {"error": "in battle — finish the fight before picking up a ball"}
        start_count = self._party_count()

        acquired = False
        for _ in range(12):
            if self._party_count() > start_count:
                acquired = True
                break
            self.press("UP")  # pin YES (top option); a no-op on plain text boxes
            self.sequence([{"type": "wait", "frames": 20}])
            self.press("A")  # advance dialogue / confirm YES
            self.sequence([{"type": "wait", "frames": 40}])
        if not acquired and self._party_count() > start_count:
            acquired = True

        if acquired:
            # Advance the "<NAME> received X!" line to surface the nickname YES/NO.
            self.press("A")
            self.sequence([{"type": "wait", "frames": 50}])
            # Decline the nickname: move the cursor to NO (index 1) from its read
            # state, then confirm. Mirrors battle_move's cursor-driven selection.
            if self._menu_cursor() == 0:
                self.press("DOWN")
                self.sequence([{"type": "wait", "frames": 20}])
            self.press("A")
            self.sequence([{"type": "wait", "frames": 60}])
            self.press("A")  # clear any trailing dialogue line
            self.sequence([{"type": "wait", "frames": 40}])

        status = self._status()
        party = status.get("party") or []
        real = [m for m in party if (m.get("level") or 0) >= 1]
        return {
            "acquired": bool(real),
            "party": [f"{m['nickname']} Lv{m['level']}" for m in real],
            "phantom_slot": len(party) > len(real),
            "in_battle": bool(status.get("battle")),
        }

    def _tool_battle_move(self, slot: int) -> dict[str, Any]:
        slot = max(1, min(4, int(slot)))
        status = self._status()
        battle = status.get("battle")
        if not battle:
            return {"error": "not in battle"}
        before_enemy = battle.get("enemy_hp")
        before_mine = (battle.get("my") or {}).get("hp")
        # Normalize: close any open submenu, park the action cursor on FIGHT.
        for button in ("B", "UP", "LEFT"):
            self.press(button)
            self.sequence([{"type": "wait", "frames": 20}])
        self.press("A")  # open the move list
        self.sequence([{"type": "wait", "frames": 30}])
        cursor = self._menu_cursor()
        target = slot - 1
        if isinstance(cursor, int) and 0 <= cursor <= 3:
            delta = target - cursor
            button = "DOWN" if delta > 0 else "UP"
            for _ in range(abs(delta)):
                self.press(button)
                self.sequence([{"type": "wait", "frames": 15}])
        self.press("A")  # use the move
        self.sequence([{"type": "wait", "frames": 300}])  # attack + enemy reply animations
        # Flush any single message box (e.g. "It's super effective!").
        self.press("A")
        self.sequence([{"type": "wait", "frames": 120}])
        after = self._status()
        after_battle = after.get("battle") or {}
        result = {
            "used_slot": slot,
            "battle_over": not after.get("battle"),
            "enemy_hp": after_battle.get("enemy_hp"),
            "enemy_hp_before": before_enemy,
            "my_hp": (after_battle.get("my") or {}).get("hp"),
            "my_hp_before": before_mine,
        }
        if result["battle_over"]:
            result["hint"] = "battle ended — press A a few times to clear messages, then continue"
        return result

    def _tool_run_away(self) -> dict[str, Any]:
        status = self._status()
        battle = status.get("battle")
        if not battle:
            return {"error": "not in battle"}
        if battle.get("kind") == "trainer":
            return {"error": "cannot run from a trainer battle — fight with battle_move"}
        for button in ("B", "UP", "LEFT"):  # park on FIGHT
            self.press(button)
            self.sequence([{"type": "wait", "frames": 20}])
        for button in ("DOWN", "RIGHT", "A"):  # RUN is bottom-right
            self.press(button)
            self.sequence([{"type": "wait", "frames": 30}])
        self.sequence([{"type": "wait", "frames": 180}])
        after = self._status()
        return {"escaped": not after.get("battle")}

    def _tool_note(self, text: str) -> dict[str, Any]:
        with self._lock:
            combined = (self._notes + "\n" + text).strip() if self._notes else text
            # Keep the newest content when over budget.
            self._notes = combined[-MAX_NOTES_CHARS:]
        return {"saved": True}

    def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "move":
            return self._tool_move(args.get("direction", "UP"), args.get("steps", 1))
        if name == "goto":
            return self._tool_goto(int(args.get("x", 0)), int(args.get("y", 0)))
        if name == "press":
            return self._tool_press(list(args.get("buttons") or ["A"]))
        if name == "battle_move":
            return self._tool_battle_move(args.get("slot", 1))
        if name == "take_starter":
            return self._tool_take_starter()
        if name == "run_away":
            return self._tool_run_away()
        if name == "note":
            return self._tool_note(str(args.get("text") or ""))
        return {"error": f"unknown tool: {name}"}

    # ── main loop ──────────────────────────────────────────────────────

    def run(self) -> None:
        with self._lock:
            if not self._history:
                self._history = [_cached(SYSTEM_PROMPT)]
        self._run_cost = 0.0

        while not self.should_stop():
            # Headless benchmark stop conditions (scripts/bench.py): a turn cap and
            # "journey complete". The budget stop is handled inside the turn below.
            if self._max_turns and self._meta.state.turns >= self._max_turns:
                self.emit("lifecycle", {"status": "max_turns_reached", "turns": self._meta.state.turns})
                return
            if self._meta.current_milestone() is None:
                self.emit("lifecycle", {"status": "all_milestones_complete"})
                return
            goal_label = (self._meta.current_milestone().label if self._meta.current_milestone() else "explore")
            with self.turn(goal=goal_label):
                restore_speed: str | None = None
                state = self.state()
                current_speed = state.get("speed_mode")
                if isinstance(current_speed, str) and current_speed != "paused":
                    restore_speed = current_speed
                    self._client.set_speed("paused")

                try:
                    self._play_one_turn()
                    # Meta supervision: milestones, rollback, budget.
                    verdict = self._meta.observe(self._status(), self._run_cost)
                finally:
                    if restore_speed is not None:
                        self._client.set_speed(restore_speed)

                if verdict["over_budget"]:
                    self.emit("budget_exceeded", {
                        "run_cost_usd": self._run_cost,
                        "limit_usd": self._meta.config.budget_usd,
                    })
                    return
                if verdict["rolled_back"]:
                    continue  # state (and our history/notes) were restored

    def _autoplay_cutscene(self) -> int:
        """Advance scripted scenes without spending LLM calls.

        The agent pauses the emulator while it thinks and turns run back to
        back, so scripted sequences (Oak walking you to the lab, etc.) never
        get frames unless we grant them. While the game holds the input lock
        (wJoyIgnore), tick time forward and tap A to flush dialogue.
        """
        rounds = 0
        for _ in range(20):
            if not self._input_locked():
                break
            self.press("A")
            self.sequence([{"type": "wait", "frames": 180}])
            rounds += 1
        if rounds:
            self.emit("lifecycle", {"status": "cutscene_autoplay", "rounds": rounds})
        return rounds

    def _circuit_breaker(self, status: dict[str, Any]) -> bool:
        """When the agent has looped for a long stretch, its own context is the
        problem: repetitive history invites parroting and stale notes can carry
        bad advice ('just press A'). Wipe both and state plainly what failed."""
        if self._loop_streak < 10:
            return False
        state = self.state()
        pokemon = state.get("pokemon") or {}
        position = f"({pokemon.get('x')},{pokemon.get('y')}) on {status.get('map_name')}"
        with self._lock:
            self._history = [self._history[0]] if self._history else []
            self._notes = (
                f"CIRCUIT BREAKER: I repeated the same actions at {position} for many "
                "turns and they did NOT work. That approach is forbidden now. I must "
                "physically move to a different coordinate that matches the GOAL text."
            )
        self._loop_streak = 0
        self.emit("lifecycle", {"status": "circuit_breaker", "position": position})
        return True

    def _play_one_turn(self) -> None:
        self._autoplay_cutscene()
        # Let any in-flight overworld transition (a map-change fade, the tail of a
        # step animation) finish before we screenshot. Otherwise the agent pauses
        # mid-fade and both the model's observation image AND the live spectator
        # view catch a black transition frame. Skipped in battle so we don't tick
        # past attack/HP animations the agent needs to read.
        if not self._status().get("battle"):
            self.sequence([{"type": "wait", "frames": 12}])
        # Human-in-the-loop: fold any guidance typed in the UI into this turn's
        # observation and persist it to notes so it carries across a few turns.
        steer = self.take_steering()
        if steer:
            self.emit("steering", {"message": " | ".join(steer)})
            with self._lock:
                joined = " ".join(steer)
                self._notes = ((self._notes + "\n[HUMAN] " + joined).strip())[-MAX_NOTES_CHARS:]
        status = self._status()
        self._update_world(status)
        observation = self._observation_text(status, steer=steer)
        if self._circuit_breaker(status):
            # Context was wiped — rebuild the observation with the fresh notes.
            observation = self._observation_text(status, steer=steer)
        png = self.screenshot_bytes()
        self.emit("observation", {"text": observation})

        user_msg: dict[str, Any] = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"}},
                {"type": "text", "text": observation + "\n\nCall exactly one tool."},
            ],
        }
        with self._lock:
            messages: list[dict[str, Any]] = self._history + [user_msg]

        model = self._meta.model()
        actions: list[dict[str, Any]] = []
        for _ in range(MAX_TOOL_CALLS_PER_TURN):
            if self.should_stop():
                break
            try:
                response = self._llm.chat(
                    messages,
                    model=model,
                    tools=TOOLS,
                    tool_choice="auto",
                    # Keep reasoning models snappy: navigation turns don't need
                    # deep thinking, and effort dominates latency and cost.
                    extra_body={"reasoning": {"effort": "low"}},
                )
            except LLMCallError as exc:
                self.emit("llm_error", exc.to_payload())
                raise
            self._run_cost += response.cost_usd
            raw_msg = response.raw_response.choices[0].message
            tool_calls = raw_msg.tool_calls or []
            self.emit("llm_call", {
                "provider": response.provider,
                "model": response.model,
                "messages": _strip_image_urls(messages[-2:]),
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
                    "cost_usd": response.cost_usd,
                    "run_cost_usd": self._run_cost,
                },
            })
            if not tool_calls:
                if actions:
                    break
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": "Nothing happened — you must call exactly one tool.",
                })
                continue

            messages.append({
                "role": "assistant",
                "content": raw_msg.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._execute_tool(tc.function.name, args)
                actions.append({"tool": tc.function.name, "args": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
            # One tool round per turn is the contract; stop after executing them.
            break

        summary = "; ".join(
            f"{a['tool']}({json.dumps(a['args'], separators=(',', ':'))[1:-1]})"
            + ("" if a['result'].get('error') is None else f" ERROR:{a['result']['error']}")
            for a in actions
        ) or "(no action)"
        self.emit("actions", {"tool_calls": actions, "summary": summary})

        # Cross-turn history: text-only observation + action summary.
        with self._lock:
            if len(self._history) >= 2 and isinstance(self._history[-1].get("content"), list):
                self._history[-1]["content"] = [
                    {k: v for k, v in b.items() if k != "cache_control"}
                    for b in self._history[-1]["content"]
                ]
            self._history.append({"role": "user", "content": self._observation_brief(status)})
            self._history.append({
                "role": "assistant",
                "content": [{"type": "text", "text": summary, "cache_control": {"type": "ephemeral"}}],
            })
            max_msgs = 1 + MAX_HISTORY_TURNS * 2
            if len(self._history) > max_msgs:
                self._history = [self._history[0]] + self._history[-(MAX_HISTORY_TURNS * 2):]

    def _observation_brief(self, status: dict[str, Any]) -> str:
        state = self.state()
        pokemon = state.get("pokemon") or {}
        battle = status.get("battle")
        battle_part = f" BATTLE vs {battle.get('enemy_species')}" if battle else ""
        return (
            f"{status.get('map_name')} ({pokemon.get('x')},{pokemon.get('y')}){battle_part}"
        )


if __name__ == "__main__":
    GymAgent().serve()
