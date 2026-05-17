# Changelog

## 2026-05-17 (agent-history-aware checkpoints — true rewind)

### Added
- `harness/agent.py` — `PokemonAgent.serialize_history() -> dict` and `restore_history(data: dict)` hooks. Default to `{}` / no-op so existing subclasses keep working unchanged. `PokemonAgent.save_state(name)` now calls `serialize_history` and ships the result as `agent_state`; `PokemonAgent.load_state(name)` reads the sidecar from the response and applies it synchronously. UI-initiated loads fan out via the control WS (`load_state:<name>` command); the agent fetches the sidecar via `GET /api/runs/<id>/states/<name>/agent` and calls `restore_history` automatically. Echo dedup via `_last_local_load` (5 s window) keeps the agent from restoring twice when it triggered the load itself.
- `harness/examples/my_agent.py` — overrides `serialize_history` / `restore_history` to round-trip `self._history`, so a UI Load now rewinds the LLM message window along with the emulator.
- `env/models.py` — optional `agent_state: dict | None` field on `SaveStateRequest`.
- `env/runtime.py` — `RuntimeManager.save_state` writes `<name>.agent.json` next to `<name>.state` when `agent_state` is supplied. `load_state` reads the sidecar (or its shared-states counterpart), returns it in the response and includes it in the `state_loaded` event payload. New `read_agent_state(run_id, name)` helper for the GET endpoint.
- `env/app.py` — `GET /api/runs/<run_id>/states/<name>/agent` serves the JSON sidecar. The `/api/load-state` route, after the env load completes, enqueues `load_state:<name>` for every running harness so each agent can restore its own history through the control WS.
- `tests/test_harness_base.py` — coverage for `serialize_history` round-trip and history restoration from a load_state response.
- `tests/test_api.py` — coverage for the sidecar write/read round-trip, null sidecar on plain saves, and the registry fanout on UI-initiated load.

## 2026-05-17 (websocket control loop + registry extraction)

### Added
- `env/harness_registry.py` — `HarnessRegistry` lifted out of `env/app.py`. Same shape, plus a small `has(harness_id) -> bool` helper. `env/app.py` re-imports it (callers `from env.app import HarnessRegistry` keep working).
- `env/app.py` — new `WS /api/harness/{harness_id}/control` endpoint. On connect, the WS drains queued commands and then pushes new ones as they're enqueued via the existing `/play` / `/stop` HTTP routes. Server-side polls the FIFO queue every 50 ms (cheap, no client traffic). Closes with code 4404 for unknown harness ids.
- `harness/agent.py` — `PokemonAgent.serve()` starts a daemon thread (`_ws_loop`) that holds the control WebSocket open and pushes commands onto an in-process queue (`_cmd_queue`). The control loop now blocks on `_cmd_queue.get(timeout=1.0)` instead of polling HTTP. If the WS endpoint isn't supported (404 from older backends), the agent falls back to the previous HTTP poll loop automatically.
- `tests/test_api.py` — three new tests for the control WS (drain-on-connect FIFO ordering, push-after-connect, 4404 close for unknown id).

### Changed
- `tests/test_api.py` — `HarnessRegistry` import now comes from `env.harness_registry` directly instead of via `env.app`.
- Removes the `GET /api/harness/<id>/poll 200 OK` log spam that filled every dev session, and drops Stop-button latency from ~500 ms (worst-case poll interval) to ~5 ms WS dispatch + whatever the agent's own loop slack is.

## 2026-05-17 (run picker + history browser)

### Added
- `env/runtime.py` and `env/app.py` — `GET /api/runs` returning all on-disk runs `[{run_id, modified_at, has_env, has_harness, active}]`, newest first.
- `ui/src/App.tsx`, `ui/src/api.ts`, `ui/src/styles.css` — "View run" dropdown in the trace pane header. Default is the live run; selecting a past run-id loads its env + harness traces from disk and shows them read-only (the dropdown also marks the count line with `viewing <run_id>`). Live WS events continue to drive checkpoint refresh + the active game screen, but are not appended to the trace list while a past run is being inspected.
- `tests/test_api.py` — two new tests for `/api/runs` (active flag, newest-first ordering).

## 2026-05-17 (checkpoint UI + dedup action/button_press)

### Added
- `env/runtime.py` and `env/app.py` — `GET /api/runs/{run_id}/states`, `GET /api/states/shared`, and `DELETE /api/runs/{run_id}/states/{name}` for listing and removing save states. Run-local listings include the `frame` each state was captured at (read from the env trace).
- `ui/src/App.tsx`, `ui/src/api.ts`, `ui/src/styles.css` — Checkpoints panel below the state grid: lists run-local checkpoints (with Load + delete) and shared checkpoints (Load only), one-click Save with auto-named `chkpt-<frame>` default, optional custom name. The panel auto-refreshes on `state_saved` / `state_loaded` WebSocket events.
- `tests/test_api.py` — five new tests for the state listing endpoints (frame enrichment, newest-first ordering, shared listing, delete, path-traversal rejection).

### Changed
- `env/runtime.py` — `button_press` and `button_sequence` env payloads now include `before` and `after` position snapshots `{frame, map_id, x, y}`. The harness no longer needs to emit its own `action` event; one ground-truth env event per press is the new contract.
- `harness/agent.py` — `PokemonAgent.press()` no longer round-trips state twice and emits a duplicate `action` event; it just delegates to the client. Saves two HTTP calls per agent press.
- `ui/src/App.tsx` — `button_press` and `button_sequence` summaries now render the position diff (`map 38 (3,6) → map 38 (3,7)`); the legacy `action` formatter is kept as a fallback for older traces.
- `ui/src/App.tsx` — removed the manual save-state form (input + Save + Load); its functionality is now covered by the Checkpoints panel.

### Removed
- `harness/agent.py` — `_safe_state` and `_position_payload` helpers (only used by the old duplicate action emit, now obsolete).

## 2026-05-17 (per-turn screenshots)

### Added
- `env/runtime.py` and `env/app.py` — per-frame thumbnails persisted to `runs/<run_id>/frames/<frame>.png` whenever an event is appended to the trace; served via `GET /api/runs/<run_id>/frames/<frame>.png`. Disk usage is bounded by dedup-by-frame: multiple events at the same emulator frame share one PNG.
- `env/runtime.py` — `Session.cached_screen_png()` caches the PNG bytes alongside the SHA-256, so thumbnail saves, the live `/api/screenshot.png` endpoint, and `state_payload()`'s screen hash all share a single render per frame (closes review item 2.F).
- `ui/src/App.tsx` and `ui/src/styles.css` — every trace event with a `frame` value renders a small pixel-perfect game thumbnail under its summary; click to toggle between 128px and 256px sizes. This is the missing link between an agent decision and what the agent actually saw.
- `ui/src/api.ts` — `frameThumbnailUrl(runId, frame)` helper.
- `tests/test_api.py` — coverage for the thumbnail endpoint (200 path, 404 path, dedup-by-frame, reset-run clears the frames directory).

### Changed
- `env/trace.py` — `TraceStore.reset_run` now also removes the `frames/` directory for the run, keeping run resets clean.

## 2026-05-17 (unified trace view)

### Added
- `AGENTS.md` — "Project north star" section at the top: optimal UI for observing agent gameplay + debuggability/tracing/checkpoint/rollback as the framing for all future work.
- `TODO.md` — codebase review plan (Tier-1 UI gaps, Tier-2 cross-cutting, Tier-3 hygiene) with detailed suggested actions.
- `ui/src/App.tsx` — env events (button_press, button_sequence, step, state_saved, state_loaded, speed_changed, run_started, run_stopped) are now rendered alongside harness events in the right pane; previously they were silently dropped, leaving no UI window onto ground-truth env actions.
- `ui/src/App.tsx` — `eventCategory()` helper classifies events into six filterable categories: decision, action, state, lifecycle, warning, error.
- `ui/src/App.tsx` and `ui/src/styles.css` — per-row "env" / "agent" source badge and color tones for the new `state` and `error` categories.
- `ui/src/App.tsx` — `refreshTraces` now fetches both env and harness traces from disk and merges them by timestamp (Reload button + initial restore).

### Changed
- `ui/src/App.tsx` — `harnessEvents` state renamed to `events`; trace pane header renamed from "Agent" to "Trace"; ring buffer bumped from 200 to 500 events so faster runs do not truncate the timeline.
- `ui/src/App.tsx` — `playback_frame` events still bump the image version but are skipped from the timeline list (they were already excluded before; now the rule is centralised in `NOISY_EVENT_TYPES`).

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
