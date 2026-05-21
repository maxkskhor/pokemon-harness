# Changelog

## 2026-05-22 (Tool Agent bedroom loop fixes)

### Fixed
- `harness/examples/tool_agent.py` — plain-text LLM responses such as `move LEFT` no longer silently become successful no-op turns. The agent now injects a current-turn user reminder that plain text is ignored and retries for an actual tool call without writing that reminder or failed text into the cached cross-turn history.
- `harness/examples/tool_agent.py` — `move()` tool results now include `before`, `after`, and boolean `moved` fields after a short settle wait, reducing false "blocked" feedback from reading state too soon after a direction press.
- `harness/examples/tool_agent.py` — agent turns temporarily pause emulator playback and restore the previous speed afterward, so LLM thinking and tool execution do not race the background playback loop.

### Added
- `harness/examples/tool_agent.py` — lightweight stuck-loop detection for repeated no-action turns, unchanged positions, and repeated failed directions; reminders are added only to the fresh user message for that turn.
- `tests/test_tool_agent.py` — regression tests for settled move results, current-turn-only tool-call reminders, speed pause/restore, and repeated failed-direction reminders.

## 2026-05-21 (run_stopped UI race)

### Fixed
- `ui/src/App.tsx` — WebSocket `run_stopped` handler now returns early after clearing state. Previously it fell through to the "new-run-detected" block, which re-anchored `eventRunIdRef.current` to the just-stopped run id. Combined with the race below, this left the View Run picker showing "Active – <stopped-id>" for several seconds after Stop until the next reload.
- `ui/src/App.tsx` — `refreshState` now captures `eventRunIdRef.current` at fetch-start and drops the result if `run_stopped` cleared it during the await. Without this guard, a late-resolving `getState()` from the `state_saved` event (emitted just before `run_stopped` while writing `_auto_resume`) repopulated state with the just-stopped run's data, because the backend leaves `self.session` set until after `emit_env("run_stopped")` returns.

## 2026-05-21 (Start/Resume label fix)

### Fixed
- `ui/src/App.tsx` — Dropping an agent in the dropdown no longer flips the primary action to "Resume agent". The label is now driven solely by the View Run picker: dropdown selection → "Start agent" (fresh run from `bedroom`); past run picked in View Run → "Resume agent" (branches from that run's checkpoint). The previous `resumableRun` auto-detection (any past stopped run with `_auto_resume` matching the selected agent's name) was silently hijacking new-run intent when an old snapshot for the same agent name still existed.

### Changed
- `ui/src/App.tsx` — `handleHarnessResume` now requires `viewedRunId`; the resume-after-Stop shortcut goes through the View Run picker instead. Stop still writes `_auto_resume` so the run remains resumable from the picker.

## 2026-05-21 (verification-feedback fixes)

### Fixed
- `ui/src/App.tsx` — On page reload, auto-select the harness whose `name` matches the active run's recorded agent (one-shot, via `autoSelectAttemptedRef`). Resolves the issue where Stop was disabled after reload because the dropdown defaulted to the first agent instead of the running one. Per AGENTS.md, Stop only targets the dropdown selection.
- `ui/src/App.tsx` — WebSocket handler treats `run_stopped` as an explicit teardown: clears local state, image version, and event run id directly. Eliminates the post-Stop `GET /api/state` and `GET /api/screenshot.png` 404s that previously appeared in the browser console after the env session closed.

### Changed
- `verify.md` — Updated wording: button labels no longer require literal `▶`/`↺` glyphs (UI uses lucide-react SVG icons); the post-resume run picker label is correctly `View run: Active – <id>`. Added a triage section labelling each item from the manual-verification feedback as FIXED / DOCS-UPDATED / WONT-FIX.

## 2026-05-21 (verification notes)

### Added
- `verify.md` — recorded local UI verification results for the resume/start/stop/reset checklist, including passing flows, incomplete checks, and follow-up issues found during browser testing.

## 2026-05-21 (resume-from-run polish)

### Added
- `env/runtime.py` — `list_runs()` now emits `has_auto_resume` (specifically tracks the Stop snapshot, not any save state). Drives the UI's Start↔Resume label so stray user-saved checkpoints don't change the primary action.
- `harness/agent.py` — Tracks `_active_turn_id` so the control thread can synthesize a `turn_finished` event if Stop fires while the run thread is mid-turn (UI no longer leaves the turn stuck on "running").
- `harness/client.py` — `delete_run_state()` (best-effort) and `list_runs()` helpers used by Reset.

### Changed
- `harness/agent.py` — Stop join timeout raised from 10 s to 30 s so a typical mid-flight LLM call has time to finish, the `turn()` block runs its `finally`, and `turn_finished` reaches the env while the session is still alive.
- `harness/agent.py` — `_run_wrapped()` suppresses error emission when `_stop_event` is already set; the resulting 404 from a press after `stop_run()` is an expected shutdown signal, not a user-visible error.
- `harness/agent.py` — Reset now wipes `_auto_resume` for every past run belonging to this agent's name (not just the current run id), so the UI primary action flips back to "Start agent".
- `ui/src/App.tsx` — Primary action button now reads "Start agent" (no resumable state) or "Resume agent" (selected agent has a stopped run with `has_auto_resume`); resume defaults to the auto-snapshot of that most-recent run. Stop and Reset re-fetch run history so the label updates immediately.
- `ui/src/trace/TurnCard.tsx` — Thumbnail uses the turn's start frame (not finish frame) so the image stays stable instead of switching when the turn transitions from running→ok.

## 2026-05-21 (resume from a previous run)

### Added
- `env/app.py` — `POST /api/harness/{id}/resume_run` endpoint that branches a fresh run from a saved checkpoint of a past run; validates that the selected harness's agent name matches the source run's recorded agent.
- `env/runtime.py` — `RuntimeManager.resume_from_checkpoint()` opens a new session under a fresh `run_id`, loads the source run's `.state` directly, and writes `parent_run_id` + `parent_checkpoint` into the new meta.
- `env/runtime.py` — `list_runs()` now emits `has_checkpoints`, `parent_run_id`, and `parent_checkpoint` for each entry.
- `env/models.py` — `HarnessResumeRequest` Pydantic model.
- `harness/agent.py` — Control-loop handler for the new `resume_run:<new>:<source>:<checkpoint>` command; restores agent history from the source's `.agent.json` sidecar before spawning the run thread.
- `ui/src/api.ts` — `resumeHarness()` client + `has_checkpoints`/`parent_run_id`/`parent_checkpoint` fields on `RunSummary`.
- `ui/src/App.tsx` — When viewing a past run, the Play button re-labels to **Resume agent** and disables with a tooltip until the dropdown selects the matching agent; clicking it branches a new run from `_auto_resume` (or the newest checkpoint if no auto-snapshot exists).
- `ui/src/run-picker/RunPicker.tsx` + `styles.css` — `↺` badge on past runs that have saved checkpoints.

### Changed
- `harness/agent.py` — Stop command now writes an `_auto_resume` snapshot (emulator + agent history) and calls `stop_run()` (was `pause_run()`). This terminates the env session so switching harnesses no longer lets the new agent silently inherit the previous session's state.
- `ui/src/App.tsx` — `handleSelectRun` now refreshes checkpoints and frames when a past run is selected, so the Checkpoints sidebar reflects the viewed run instead of staying empty.

## 2026-05-19 (abstract frames from agent API)

### Changed
- `harness/agent.py` — `PokemonAgent.press(button)` no longer takes a `frames` parameter. Direction buttons automatically hold for 16 frames (full tile animation); action buttons hold for 8. Screenshots taken immediately after a move now always show the character settled on the new tile.
- `harness/agent.py` — Removed `PokemonAgent.wait()`. It was frame-based and not needed in agent code.
- `harness/client.py` — Module-level `press(button, frames=None)` auto-selects frame duration when called without `frames`; explicit frames still accepted for `scripts/setup.py` and sequence builders.
- `harness/__init__.py` — `wait` removed from public exports; still importable from `harness.client` for low-level use.
- `harness/examples/tool_agent.py` — `get_state` tool response no longer includes the `frame` counter.
- `README.md`, `AGENTS.md` — Updated agent API reference to reflect removed `frames`/`wait` surface.

## 2026-05-19 (fix Stop/Play lifecycle)

### Added
- `env/runtime.py` — `pause_run()` pauses the emulator playback loop without destroying the session; `resume_run()` restarts it. Keeps run ID and game state intact across Stop/Play cycles.
- `env/app.py` — `POST /api/run/pause` and `POST /api/run/resume` endpoints.
- `harness/client.py` — `pause_run()` and `resume_run()` client methods.

### Fixed
- `harness/agent.py` — Stop command now calls `pause_run()` instead of `stop_run()`. The emulator session stays alive so the next Play resumes the same run (same run_id, continuing trace) instead of creating a new one.
- `env/runtime.py` — `harness_event()` no longer returns 404 when there's no active session; lifecycle events emitted after stop are silently accepted.
- `ui/src/App.tsx` — Clicking "Play agent" now switches the trace view to the live run, so the user is never left watching a past run while the agent is active.

## 2026-05-19 (fix stale Running status)

### Fixed
- `env/runtime.py` — `RuntimeManager.__init__` now calls `_heal_stale_runs()` on startup, marking any runs left as `"running"` from a previous server process as `"stopped"`. Prevents ghost "Running" entries after a crash or kill.
- `harness/agent.py` — `_control_loop` "stop" command now calls `self._client.stop_run()` after the run thread finishes, so `meta.json` is written with `status: "stopped"` and `ended_at`. Previously only "reset" did this.
- `env/harness_registry.py` — `register()` now reuses an existing `idle` or `disconnected` entry with the same name instead of always creating a new one. Prevents duplicate agent entries accumulating in the UI dropdown when the harness restarts.

## 2026-05-19 (docs gardening)

### Changed
- `TODO.md` — restored it to an open-work list and moved the remaining future-work notes into it.
- `AGENTS.md` — updated stale setup, reset/run lifecycle, and model-string notes.
- `README.md` — documented agent `model` metadata and checkpoint sidecar hooks for agent history.
- `docs/architecture.md` — refreshed runtime artifact notes and the current API endpoint list.

### Removed
- `IDEA.md` — removed the duplicate future-work scratch file now that open items live in `TODO.md`.

## 2026-05-19 (Reset button)

### Added
- `env/app.py` — `POST /api/harness/{id}/reset` endpoint; enqueues a "reset" command to the harness.
- `harness/agent.py` — handles "reset" command in `_control_loop`: stops agent loop, calls `stop_run()` to close the env session, resets turn counter and run ID so the next Play starts fresh from the bedroom save state.
- `ui/src/api.ts` — `resetHarness()` API function.
- `ui/src/App.tsx` — "Reset" button (with RotateCcw icon) in the agent controls; enabled whenever a harness is connected and not disconnected.

## 2026-05-19 (README screenshot)

### Added
- `.gitignore` — allowed committed PNG assets under `docs/assets/` while keeping ad hoc development screenshots ignored.
- `docs/assets/demo-page.png` — added the current UI screenshot for README display; replace this file when the UI demo image needs refreshing.
- `README.md` — embedded the demo screenshot near the top of the page so visitors can see the gameplay and trace UI before setup.

## 2026-05-19 (rename my_agent → first_agent)

### Changed
- `harness/examples/my_agent.py` → `harness/examples/first_agent.py`; class `MyAgent` → `FirstAgent`; `name = "First Agent"`.
- `tests/test_my_agent.py` → `tests/test_first_agent.py`; removed tests for `_extract_reasoning` / `_strip_think_tags` (those are `harness.llm` internals, not part of the agent interface).
- `README.md`, `AGENTS.md` — updated all references.

## 2026-05-19 (trace cleanup and harness simplification)

### Fixed
- `ui/src/styles.css` — turn cards were crushed to 2px height by the flex algorithm (`.trace-list` is a flex column; `.turn-card` lacked `flex-shrink: 0` so all cards compressed to just their 1px border on each side). Added `flex-shrink: 0` to make cards their natural height.
- `harness/examples/my_agent.py` — agent was manually constructing `turn_id` strings and passing them to `emit()` directly instead of using `with self.turn()`. This meant no `turn_started`/`turn_finished` events were emitted (all turns showed "running" forever), and `press()` was called outside the turn context so `button_press` env events had no `turn_id` and landed in the Session group. Rewrote `run()` to use `with self.turn(goal=...)` so all three are fixed: proper status, elapsed time, goal text, and button_press events grouped inside their turn cards.

### Removed
- `harness/agent.py` — removed `_http_poll_loop()` and the 404-fallback logic from `_ws_loop()` that existed for older backends without WebSocket support.
- `runs/` — deleted all accumulated trace runs; start fresh.

## 2026-05-19 (one-command setup)

### Added
- `scripts/setup.sh` — added a first-time setup wrapper that installs Python/UI dependencies, builds local ROM artifacts, starts a temporary backend if needed, and creates the default `bedroom` save state.
- `scripts/setup.py` — moved the bedroom-state automation behind the setup command as an internal helper.

### Changed
- `README.md` — replaced the separate dependency, ROM build, backend start, and bedroom setup steps with `scripts/setup.sh`.
- `harness/examples/my_agent.py` — updated the usage comment to point first-time users at `scripts/setup.sh`.

### Removed
- `scripts/setup_bedroom.py` — removed the standalone bedroom setup entry point so first-time setup has one public command.

## 2026-05-19 (README visibility cleanup)

### Added
- `docs/architecture.md` — moved repository layout and provider-neutral API endpoint notes out of the README so public setup instructions stay focused.

### Changed
- `README.md` — rewrote the README around the developer evaluation path: concise project description, features, requirements, setup, launch, custom-agent example, LLM providers, useful commands, legal boundary, and license.
- `README.md` — removed Codex-specific `UV_CACHE_DIR=/private/tmp/uv-cache` from public setup commands.
- `README.md` — clarified platform expectations as macOS/Linux/WSL, with native Windows currently unverified.

## 2026-05-19 (UI cleanup: remove emulator controls, fix LLM filter, add screenshot toggle)

### Changed
- `ui/src/App.tsx` — removed emulator "Reset run" / "Stop run" buttons from header (runs are started by the agent harness process); removed ROM and Symbols from status bar; added "Emulator speed" label with tooltip on "paused"; added `showImages` state passed to trace components.
- `ui/src/trace/TraceFilters.tsx` — added "screenshots" toggle to show/hide thumbnails in the trace.
- `ui/src/trace/TraceList.tsx` — passes `filters` and `showImages` to `TurnCard`; `TraceItem` and `SessionGroup` respect `showImages` for thumbnail display.
- `ui/src/trace/TurnCard.tsx` — applies event filters to the expandable raw-events list (fixes LLM filter not affecting turn events); respects `showImages` toggle for turn thumbnails.
- `ui/src/styles.css` — added `.speed-label` for the speed controls label; `.trace-filter-divider` for the screenshots toggle separator.

### Fixed
- LLM filter checkbox now hides/shows `llm_call` events inside expanded TurnCard raw event lists (previously only affected session-level events).

## 2026-05-19 (turn-context observability + run metadata)

### Added
- `harness/client.py` — `_current_turn_id` ContextVar + `get_current_turn_id()` shared helper; `press_button`, `wait`, `press_sequence`, `emit` automatically inherit the active turn ID without caller plumbing.
- `harness/agent.py` — `turn()` context manager: auto-generates `turn-001`/`turn-002` IDs, emits `turn_started`/`turn_finished` boundary events with goal, frame, elapsed_ms, status; guards nested turns with RuntimeError; resets ContextVar on exit.
- `harness/agent.py` — `model` class attribute for agent authors; `name`/`model` forwarded to harness register request.
- `env/models.py` — `turn_id` field on `PressAction`, `SequenceAction`, `StepRequest`; `harness_id`/`start_state` on `StartRunRequest`; `model`/`metadata` on `HarnessRegisterRequest`.
- `env/runtime.py` — `Session.emit_env` accepts `turn_id`; `press`, `sequence`, `step` propagate request's `turn_id` into env trace rows. `_write_meta`, `_patch_meta`, `_load_meta` helpers; `start_run` writes `meta.json`; `stop_run` updates status/ended_at; `harness_event` increments turns/last_turn_summary on `turn_finished`; `list_runs` merges meta.json fields.
- `env/harness_registry.py` — `register` now stores `model` and `metadata`.
- `env/app.py` — `/api/run/start` resolves harness record and passes agent_info to start_run; `/api/harness/register` forwards model/metadata.
- `ui/src/trace/TurnCard.tsx` — new turn-summary card component with status badge, elapsed time, goal, thumbnail, decision/action summary, position delta, LLM usage, reasoning, expandable raw events, and checkpoint affordances (load near this turn / save checkpoint here).
- `ui/src/styles.css` — styles for active-run pill, turn cards, run comparison table.

### Changed
- `ui/src/trace/TraceList.tsx` — turn-first rendering: events grouped into turn cards + Session group for unturn'd events.
- `ui/src/run-picker/RunPicker.tsx` — replaced dropdown with collapsible comparison table showing status, agent, model, turns, last turn summary, started time, and size.
- `ui/src/api.ts` — `RunSummary` extended with meta.json fields (status, started_at, ended_at, turns, last_turn_summary, agent, rom, start_state).
- `ui/src/App.tsx` — active run shows read-only pill instead of editable input; "Reset run" uses `state.run_id` so it cannot drift; passes checkpoint props to TraceList for turn-card affordances.
- `AGENTS.md` — documented turn context API and meta.json lifecycle.

### Fixed
- `harness/agent.py` — `_count_existing_turns` now validates the harness-trace response shape before counting `turn_finished` events, keeping active-run resume typed and tolerant of unexpected API responses.

### Tests
- `tests/test_harness_base.py` — added FakeClient `start_run` signature update; added 7 turn-context unit tests (started/finished events, ID increment, explicit ID, nested turn error, exception status, context reset, turn-ID inheritance by press).
- `tests/test_api.py` — added tests: press/step/sequence with turn_id write to env trace; meta.json written on start, updated on stop, turns increment on turn_finished, list_runs includes meta fields; harness register stores model/metadata.

## 2026-05-19 (turn-context observability plan)

### Added
- `TODO.md` — added a detailed implementation plan for turn-context observability, backend-owned run metadata, turn summary cards, active-run UX cleanup, run comparison, and branch/rewind affordances. The plan explicitly keeps the agent-author API high-level so harness users do not need to manage WebSockets, streaming, playback frames, trace merging, or metadata files.

### Changed
- `TODO.md` — expanded each planned implementation area with concrete verification gates so future implementation can prove when the feature is successfully built.

## 2026-05-17 (agent play resume)

### Changed
- `harness/agent.py` — agent Play now resumes an active emulator run instead of always creating a fresh run and reloading the configured starting save state.
- `ui/src/App.tsx` — the emulator start control now reads `Reset run` while a run is active, making the explicit restart path clearer.

### Added
- `tests/test_harness_base.py` — regression coverage for agent Play resuming an active run and only starting/loading the initial state when no emulator run exists.

## 2026-05-17 (LLM client retry layer)

### Added
- `harness/llm.py` — added a reusable LLM client with provider presets, OpenAI-compatible provider adapter, retry/backoff for 429/5xx/network failures, normalized response metadata, and structured `LLMCallError` payloads.
- `tests/test_llm_client.py` — added regression coverage for retry success, retry exhaustion, and non-retryable provider errors.
- `README.md` — documented the reusable LLM client and provider extension points for future OpenAI-compatible or custom adapters.

### Changed
- `harness/examples/my_agent.py` — replaced the direct OpenRouter SDK call with `LLMClient`, and now emits provider name plus retry attempt count in `llm_call` traces.
- `harness/__init__.py` — exported the reusable LLM client helpers for future harnesses.
- `tests/test_my_agent.py` — updated the example-agent tests around the reusable client and added coverage that exhausted LLM failures emit `llm_error` before surfacing.
- `ui/pokemon-harness-smoke.spec.js` — changed the initial page wait from `networkidle` to `domcontentloaded`, removed the stale RIGHT-button click now that the UI is observation-only, and aligned the screen-size assertion with the wider trace pane.

## 2026-05-17 (UI refinements)

### Changed
- `ui/src/App.tsx`, `ui/src/styles.css` — removed manual D-pad, A/B/START/SELECT game buttons, and 30-frame step button; the UI is observation-only now.
- `ui/src/styles.css` — widened trace pane to 60% of viewport (was a fixed ~430px cap) to give more room for event inspection.
- `ui/src/App.tsx` — changed default trace filters: `state` and `lifecycle` now off by default; `decision`, `llm`, `action`, `warning`, `error` remain on.

## 2026-05-17 (post-review followups)

### Fixed
- `scripts/verify.sh` — removed the leftover hard-coded `UV_CACHE_DIR=/private/tmp/uv-cache` prefix that the 2026-05-17 correctness pass missed when it cleaned up `scripts/dev.sh`.
- `harness/examples/my_agent.py` — guard `self._history` with a `threading.Lock` so `restore_history` (control-loop thread, WS-triggered) cannot interleave with `run()`'s appends/rolling-window resize on the run thread. Snapshot the history before each LLM call so an in-flight `chat.completions` request can't trip over a concurrent rewind either.

### Changed
- `harness/agent.py` — comment the implicit `self._run_id` ↔ env `session.run_id` coupling that makes the WS-load sidecar lookup correct, so it stays load-bearing if anyone ever decouples them.
- `env/trace.py` — annotate `now_iso()` and the `since_timestamp` compare in `TraceStore.read()` to spell out that lexicographic ordering is only safe because every timestamp on disk comes from `now_iso()` (fixed-width UTC ISO 8601 with `+00:00`).
- `env/app.py` — note in the control WS loop that the 50 ms `asyncio.sleep` is a deliberate choice; switching to a per-harness `asyncio.Event` signalled from `enqueue()` is the eventual upgrade path but isn't worth the cross-thread plumbing yet.

## 2026-05-17 (TODO completion sweep)

### Added
- `env/runtime.py`, `env/app.py`, `ui/src/api.ts`, `ui/src/checkpoints/FrameScrubber.tsx`, `ui/src/styles.css` - added frame listing plus a frame scrubber under the emulator screen. Scrubbing previews persisted thumbnails without mutating emulator state; rewind loads the nearest prior checkpoint so visual preview and actual rollback stay honest.
- `harness/examples/my_agent.py`, `ui/src/trace/TraceList.tsx`, `ui/src/trace/helpers.ts` - added sanitized `llm_call` trace events with prompt messages, response, token usage, and latency, plus a filterable trace category and expandable call details.
- `env/harness_registry.py`, `env/app.py`, `env/models.py`, `harness/agent.py`, `harness/client.py` - added registry `last_seen_at`, stale-disconnect pruning, `runs/registry.json` persistence, startup hydration with live statuses downgraded to `disconnected`, and UI status display for disconnected agents.
- `env/trace.py`, `env/runtime.py`, `env/app.py`, `ui/src/api.ts` - added `since_timestamp` / `limit` trace reads and incremental UI reloads for larger traces.
- `pyproject.toml`, `ui/eslint.config.js`, `ui/.prettierrc.json`, `ui/package.json`, `scripts/verify.sh` - added Pyright, ESLint, Prettier config, and verification wiring.
- `ui/src/trace/`, `ui/src/checkpoints/`, `ui/src/run-picker/` - split trace rendering, checkpoint controls, the frame scrubber, and the run picker out of `ui/src/App.tsx`.
- `tests/test_api.py`, `tests/test_my_agent.py` - regression coverage for frame lists, paginated trace reads, registry stale/persistence behavior, and sanitized LLM telemetry.

### Changed
- `ui/src/App.tsx` - reduced to the composition/root state owner after moving repeated UI surfaces into focused modules.
- `TODO.md` - removed completed work items; the file now records no open TODOs.

## 2026-05-17 (correctness and DX cleanup)

### Added
- `scripts/clean-runs.sh` — dry-run capable cleanup script for removing `runs/<id>/` and matching `states/<id>/` directories older than a configurable age, skipping `shared`.
- `ui/playwright.config.ts`, `ui/package.json`, `scripts/verify.sh` — wired `npm run test:smoke` through Playwright with backend/frontend web servers, and added it after the production build in full verification.
- `tests/test_replay.py` — replay regression coverage that `replay_marker` events are emitted before replayed actions.

### Changed
- `env/models.py`, `env/runtime.py` — safe-name validation now uses `env.trace.ensure_safe_name` consistently. State and agent-side state paths resolve under `states_dir` before use for defense-in-depth against traversal.
- `harness/agent.py`, `tests/test_harness_base.py`, `tests/test_my_agent.py` — `PokemonAgent` accepts an optional `client_factory`, so tests inject fake clients without assigning to private `_client`.
- `harness/replay.py` — emits a `replay_marker` harness event before each replayed env action, carrying the source run id, source frame, and source event type.
- `scripts/dev.sh` — no longer hard-codes `UV_CACHE_DIR=/private/tmp/uv-cache`; it now respects the caller's environment.
- `README.md`, `harness/examples/my_agent.py` — document module-form example-agent invocation (`python -m harness.examples.my_agent`) and correct the README agent base-class import.
- `harness/__init__.py`, `README.md` — export and document the `press()` / `wait()` helper builders for `sequence()` payloads.
- `env/runtime.py`, `ui/src/api.ts`, `ui/src/App.tsx` — run summaries now include on-disk byte size and the run picker displays it.
- `ui/src/styles.css` — compacted the desktop state grid and checkpoint panel so the emulator screen keeps priority on the 1440×900 smoke viewport.
- `ui/pokemon-harness-smoke.spec.js` — cleans up its temporary run/state directories after execution.

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
