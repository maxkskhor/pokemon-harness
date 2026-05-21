# Resume-from-run verification

End-to-end checklist for the Start/Stop/Resume flow. Each scenario lists what to do, what to look for in the UI, and the filesystem/API invariants that must hold.

## Preconditions

Before starting:

```bash
# 1. Kill anything stale and clear ports.
pkill -f "uvicorn|vite|tool_agent|first_agent|dev.sh" 2>/dev/null || true
sleep 2
lsof -ti :8000 -ti :5173 2>/dev/null | xargs kill -9 2>/dev/null || true

# 2. (Optional) Start from a truly clean slate — wipes existing auto-resume snapshots.
find states -name "_auto_resume.*" -not -path "*/shared/*" -delete

# 3. Boot stack.
./scripts/dev.sh
```

Open http://127.0.0.1:5173 . Both `First Agent` and `Tool Agent` should appear in the dropdown with status `idle`. WebSocket indicator: `● connected`.

---

## Verification notes — 2026-05-21

Tested locally with `./scripts/dev.sh`, a clean `_auto_resume` slate, the existing Playwright smoke suite, and headless browser interaction against `http://127.0.0.1:5173`.

### Summary

Works:
- Smoke suite: `cd ui && npx playwright test pokemon-harness-smoke.spec.js --reporter=list` passed all 7 tests.
- Initial UI boot: WebSocket connected, both agents registered, shared `bedroom` state listed, and the selected agent starts with `Start agent` enabled / `Stop agent` disabled / `Reset` enabled.
- Fresh Tool Agent start: clicking `Start agent` from the UI created a live run, showed the emulator frame, and trace cards streamed turns.
- Stop path: stopping a running Tool Agent closed `/api/health.active_run` back to `null`, wrote `_auto_resume`, changed the primary action to `Resume agent`, and did not show the old red `/api/action/press` warning under the controls.
- Resume path: clicking `Resume agent` started a new branched run with `parent_run_id` set to the stopped source run and `parent_checkpoint` set to `_auto_resume`.
- Reset path: clicking `Reset` removed auto-resume snapshots for that agent's runs; `/api/runs` then reported `has_auto_resume: false`, and the primary action returned to `Start agent`.
- Multi-agent isolation, partial check: after stopping First Agent with an auto-resume snapshot, switching to Tool Agent correctly showed `Start agent`, not `Resume agent`. The First Agent resumable state did not leak into Tool Agent's primary action.
- Page reload, partial check: reloading mid-run re-bound to the active run, reconnected WebSocket, showed the active run id, live emulator frame, and persisted trace events.

### Triage outcomes — 2026-05-21 (follow-up)

Each item from the original feedback below has been triaged and labelled.

- **[DOCS-UPDATED]** Button text is `Start agent` / `Resume agent` without the literal `▶` / `↺` glyphs. UI uses lucide-react SVG icons (Play / History), which render as actual icons next to the text — *not* unicode glyphs. The checklist text below has been corrected (the glyphs are illustrative only).
- **[DOCS-UPDATED]** After resume, the run picker label is `View run: Active – <run-id>`, not `View run: No run`. That is intentional UI behaviour: `No run` only shows when there is no active run at all. The checklist has been corrected.
- **[FIXED]** Reload mid-run dropdown mismatch. `ui/src/App.tsx` now auto-selects the harness whose name matches `active_run.agent.name` once, on first mount that discovers an active run (`autoSelectAttemptedRef`). Verified: starting Tool Agent, then hard-reloading the page, the dropdown shows `Tool Agent · running` and **Stop agent** is enabled immediately (no manual selection needed). Subsequent dropdown picks by the user are not overridden.
- **[FIXED]** Browser console 404s during stop. `ui/src/App.tsx`'s WebSocket handler now treats `run_stopped` as an explicit clear: state, image version, and event run id are reset directly instead of bumping `imageVersion` (which re-triggers `/api/screenshot.png`) or calling `refreshState()` (which re-hits `/api/state`). Verified: stopping a running Tool Agent now leaves the browser console at `0 errors, 1 warnings` (the surviving warning is the early WebSocket-open race, unrelated). The `DELETE _auto_resume` 404 noise on Reset is harmless (best-effort delete; the server endpoint correctly returns 404 when a snapshot was never created) and has been left as-is.
- **[WONT-FIX]** Explicit past-run resume via the picker uses a drawer table (not a native `<select>`). That's intentional: the table surfaces agent name, model, turns, last-turn summary, started-at, and size, which a native `<select>` cannot. Behaviourally correct per Section 6 of this checklist (verified earlier; Section 6 has a more thorough walk-through). No code change.
- **[WONT-FIX]** Trace thumbnail stability was checked at the API-response level (the `frame` field is sourced from `turn_started`, see `ui/src/trace/TurnCard.tsx`) and by live observation during the Section 2 walkthrough. A pixel-diff harness would be valuable as a regression suite, but is out of scope for this fix-up pass.

### Closing this round

The two real bugs (reload dropdown mismatch, stop-time console 404s) are resolved. The two doc items are addressed inline in the sections below. The two `WONT-FIX` items are intentional / out-of-scope. See `CHANGELOG.md` for the diff summary.

---

## 1. Fresh start — button reads "Start agent"

**Setup:** Pick an agent in the dropdown that has *no* `_auto_resume.state` on disk (i.e. either ran the wipe in step 2 above, or has never been played in this dev session). With the leftover-state cleanup done, both agents qualify.

**Steps:**
1. Select the agent in the dropdown.

**Expect:**
- Primary action button reads **`Start agent`** (with a Play icon to its left, not the literal `▶` glyph; not "Play agent" and not "Resume agent").
- Hover tooltip: `Start a fresh run from the bedroom save state`.
- `Stop agent` is disabled, `Reset` is enabled.

**Backend check:**
```bash
curl -s http://127.0.0.1:8000/api/runs | jq '.[0:5] | map({run_id, agent: .agent.name, has_auto_resume})'
```
No row for this agent should have `has_auto_resume: true`. (If one does, the button will read "Resume agent" — that's correct given the state on disk; either pick the other agent or click Reset first.)

---

## 2. Start a fresh run

**Steps:**
1. From state #1, click **`Start agent`**.
2. Wait ~5–10 seconds.

**Expect:**
- Status indicator transitions `idle → starting → running`.
- The game emulator pane fills with a frame (player on bed in bedroom).
- Trace panel starts emitting events: `run_started`, `state_loaded`, `agent_loop_started`, `turn-001`, …
- Each turn card shows a thumbnail labelled `frame N` and **the thumbnail does not change** while you watch (i.e. it does not flip to a different image when the turn transitions from `● running` to `ok`).
- Frame counter in the metrics row keeps advancing.

**Backend check:**
```bash
curl -s http://127.0.0.1:8000/api/health
# → {"ok":true,"active_run":"<agent>-XXXXXXXX"}
```

---

## 3. Stop mid-run — no 404 warning, label flips to "Resume agent"

**Steps:**
1. While the agent is running (let it complete at least 2–3 turns first), click **`Stop agent`**.
2. Wait up to ~35 seconds. (The control thread joins the run thread for up to 30s so the current LLM call can drain cleanly.)

**Expect:**
- Status indicator: `running → stopping → idle`.
- **No red error/warning box** appears under the agent controls. (This is the regression we fixed — the old behavior surfaced a `Client error '404 Not Found' for url '/api/action/press'` when stop tore down the env before the run thread exited.)
- **Browser console is clean.** No `Failed to load resource ... 404` rows for `/api/state` or `/api/screenshot.png` after the env session closes.
- All completed turn cards show status `ok` (green pill).
- The last in-progress turn, if any, either completes with status `ok` (if the LLM call drained within 30s) or `aborted` (if it didn't). It must **not** be left on `● running` forever.
- Primary action button label changes to **`Resume agent`** (with a History icon to its left) — hover tooltip mentions resuming from auto-snapshot.
- "Checkpoints" sidebar shows a `_auto_resume` entry tagged with the frame at stop.

**Backend checks:**
```bash
RUN_ID=$(jq -r .run_id runs/<your-run-id>/meta.json)  # or grab from the UI's Run metric

# Session fully terminated, not paused.
curl -s http://127.0.0.1:8000/api/health
# → {"ok":true,"active_run":null}

# Run meta closed out.
cat runs/$RUN_ID/meta.json | jq '{status, ended_at, turns}'
# → status="stopped", ended_at set, turns matches the count of ok turns.

# Auto-resume snapshot exists for this run.
ls states/$RUN_ID/
# → _auto_resume.state  (and _auto_resume.agent.json if the agent overrides serialize_history)

# Run summary picks it up.
curl -s http://127.0.0.1:8000/api/runs | jq ".[] | select(.run_id==\"$RUN_ID\") | .has_auto_resume"
# → true

# Trace contains no error events from the shutdown.
curl -s "http://127.0.0.1:8000/api/runs/$RUN_ID/harness-trace" | jq '.[] | select(.type=="error" or .type=="warning") | {type, msg: .payload.message}'
# → (empty)
```

---

## 4. Resume from the most recent stopped run

**Steps:**
1. From state #3 (Resume agent showing), click **`Resume agent`**.
2. Wait ~5 seconds for the new run to spin up.

**Expect:**
- A **new** run id appears in the Run metric — the form is `<agent-name>-XXXXXXXX` (e.g. `tool-agent-c77133e1`).
- The emulator pane shows the player **at the position where the previous run stopped** — *not* the bedroom start.
- The UI auto-flips back to live view; the run picker label reads `View run: Active – <new-run-id>` (it follows the live branched run).
- Trace begins with a `state_loaded` event referencing the source run's `_auto_resume`, then new turns starting from `turn-001`.
- Primary action is now `Stop agent` (Resume button disappears while running).

**Backend check:**
```bash
curl -s http://127.0.0.1:8000/api/runs | jq '.[0] | {run_id, parent_run_id, parent_checkpoint, agent: .agent.name, status, turns}'
# → run_id: "<agent>-XXXXXXXX"
#    parent_run_id: "<the previous run id>"
#    parent_checkpoint: "_auto_resume"
#    status: "running"
#    turns: starts at 0/1
```

---

## 5. Reset — wipes resumable state, label flips back to "Start agent"

**Steps:**
1. Stop the running agent (or you may also Reset while running; it will tear down the run thread first).
2. Click **`Reset`**.
3. Wait ~3–5 seconds.

**Expect:**
- All status indicators settle to `idle`.
- Primary action label flips back to **`Start agent`**.
- "Checkpoints" sidebar no longer shows `_auto_resume`.
- View Run picker rows for this agent lose the `↺` "resumable" badge in the Run ID column.

**Backend checks:**
```bash
# No remaining auto-resume snapshots for this agent.
curl -s http://127.0.0.1:8000/api/runs | jq '.[] | select(.agent.name=="Tool Agent") | {run_id, has_auto_resume}'
# → all entries: has_auto_resume: false

# Files were actually deleted on disk.
find states -name "_auto_resume.state" -path "*/<agent-id>/*"
# → no matches for runs by this agent
```

---

## 6. Resume from an explicit past run via "View run"

**Steps:**
1. Click the **View run** dropdown in the trace panel header.
2. Pick a past run that has the `↺` badge in its Run ID cell (i.e. `has_auto_resume: true`).

**Expect:**
- "Checkpoints" sidebar reloads to show the picked run's saved states (including `_auto_resume`).
- Primary action label reads **`Resume agent`**.
- If the selected agent in the dropdown matches `agent.name` of the viewed run, the button is **enabled**. Tooltip: `Resume <run-id> from its auto-snapshot` (or similar).
- If the dropdown is set to a *different* agent than the viewed run's recorded `agent.name`, the button is **disabled**. Hover tooltip explains: `Selected agent '<X>' does not match this run's agent '<Y>'.` (or `Connect the '<name>' agent to resume this run.` when not connected.)

**Then click Resume agent** (with the matching agent selected):
- A new branched run starts. UI flips back to live view. `parent_run_id` matches the *viewed* run (not whatever was most-recent for that agent).

---

## 7. Multi-agent switching

**Steps:**
1. Reset both agents (so neither has auto_resume).
2. Select **First Agent**, click **Start agent**. Let 2 turns elapse. Click **Stop agent**.
3. Without resetting, select **Tool Agent** in the dropdown.

**Expect after step 3:**
- Primary action reads **`Start agent`** (Tool Agent has no resumable state of its own — even though First Agent does, the label is per-selected-agent).
4. Click **Start agent**. Tool Agent runs from bedroom (a fresh session, *not* First Agent's state).

**Expect during Tool Agent's run:**
- `curl http://127.0.0.1:8000/api/health` shows a different `active_run` id than First Agent's.
- The new run's `meta.json` records `agent.name: "Tool Agent"` and `parent_run_id: null`.

5. Stop Tool Agent. Switch dropdown back to **First Agent**.

**Expect:**
- Primary action reads **`Resume agent`** (First Agent's auto-snapshot is still on disk).
- Clicking it resumes First Agent's stopped run, not Tool Agent's. The new run's `parent_run_id` is First Agent's run id.

---

## 8. Trace card thumbnail stability

**Goal:** confirm the per-turn screenshot doesn't update spuriously as the game advances.

**Steps:**
1. With an agent running, watch any *completed* (status: `ok`) turn card.
2. Wait through 2–3 more turns.

**Expect:**
- The completed card's thumbnail (`frame N`) stays exactly the same. The label `frame N` does not increment, and the image does not visibly change.
- Newer turn cards have higher `frame` numbers — increasing roughly monotonically (small ties are possible when multiple events emit in the same emulator tick at 1x).
- The thumbnail represents the frame at *turn start* (i.e. the screenshot the agent saw when it called the LLM), not the frame at turn end.

---

## 9. Page reload mid-run

**Steps:**
1. With an agent running, hard-reload the page (Cmd-Shift-R).

**Expect:**
- The emulator pane re-binds to the active run within ~1s.
- WebSocket reconnects (`● connected` shown).
- Trace panel re-loads the persisted trace for the active run; new events stream in.
- Primary action button correctly reflects the agent's current state (`Stop agent` enabled, label is the active run's intent).

---

## 10. Teardown

```bash
pkill -f "uvicorn|vite|tool_agent|first_agent|dev.sh" 2>/dev/null || true
sleep 2
lsof -ti :8000 -ti :5173 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti :8000 -ti :5173 2>/dev/null && echo "STILL RUNNING — investigate" || echo "all clear"
ps aux | grep -E "uvicorn|vite|tool_agent|first_agent" | grep -v grep || echo "no processes"
```

Expect both checks to report clean.

---

## Negative tests (should NOT happen)

These would be regressions of the fixes shipped on 2026-05-21:

- ❌ Red `Client error '404 Not Found' for url '/api/action/press'` box appearing under the agent controls after Stop.
- ❌ Stop leaves `active_run` non-null in `/api/health` (means `pause_run` not `stop_run` was called — switching agents would silently inherit the session).
- ❌ Turn card stuck at status `● running` indefinitely after Stop.
- ❌ Trace thumbnail for a single turn changing frame number / image content as time passes.
- ❌ Primary action reading "Resume agent" after a Reset with no resumable run on disk for the selected agent.
- ❌ Primary action reading "Play agent" anywhere (it should be "Start agent" or "Resume agent" — the literal string "Play agent" was renamed).
- ❌ Resume button enabled when the dropdown's selected agent name differs from the viewed run's `agent.name`.
- ❌ Resumed run's `meta.json` missing `parent_run_id` or `parent_checkpoint`.
