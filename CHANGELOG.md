# Changelog

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
