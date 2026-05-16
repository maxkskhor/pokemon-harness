# AGENTS.md — Non-obvious knowledge for AI agents working on this repo

## Keeping the changelog

After completing any meaningful work, append an entry to `CHANGELOG.md`. Group by date, use Added / Changed / Fixed / Removed sections. Be specific: name the file, what changed, and why if non-obvious.

## Pokemon Red intro sequence (setup_bedroom.py)

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

Models default to pressing A when given a vague prompt. To get movement, explicitly tell the model to prefer direction buttons and only press A for dialogue/menus. See `harness/examples/my_agent.py` for the working prompt.

`response.choices[0].message.content` can be `None` for some model responses (e.g. thinking-mode outputs). Always guard with `or ""`:
```python
raw = (response.choices[0].message.content or "").strip()
```

## Harness lifecycle

- Each `MyAgent()` instance gets a fixed `run_id` (set in `__init__`). Re-playing the same harness reuses the same run_id — the UI trace list appends rather than clearing.
- Stale harness registrations (`status="stopping"` that never resolves) are from dead processes. Select a different entry in the dropdown with `status="idle"`.
- After a harness errors, `_run_wrapped` sets status to "error" then "idle". The control loop keeps running — click Play again to restart without restarting the process.

## PyBoy button press duration

`press(button, frames=8)` holds the button for 8 frames. A full tile step in Pokemon Red takes ~16 frames. Eight frames is enough to register movement but the coordinate in memory may not update until the tile transition completes; the next `state()` call sees the new position.
