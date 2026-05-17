# TODO

Tasks are labelled with effort: **Easy** (≤ ~1 hr, mostly mechanical), **Medium** (a few hours, some design), **Hard** (a day+, protocol or state-machine changes that touch multiple layers).

Hard tasks are the ones worth handing to the most capable agent. Easy and medium tasks can usually be done by a smaller model with a clear brief.

For background on what shipped on 2026-05-17 (unified trace, per-turn screenshots, checkpoint list, run picker, button_press dedup, screenshot byte cache), see `CHANGELOG.md`.

---

## Repo orientation (read this first)

- **Project goal** — see the "Project north star" section at the top of `AGENTS.md`. Every change should improve observability of the agent or debuggability of a run; if it regresses either, it's net-negative regardless of how clean the code is.
- **AGENTS.md** is also where the non-obvious domain knowledge lives (Pokemon Red intro timing, bedroom save state quirks, harness lifecycle gotchas, LLM prompting tips, PyBoy press timing). Read it before touching `setup_bedroom.py`, the harness control loop, or anything frame-counting.
- **Three layers, kept deliberately separate:**
  - `env/` — FastAPI backend that owns the emulator (`env/runtime.py:RuntimeManager`, `Session`), the trace store (`env/trace.py:TraceStore`), and the WebSocket broker (`env/runtime.py:EventBroker`).
  - `harness/` — external HTTP client + agent base class (`harness/agent.py:PokemonAgent`, `harness/client.py:PokemonEnvClient`). Runs as a separate process.
  - `ui/` — React + TS, single-file app at `ui/src/App.tsx` (~700 lines, expected to be split later — see 4.B). State + API in `ui/src/api.ts`. Styles in `ui/src/styles.css`.
- **Trace event shape** — every event has `{run_id, source: "env"|"harness", type, turn_id, frame, timestamp, payload}` and is published over both the WebSocket and `runs/<run_id>/<source>.jsonl`. New event types only need a UI summarizer in `App.tsx:summarizeEvent` to render nicely.
- **Common verification commands**:
  - Backend tests: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest` (39 tests, < 1s)
  - UI typecheck + build: `cd ui && npm run build`
  - Full dev session: `bash scripts/dev.sh` (backend on :8000, vite on :5173)
  - Probe API: `curl -s http://127.0.0.1:8000/api/...`
- **Probe etiquette** — when starting a probe run for testing, use a `run_id` like `<feature>-test` and clean up `runs/<id>/` + `states/<id>/` afterwards so the runs dir doesn't accumulate test detritus.
- **Conventions** — completed work goes into `CHANGELOG.md` (grouped by date, Added/Changed/Fixed/Removed sections); finished TODO items are *removed* from this file, not struck through. See AGENTS.md.
- **The fake emulator** — `env/emulator.py:FakeEmulator` is the test-friendly stand-in for PyBoy. Position updates immediately (unlike real PyBoy which lags ~16 frames). All backend tests use it via `tests/conftest.py`.

---

## 1. Observability / debugging — Tier 1

### 1.E — Frame scrubber + rewind UI **[Hard]**

**Problem.** No way to scrub backward through a game. `harness/replay.py` exists but is CLI-only, replays into a *live* env, and can only go forward.

**Suggested action.** Build on existing per-frame thumbnails (`runs/<run_id>/frames/<frame>.png`, served by `GET /api/runs/<run_id>/frames/{frame}.png`): a horizontal scrubber under the game screen. Scrubbing previews the screenshot at that frame without mutating live state. A "Rewind to here" button calls into the checkpoint subsystem from 1.C.2 to actually mutate the emulator + agent state.

**Entry points.**
- Frames already exist on disk and have an endpoint — see `env/runtime.py:_save_frame_thumbnail` (line 109) and the GET route in `env/app.py:213`.
- For the discoverable-frames list, you can scan `runs/<run_id>/frames/` for existing PNGs (cheap directory iteration; numbers are the keys). Add `GET /api/runs/<run_id>/frames` returning `[int]`.
- UI: add the scrubber between `<div className="screen-wrap">` and `<section className="control-band">` in `ui/src/App.tsx`. On hover/scrub, override the game-screen `<img>` src with `frameThumbnailUrl(run_id, frame)` instead of the live `screenshotUrl(imageVersion)`.
- For the rewind action: a thumbnail only proves a *visual* state existed at that frame. Actually rewinding requires either (a) periodic auto-checkpoints, or (b) restricting "Rewind to here" to the nearest prior named checkpoint with a "+N frame replay" badge. Recommend (b) first — it's accurate, doesn't blow up disk, and reuses the existing checkpoint subsystem.

**Verify (acceptance).**
- Drag the scrubber: game screen preview updates to show old frames; releasing snaps back to live.
- Click "Rewind to here": emulator state + agent history snap to the prior checkpoint; trace pane shows a `state_loaded` event with the right name.
- Auto-scroll: when the user is scrubbing the past, the trace pane should *not* auto-scroll to live events (already handled by viewedRunId for past runs — extend the same idea here).

**Why hard.** Two pieces: the scrubber UI is medium on its own (timeline component, hover preview, range), but the "rewind" action is hard — it depends on 1.C.2 (agent history) and the UX around "which frame can I actually rewind to" needs a clear answer (named checkpoints only? auto-saves every N frames?). Disk cost for auto-saves at every press is ~165 KB × N — manageable for short runs, not for long ones.

**Files.** `env/runtime.py`, `env/app.py`, `ui/src/App.tsx`, `ui/src/api.ts`, `ui/src/styles.css`.

### 1.F — Conversation / prompt drawer + LLM telemetry **[Medium]**

**Problem.** The full LLM conversation (system prompt, image turn, assistant reply, history window) lives only inside the agent process. The UI sees a string `reasoning` and a single chosen button. You cannot inspect the exact prompt that was sent or compare model costs / latency.

**Suggested action.** Have the harness emit a new `llm_call` harness event from `harness/examples/my_agent.py` after each `self._llm.chat.completions.create(...)` call (line 95):

```python
self.emit("llm_call", {
    "model": MODEL,
    "messages": <serialized messages — strip base64 image data, keep a placeholder>,
    "response": raw,
    "usage": {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "latency_ms": elapsed_ms,
    },
}, turn_id=turn_id)
```

UI renders this as a new trace category (extend `eventCategory` and `CATEGORY_ICON` in `App.tsx` — see the existing pattern for `decision` / `action`). Show messages chat-style, images inline (load the same frame thumbnail since the agent sends `data:image/png;base64,...`). Footer shows running totals: tokens, $/turn (use a model→price lookup table), p50 latency.

**Verify (acceptance).**
- Run the example agent for ~5 turns; trace shows 5 `llm_call` events.
- Click one → drawer shows system prompt, user message, assistant response, token + latency stats.
- Toggle the new filter chip — `llm_call` events hide/show.

**Why medium.** Schema design + reasonable UI; mostly mechanical once shape is settled. No state-machine changes; no cross-process protocol. The image-stripping bit is the only subtle piece (full base64 in every llm_call would blow up `harness.jsonl`).

**Files.** `harness/examples/my_agent.py` (emit), `harness/agent.py` (optional `emit_llm_call` helper), `ui/src/App.tsx` (new category, renderer, drawer).

---

## 2. Cross-cutting infra — Tier 2

### 2.C — Harness registry: heartbeat + TTL + persistence **[Medium]**

**Problem.** `env/app.py:HarnessRegistry` (line 30) is in-memory only and never expires entries.
- Restart the backend → registered agents are lost; running agents keep polling 404 forever (documented in AGENTS.md).
- An agent process that dies leaves a `status="running"` row in the registry forever.

**Suggested action.**
1. In `HarnessRegistry`, add a `last_seen_at` field updated on every poll / WS pong / event emit. Add a `prune_stale(max_age_s)` method.
2. Wire it from a periodic asyncio task started in `RuntimeManager.__init__` (`env/runtime.py:157`); mark entries older than 30s as `disconnected` and prune after 5 min.
3. Persist registry to `runs/registry.json` on every mutation (or, less chatty, debounce). On `create_app` startup, hydrate from this file; on hydrate, set all `running` statuses back to `disconnected` (because we don't know if the process is alive).
4. UI: in the harness dropdown (`ui/src/App.tsx`, look for `harnessAgents.map`), show a `disconnected` chip alongside the existing status badge.

**Verify (acceptance).**
1. Test: register a harness, wait > 30s with no activity, assert status flips to `disconnected`.
2. Test: register + persist + reload manager → registry restored, running statuses downgraded to `disconnected`.
3. Manual: kill agent mid-run, wait 30s, dropdown shows it greyed out.

**Why medium.** Background task + state file + UI affordance; each piece is straightforward but there are three of them, and a few edge cases (a registration that ages out mid-Stop must not lose the Stop signal — keep the FIFO queue alive even when status is `disconnected`).

**Files.** `env/app.py` (`HarnessRegistry`), `env/runtime.py`, `ui/src/App.tsx`, `tests/test_api.py`.

### 2.E — Streaming / paginated trace reads **[Medium]**

`TraceStore.read()` (`env/trace.py:68`) loads the entire `env.jsonl` or `harness.jsonl` into memory and parses it on every `GET /api/runs/<id>/<source>-trace` call. Fine for today's 50-event traces. For longer agent runs (thousands of events per session) the UI's Reload button becomes a multi-megabyte fetch. Add `?since_timestamp=` / `?limit=` query params (server-side: read line-by-line, skip until `since`, take at most `limit`); UI already merges + sorts.

**Verify.** Manual: a run with 5000+ events should load incrementally; Reload completes in under a second.

**Files.** `env/trace.py`, `env/runtime.py`, `env/app.py`, `ui/src/App.tsx`.

### 2.G — Consolidate safe-name validation **[Easy]**

Three slightly different "safe name" checks exist today:
- `env/trace.py:11` — `SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")` + `ensure_safe_name`.
- `env/models.py:18-23` (`validate_run_id`) and `env/models.py:60-64` (`validate_name`) — `all(char.isalnum() or char in ('-', '_') ...)`.
- `env/runtime.py:list_states delete_state` — its own inline check.

Pull into a single helper (probably keep `env.trace.ensure_safe_name` as the canonical) and use everywhere. While there, harden `runtime.py:_state_path` and `load_state` with a `Path.resolve()` check that the resolved path is still inside `states_dir` (defense-in-depth against path traversal even if the name validator slips).

**Verify.** `pytest` passes; the existing `test_delete_state_rejects_traversal` should still pass with the new check.

**Files.** `env/trace.py`, `env/models.py`, `env/runtime.py`.

---

## 3. Correctness / smaller fixes

### 3.B — `dev.sh` bakes in a personal cache path **[Easy]**

`scripts/dev.sh:18` hard-codes `UV_CACHE_DIR=/private/tmp/uv-cache`. Almost certainly a personal workaround. Change to: only set the env var if it isn't already set, or just drop it entirely.

**Verify.** `bash scripts/dev.sh` still works on a fresh checkout.

**Files.** `scripts/dev.sh`.

### 3.C — Private-attr access in tests **[Easy]**

The test suite does `harness._client = client  # type: ignore` (see `tests/test_harness_base.py:59`, `tests/test_my_agent.py` patterns). Indicates the public/private API isn't clean. Add a `client_factory: Callable[[str], PokemonEnvClient] | None = None` constructor argument to `PokemonAgent` (`harness/agent.py:24`); tests pass a lambda producing a fake client.

**Verify.** `pytest` passes without any `# type: ignore` on `_client` assignment.

**Files.** `harness/agent.py`, `tests/test_harness_base.py`, `tests/test_my_agent.py`.

### 3.D — `harness/replay.py` re-presses already-emitted events **[Easy]**

When replaying into a fresh run, the live env emits its own `button_press` events; you end up with a trace mixing original + replayed events. The cleanest fix: before each press in `harness/replay.py:replay_env_trace`, emit a harness event of type `replay_marker` with payload `{source_run_id, source_frame}`. UI can use this to mark replayed runs visually (or filter them out via the existing filter chips).

**Verify.** Replay a known trace into a fresh run; new env trace shows interleaved `replay_marker` events identifying the source.

**Files.** `harness/replay.py`.

---

## 4. DX / repo hygiene — Tier 3

### 4.A — Static analysis **[Medium]**

- Add `pyright` or `mypy` config and fix the few `# type: ignore`s that pop up. The `EmulatorFactory` type signature in `env/runtime.py:28` vs how `FakeEmulator` is invoked is a real signature mismatch (FakeEmulator's `__init__` accepts `rom_path: Path | None`, but `Callable[[Path, Path | None], Emulator]` requires the first arg to be `Path`).
- Add `eslint` + `prettier` config in `ui/` — `@typescript-eslint/eslint-plugin` + `eslint-plugin-react-hooks` since the UI is one large `App.tsx`.

**Verify.** `uv run pyright env harness` (or mypy) clean; `npm run lint` clean (and add it to `scripts/verify.sh`).

**Files.** `pyproject.toml` (deps + tool config), `ui/package.json` (deps + lint script), `.eslintrc.*` (new), code fixes that surface.

### 4.B — Split `App.tsx` **[Medium]**

After today's changes the file is ~700 lines. Split into `ui/src/trace/` (TraceList, TraceGroup, TraceItem, TraceFilters, helpers), `ui/src/checkpoints/` (the Checkpoints component), `ui/src/run-picker/` (run dropdown). Mechanical but takes time. Keep `App.tsx` as the composition root only.

**Verify.** `npm run build` succeeds; UI still renders identically (do a side-by-side screenshot diff).

**Files.** `ui/src/App.tsx` → multiple modules.

### 4.C — Run/state cleanup policy **[Easy]**

25+ run dirs on disk after a few days, none ever cleaned. Add `scripts/clean-runs.sh` that removes `runs/<id>/` and `states/<id>/` for any id whose `runs/<id>/` mtime is > 30 days old. Bonus: surface run sizes in the run picker dropdown so the user can see what's consuming disk (extend the `RunSummary` shape in `env/runtime.py:list_runs` to include `bytes`).

**Verify.** `scripts/clean-runs.sh --dry-run` lists candidates; without `--dry-run` deletes them.

**Files.** `scripts/clean-runs.sh` (new), optionally `ui/src/App.tsx`, `env/runtime.py`.

### 4.D — Module-form invocations in docs **[Easy]**

`harness/examples/my_agent.py` is invoked with `uv run python harness/examples/my_agent.py` (a path) but `python -m harness.examples.my_agent` would also work and matches `python -m harness.replay` already in the README. Just docs.

**Files.** `README.md`.

### 4.E — Smoke test wiring **[Easy]**

`ui/pokemon-harness-smoke.spec.js` (referenced in `CHANGELOG.md`) lives in `ui/` not `tests/` or `ui/tests/`. With Playwright as a `devDependencies`, wire up `npm run test:smoke` (e.g. `playwright test pokemon-harness-smoke.spec.js`) and add it to `scripts/verify.sh` after the production build.

**Files.** `ui/package.json`, `scripts/verify.sh`.

### 4.F — Export client helpers from `harness/__init__.py` **[Easy]**

`harness/__init__.py` exports `PokemonAgent` only. The `press()` / `wait()` helper builders in `harness/client.py:94-99` are useful for building `sequence()` payloads but aren't exported — `from harness import press` fails silently. Either export them (add to `__all__`) or delete them (they're undocumented). Prefer export, since `sequence()` payloads are the natural use case and the README's API table lists `sequence()` as a supported entry point.

**Files.** `harness/__init__.py`, `README.md` if you add a usage note.

---

## Suggested order for what's left

1. **1.E** (frame scrubber + rewind UI, Hard) — the user-facing complement to 1.C.2: visual scrub through past frames, one-click rewind to any prior checkpoint, all hooked into the now-working agent-history restore.
2. **1.F** (LLM telemetry drawer, Medium) — independent, big perceived-quality win for observability.
3. **2.C** (heartbeat/TTL/persistence, Medium) — papers over the documented stale-registration footgun.
4. **2.E** / **2.G** / **3.x** / **4.x** — opportunistic, low risk.
