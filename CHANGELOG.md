# Changelog

## 2026-05-17 (docs gardening)

### Added
- `LICENSE` — MIT license.
- `README.md` — License section linking to LICENSE file.
- `README.md` — Harness API table now includes `wait()`, `sequence()`, `save_state()`, `load_state()`, and the `turn_id` parameter on `emit()`.
- `README.md` — documented `harness/replay.py` under a new "Other utilities" subsection.

### Removed
- `harness/examples/starter_route.py` — unused standalone script that bypassed the `Harness` base class; moved nothing, just deleted.

## 2026-05-16 (session 3)

### Added
- `harness/harness.py` — public `wait()`, `sequence()`, `save_state()`, and `load_state()` helpers so harness authors do not need to reach into `self._client`.
- `env/app.py` — `HarnessRegistry` class with FIFO command queues, allowing rapid Play then Stop commands to be polled in order.
- `ui/src/App.tsx` and `ui/src/styles.css` — trace event filters, turn/session grouping, trace event count, reload-from-disk button, inter-event delta times, and expandable trace rows.
- `tests/test_harness_base.py` and `tests/test_api.py` — regression coverage for the new harness helpers, full traceback emission, FIFO command polling, and cached screen hashes.

### Changed
- `harness/harness.py` — each Play command now creates a fresh harness run id, so UI trace state resets between replays.
- `ui/src/App.tsx` and `ui/src/styles.css` — Emulator Start/Stop controls are visually/textually separated from Agent Play/Stop controls; the WebSocket indicator now has an explicit label.
- `ui/src/App.tsx` and `ui/src/styles.css` — trace item expansion is limited to the header row and reasoning is collapsed to two lines by default with its own toggle.
- `TODO.md` — removed completed TODO entries; the completed work is now recorded in this changelog.

### Fixed
- `harness/harness.py` — `_run_wrapped()` now captures the full traceback, prints it to stderr, and emits it as a harness `error` trace event before returning to idle.
- `env/runtime.py` — `screen.sha256` is cached by frame and invalidated after emulator mutations, avoiding redundant screenshot rendering on repeated `GET /api/state` calls.
- `ui/src/App.tsx` — state-grid metric values now expose full values via `title` tooltips when truncated.
- `ui/src/api.ts` and `ui/src/App.tsx` — startup now checks `/api/health` before fetching `/api/state`, avoiding expected 404 console noise when no run exists.
- `ui/pokemon-harness-smoke.spec.js` — updated the smoke test selector to match the clearer `Start run` control label.

## 2026-05-16 (session 2)

### Added
- `harness/examples/my_agent.py` — rolling conversation history (last 5 turns) passed to the LLM each turn so the model retains context across steps.
- `harness/examples/my_agent.py` — reasoning token extraction: tries `message.reasoning` attribute, `model_extra["reasoning"]`, then `<think>...</think>` tags in content. Emits extracted reasoning under `payload.reasoning` key.
- `harness/examples/my_agent.py` — `_extract_reasoning()` and `_strip_think_tags()` helper functions; structured system prompt + per-turn user messages with just the latest screenshot.
- `tests/test_my_agent.py` — 14 unit tests covering reasoning extraction (3 methods + edge cases), think-tag stripping, history growth, history cap at `MAX_HISTORY_TURNS`, multi-turn message ordering, reasoning in emit payload, and user message format.

### Changed
- `ui/src/App.tsx` — `eventLabel()`: removed `f####` frame number prefix; labels now show `turn-001 decision` instead of `f1234 turn-001 decision`.
- `ui/src/App.tsx` — `summarizeEvent()` for `decision`: removed x/y location string; now just "Chose UP".
- `ui/src/App.tsx` — `summarizeEvent()` for `action`: reformatted to tool-call style `press_button(UP, frames=8) — map 38 (3,6) → map 38 (3,5)`.
- `ui/src/App.tsx` — `formatPosition()`: removed frame number from position display; shows `map N (x,y)` instead of `fN map N x/y X/Y`.
- `ui/src/App.tsx` — `TraceItem`: reasoning now keyed on `reasoning`/`thought`/`thinking`/`raw_thought` (removed `raw_response` fallback to avoid showing the button name as a thought).
- `harness/examples/my_agent.py` — `emit("decision")` payload no longer includes `map_id`, `x`, `y` (those are state data, not agent output); includes `reasoning` and `raw_response` (think-tags stripped).

## 2026-05-16

### Added
- `ui/pokemon-harness-smoke.spec.js` and `ui/package.json` — Playwright browser smoke test for starting a run, pressing RIGHT, checking console errors, and verifying the enlarged game screen dimensions.
- `tests/test_harness_base.py` — regression coverage that `Harness.press()` emits a structured `action` event with before/after position data.
- `harness/harness.py` — `Harness` base class: `run()` override, `screenshot_bytes()`, `state()`, `press()`, `emit()`, `should_stop()`, `serve()`. Handles register/poll/play/stop lifecycle with the backend automatically.
- `harness/examples/my_agent.py` — minimal vision agent using qwen3.6-flash via OpenRouter. Captures screenshot, asks LLM for next button, presses it, emits decision event.
- `scripts/setup_bedroom.py` — one-time script to boot the game at max speed, navigate the full intro (13 Oak boxes, player name RED, 6 post-naming boxes, rival name BLUE), verify free-roaming movement in all 4 directions, and save `states/shared/bedroom.state`.
- `AGENTS.md` — non-obvious domain knowledge for AI agents: Pokemon Red timing, bedroom state facts, LLM prompting gotchas, harness lifecycle quirks.
- `CLAUDE.md` — links to AGENTS.md.
- `.env.example` — documents required env vars (`OPENROUTER_API_KEY`).
- README Quick Start section at top.

### Changed
- `AGENTS.md` — documented the TODO convention: `TODO.md` should contain only open work; completed items are removed and recorded here instead of being struck through.
- `TODO.md` — removed completed items now that the corresponding work is recorded in this changelog.
- **Harness logs** (`harness/harness.py`, `harness/examples/my_agent.py`, `ui/src/App.tsx`): harness lifecycle and button presses now emit visible events; model responses are preserved in decision payloads; the UI renders chronological chat-style rows with summaries, payload expansion, and a running/waiting indicator.
- **Backend** (`env/app.py`, `env/models.py`, `env/runtime.py`): harness registry now tracks timestamps, accepts the `starting` status, validates status values, and writes structured env/harness events to backend logs for debugging.
- **UI layout** (`ui/src/styles.css`): widened the game pane, fixed the trace pane width, and let the emulator image fill the available left-panel space.
- **Backend** (`env/app.py`): harness registry endpoints — `POST /api/harness/register`, `GET /api/harness/list`, `POST /api/harness/{id}/play`, `POST /api/harness/{id}/stop`, `GET /api/harness/{id}/poll`, `POST /api/harness/{id}/status`, `POST /api/harness/{id}/error`, `POST /api/harness/{id}/unregister`.
- **UI** (`ui/src/App.tsx`): replaced env log panel with harness event panel; added harness dropdown, Play/Stop buttons, status badge, error display; WebSocket auto-reconnect; state auto-restore on page load.
- **UI** (`ui/src/styles.css`): fixed-height viewport layout (no page scroll); game screen grows to fill space.
- `.gitignore`: added `.playwright-mcp/` and `*.png`.

### Fixed
- `ui/src/App.tsx` — added explicit accessible labels to D-pad icon buttons after browser testing showed RIGHT/LEFT/UP/DOWN could not be targeted by role/name.
- `setup_bedroom.py`: corrected Oak intro count (was 10, needs 13) and rival advance count (was 5, needs 6) — old states were saved mid-intro and blocked all player movement.
- `my_agent.py`: guard `response.choices[0].message.content or ""` — some model responses return `None` content and would crash the agent loop.
