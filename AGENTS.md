# AGENTS.md — Non-obvious knowledge for AI agents working on this repo

## Project north star

The ultimate goal is an **optimal UI for observing gameplay and how the Pokemon agent is playing the game** with whatever LLM agent/harness the user chooses. Two pillars:

1. **Observability of the agent.** Show enough detail that a human can follow *what the agent saw, what it decided, and why* on every turn. The UI should be expandable — surface a useful summary by default, allow drilling into the raw payload, prompt, tool calls, screenshot, and reasoning when needed.
2. **Debuggability of the run.** Tracing, structured logging, save states, checkpointing, and rollback are first-class concerns — not afterthoughts. The user should be able to pause, inspect, rewind, branch, and resume a run from any point.

When proposing or making changes, weigh them against these two goals. A change that adds a feature but reduces inspectability or makes debugging harder is a regression. A change that makes a run easier to understand or replay is a win.

## Coding principles for non-trivial tasks

Apply these when tackling TODO items, new features, or refactors. They address the most common failure modes: wrong assumptions, overengineering, sprawling edits, and vague goals.

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

- State assumptions explicitly — if uncertain, ask rather than guess
- Present multiple interpretations — don't pick silently when ambiguity exists
- Push back when warranted — if a simpler approach exists, say so
- Stop when confused — name what's unclear and ask for clarification

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked
- No abstractions for single-use code
- No "flexibility" or "configurability" that wasn't requested
- No error handling for impossible scenarios
- If 200 lines could be 50, rewrite it

**Test:** Would a senior engineer say this is overcomplicated? If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code: don't "improve" adjacent code, comments, or formatting; don't refactor things that aren't broken; match existing style even if you'd do it differently; if you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans: remove imports/variables/functions that *your* changes made unused; don't remove pre-existing dead code unless asked.

**Test:** Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform imperative tasks into verifiable goals:

| Instead of… | Transform to… |
|---|---|
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug" | "Write a test that reproduces it, then make it pass" |
| "Refactor X" | "Ensure tests pass before and after" |

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let the LLM loop independently. Weak criteria ("make it work") require constant clarification.

## Keeping the changelog

After completing any meaningful work, append an entry to `CHANGELOG.md`. Group by date, use Added / Changed / Fixed / Removed sections. Be specific: name the file, what changed, and why if non-obvious.

## Keeping TODO.md

`TODO.md` is only for open work. When a TODO item is completed, remove it from `TODO.md` instead of striking it through, and record the completed work in `CHANGELOG.md`.

## Pokemon Red intro sequence (`scripts/setup.py --create-bedroom-state`)

- Oak's intro has **13 dialogue boxes** before the player naming screen.
- After naming the player there are **6 dialogue boxes** before the rival naming screen.
- Naming preset order — player: `NEW NAME / RED / ASH / JACK`; rival: `NEW NAME / BLUE / GARY / JOHN`. Cursor starts on NEW NAME; one DOWN moves to the first preset.
- The naming screen sets `wIgnoreInputCounter` (~64 frames) on open to prevent accidental selection. Wait at least 200 game frames before pressing DOWN after the screen appears.

## `wait()` values are game frames, not milliseconds

`wait(N)` in `harness/client.py` generates `{"type": "wait", "frames": N}`. The backend calls `emulator.tick(N)` — each tick is one frame at 60 fps. `wait(1700)` ≈ 28 real seconds at 1x speed, but executes instantly at max speed.

## Bedroom save state facts

- Verified position: `map_id=38`, `x=3`, `y=6`.
- East wall is at `x=5` — RIGHT from x=5 is correctly blocked, not a bug.
- `wCurMap` defaults to 38 in RAM from the very first game frame. Seeing `map_id=38` immediately after boot does **not** mean the bedroom loaded; wait until after the full intro completes.
- `wIgnoreInputCounter` cycles between 0–255 during normal bedroom free-roam (step animation counter). This is expected — it does not block movement.

## LLM agent prompting

Models default to pressing A when given a vague prompt. To get movement, explicitly tell the model to prefer direction buttons and only press A for dialogue/menus. See `harness/examples/first_agent.py` for the working prompt.

`response.choices[0].message.content` can be `None` for some model responses (e.g. thinking-mode outputs). Always guard with `or ""`:
```python
raw = (response.choices[0].message.content or "").strip()
```

## Harness lifecycle

- Each `FirstAgent()` instance gets a generated run ID in `__init__`. Play resumes the active emulator run if one exists; Reset stops the env run, clears the turn counter, and generates a fresh run ID for the next Play.
- Stale harness registrations (`status="stopping"` that never resolves) are from dead processes. Select a different entry in the dropdown with `status="idle"`.
- After a harness errors, `_run_wrapped` sets status to "error" then "idle". The control loop keeps running — click Play again to restart without restarting the process.

## PyBoy button press duration

`press(button, frames=8)` holds the button for 8 frames. A full tile step in Pokemon Red takes ~16 frames. Eight frames is enough to register movement but the coordinate in memory may not update until the tile transition completes; the next `state()` call sees the new position.

## Turn context API

`PokemonAgent.turn()` is a context manager that groups all activity in one logical turn. The framework handles trace correlation, WebSocket delivery, and `meta.json` maintenance automatically.

Intended use:
```python
with self.turn(goal="leave the bedroom"):
    state = self.state()
    self.emit("observation", {"pokemon": state["pokemon"]})
    self.emit("decision", {"action": "RIGHT", "reasoning": "Moving toward the exit."})
    self.press("RIGHT")
```

**Do not pass `turn_id` manually** in the happy path. `emit`, `press`, `wait`, and `sequence` inherit the current turn ID via `contextvars.ContextVar` — no threading required.

`turn_id` is only useful for advanced/debug cases (e.g. manually correlating events from a helper outside the with-block).

**Nested turns raise `RuntimeError`.** There is no parent/child span tree in v1.

Turn IDs are auto-generated as `turn-001`, `turn-002`, etc. and reset to 0 when a new run starts. An explicit `turn_id` may be passed for deterministic test setups.

## meta.json lifecycle

`runs/<run_id>/meta.json` is written by the env backend — agent code never writes it. Fields:
- `status`: `"running"` while env session is active; `"stopped"` after `stop_run`.
- `turns`: incremented by 1 each time a `turn_finished` event is received.
- `last_turn_summary`: taken from `turn_finished.payload.goal` or `status`.
- `agent`: populated from the harness registry record at run-start time.
- `rom`: populated from the loaded ROM metadata.

To expose agent and model info in meta.json, set class attributes before calling `serve()`:
```python
class FirstAgent(PokemonAgent):
    name = "First Agent"
    model = "qwen/qwen3.6-flash"
```
