import { Activity, History, Pause, Play, RefreshCw, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  API_BASE,
  HarnessAgent,
  PokemonState,
  RunSummary,
  SavedState,
  TraceEvent,
  deleteRunState,
  frameThumbnailUrl,
  getHealth,
  getState,
  listHarnesses,
  listRunFrames,
  listRunStates,
  listRuns,
  listSharedStates,
  loadState,
  playHarness,
  resetHarness,
  resumeHarness,
  saveState,
  screenshotUrl,
  setSpeed,
  stopHarness,
  traceUrl,
  wsUrl,
} from "./api";
import { Checkpoints } from "./checkpoints/Checkpoints";
import { FrameScrubber } from "./checkpoints/FrameScrubber";
import { RunPicker } from "./run-picker/RunPicker";
import { TraceFilters } from "./trace/TraceFilters";
import { TraceList } from "./trace/TraceList";
import { NOISY_EVENT_TYPES, type FilterType } from "./trace/helpers";

const speeds = ["paused", "1x", "5x", "max"];

export function App() {
  const [state, setState] = useState<PokemonState | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [imageVersion, setImageVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [harnessAgents, setHarnessAgents] = useState<HarnessAgent[]>([]);
  const [selectedHarnessId, setSelectedHarnessId] = useState<string | null>(null);
  const [runStates, setRunStates] = useState<SavedState[]>([]);
  const [sharedStates, setSharedStates] = useState<SavedState[]>([]);
  const [checkpointName, setCheckpointName] = useState("");
  const [runHistory, setRunHistory] = useState<RunSummary[]>([]);
  const [viewedRunId, setViewedRunId] = useState<string | null>(null);
  const [frameNumbers, setFrameNumbers] = useState<number[]>([]);
  const [scrubSelectedFrame, setScrubSelectedFrame] = useState<number | null>(null);
  const [scrubPreviewFrame, setScrubPreviewFrame] = useState<number | null>(null);
  const viewedRunIdRef = useRef<string | null>(null);
  viewedRunIdRef.current = viewedRunId;
  const [showImages, setShowImages] = useState(true);
  const [traceFilters, setTraceFilters] = useState<Record<FilterType, boolean>>({
    decision: true,
    llm: true,
    action: true,
    state: false,
    lifecycle: false,
    warning: true,
    error: true,
  });
  const eventRunIdRef = useRef<string | null>(null);
  // Tracks whether we've already auto-selected the harness for the active run
  // discovered on initial mount. AGENTS.md is explicit that Stop only targets
  // the dropdown selection — so on reload, the dropdown must match the agent
  // that owns active_run. After this fires once, the user is in control.
  const autoSelectAttemptedRef = useRef(false);

  const selectedHarness = harnessAgents.find((h) => h.id === selectedHarnessId) ?? null;
  const viewedRunSummary = viewedRunId
    ? runHistory.find((r) => r.run_id === viewedRunId) ?? null
    : null;
  const isViewingPastRun = viewedRunId !== null;

  // Primary action label is driven solely by the View Run picker:
  //   "start"  – dropdown selection only; click starts fresh from `bedroom`.
  //   "resume" – user explicitly picked a past run; click branches from that run's checkpoint.
  // Changing the agent in the dropdown must never silently imply resume.
  const primaryIntent: "start" | "resume" = isViewingPastRun ? "resume" : "start";

  const viewedRunHasCheckpoint = runStates.length > 0;
  const viewedRunAgentName = viewedRunSummary?.agent?.name ?? null;
  let resumeBlocker: string | null = null;
  if (isViewingPastRun) {
    if (!viewedRunHasCheckpoint) {
      resumeBlocker = "This run has no saved checkpoints to resume from.";
    } else if (!selectedHarness) {
      resumeBlocker = viewedRunAgentName
        ? `Connect the '${viewedRunAgentName}' agent to resume this run.`
        : "Select a connected agent to resume.";
    } else if (viewedRunAgentName && selectedHarness.name !== viewedRunAgentName) {
      resumeBlocker = `Selected agent '${selectedHarness.name}' does not match this run's agent '${viewedRunAgentName}'.`;
    } else if (selectedHarness.status === "running") {
      resumeBlocker = "Stop the running agent before resuming a past run.";
    } else if (selectedHarness.status === "disconnected") {
      resumeBlocker = "Selected agent is disconnected.";
    }
  }

  // Restore active run on page load
  useEffect(() => {
    getHealth()
      .then((health) => {
        if (!health.active_run) return null;
        return getState();
      })
      .then((next) => {
        if (!next) return;
        setState(next);
        setImageVersion((v) => v + 1);
        eventRunIdRef.current = next.run_id;
        void refreshTraces(next.run_id);
        void refreshCheckpoints(next.run_id);
        void refreshFrames(next.run_id);
      })
      .catch(() => {});
    void refreshCheckpoints(null);
    void refreshRunHistory();
  }, []);

  // WebSocket for live events
  useEffect(() => {
    let alive = true;
    let ws: WebSocket;

    function connect() {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => { if (alive) setWsConnected(true); };
      ws.onclose = () => {
        if (alive) {
          setWsConnected(false);
          setTimeout(connect, 2000);
        }
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (message) => {
        const event = JSON.parse(message.data) as TraceEvent;
        // While the user is browsing a past run, suppress live appends so the historical
        // trace they're inspecting doesn't shift under them.
        const viewingPast = viewedRunIdRef.current !== null && viewedRunIdRef.current !== event.run_id;

        // Handle run_stopped as an explicit teardown and return early. If we fell
        // through to the "new-run-detected" block below, it would re-anchor
        // eventRunIdRef to the just-stopped run id and race with any in-flight
        // refreshState — leaving the UI showing "Active – <stopped-id>" until reload.
        if (event.source === "env" && event.type === "run_stopped") {
          setState(null);
          setImageVersion(0);
          eventRunIdRef.current = null;
          void refreshRunHistory();
          if (!viewingPast) {
            setEvents((current) => [...current.slice(-499), event]);
          }
          return;
        }

        if (event.source === "env") {
          setImageVersion((version) => version + 1);
          // playback_frame fires every 0.1s — skip full state refresh, image bump is enough
          if (event.type !== "playback_frame") {
            void refreshState(false);
          }
          if (event.type === "state_saved" || event.type === "state_loaded") {
            void refreshCheckpoints(event.run_id);
          }
          if (event.type === "run_started") {
            void refreshRunHistory();
          }
          if (event.frame != null) {
            setFrameNumbers((current) => {
              const frame = event.frame as number;
              if (current.includes(frame)) return current;
              return [...current, frame].sort((a, b) => a - b);
            });
          }
        }

        if (event.source === "harness" && event.type === "turn_finished") {
          void refreshRunHistory();
        }

        if (viewingPast) return;

        if (eventRunIdRef.current !== event.run_id) {
          eventRunIdRef.current = event.run_id;
          setEvents([]);
          void refreshCheckpoints(event.run_id);
          void refreshFrames(event.run_id);
        }
        if (!NOISY_EVENT_TYPES.has(event.type)) {
          setEvents((current) => [...current.slice(-499), event]);
        }
      };
    }

    connect();
    return () => {
      alive = false;
      ws?.close();
    };
  }, []);

  // On the first time we discover an active run (e.g. on page reload), align the
  // dropdown with the harness that started that run. Subsequent runs are
  // user-initiated, so we leave the selection alone after this fires once.
  useEffect(() => {
    if (autoSelectAttemptedRef.current) return;
    if (!state) return;
    if (harnessAgents.length === 0) return;
    autoSelectAttemptedRef.current = true;
    const activeRunSummary = runHistory.find((r) => r.run_id === state.run_id);
    const activeAgentName = activeRunSummary?.agent?.name;
    if (!activeAgentName) return;
    const matching = harnessAgents.find((h) => h.name === activeAgentName);
    if (matching && matching.id !== selectedHarnessId) {
      setSelectedHarnessId(matching.id);
    }
  }, [state, harnessAgents, runHistory, selectedHarnessId]);

  // Poll harness registry
  useEffect(() => {
    const poll = async () => {
      try {
        const agents = await listHarnesses();
        setHarnessAgents(agents);
        setSelectedHarnessId((prev) => {
          if (prev && agents.find((a) => a.id === prev)) return prev;
          return agents[0]?.id ?? null;
        });
      } catch {
        setHarnessAgents([]);
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, []);

  async function runAction<T>(action: () => Promise<T>, refresh = true): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (refresh) await refreshState();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function refreshState(updateImage = true) {
    // Capture the active run at fetch-start. If run_stopped clears eventRunIdRef
    // while the fetch is in flight, drop the result — the backend's session is
    // briefly still alive between `emit_env("run_stopped")` and `self.session = None`,
    // so a late resolve here would re-populate state with the just-stopped run.
    const expectedRunId = eventRunIdRef.current;
    try {
      const next = await getState();
      if (expectedRunId !== null && eventRunIdRef.current === null) return;
      setState(next);
      if (updateImage) setImageVersion((v) => v + 1);
    } catch {
      setState(null);
    }
  }

  async function refreshTraces(activeRunId: string, incremental = false) {
    const currentEvents = events.filter((event) => event.run_id === activeRunId);
    const sinceTimestamp = incremental && currentEvents.length
      ? currentEvents.reduce((latest, event) => event.timestamp > latest ? event.timestamp : latest, currentEvents[0].timestamp)
      : undefined;
    const [envResponse, harnessResponse] = await Promise.all([
      fetch(traceUrl(activeRunId, "env", { sinceTimestamp, limit: incremental ? 1000 : undefined })),
      fetch(traceUrl(activeRunId, "harness", { sinceTimestamp, limit: incremental ? 1000 : undefined })),
    ]);
    const envEvents: TraceEvent[] = envResponse.ok ? await envResponse.json() : [];
    const harnessEvents: TraceEvent[] = harnessResponse.ok ? await harnessResponse.json() : [];
    const merged = [...(incremental ? currentEvents : []), ...envEvents, ...harnessEvents]
      .filter((event) => !NOISY_EVENT_TYPES.has(event.type))
      .filter((event, index, all) => {
        const key = `${event.source}:${event.timestamp}:${event.type}:${event.turn_id ?? ""}:${event.frame ?? ""}`;
        return all.findIndex((candidate) => `${candidate.source}:${candidate.timestamp}:${candidate.type}:${candidate.turn_id ?? ""}:${candidate.frame ?? ""}` === key) === index;
      })
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    setEvents(merged);
  }

  async function refreshFrames(activeRunId: string | null) {
    if (!activeRunId) {
      setFrameNumbers([]);
      setScrubSelectedFrame(null);
      setScrubPreviewFrame(null);
      return;
    }
    try {
      const frames = await listRunFrames(activeRunId);
      setFrameNumbers(frames);
      setScrubSelectedFrame((current) => current ?? frames.at(-1) ?? null);
    } catch {
      setFrameNumbers([]);
      setScrubSelectedFrame(null);
      setScrubPreviewFrame(null);
    }
  }

  async function refreshCheckpoints(activeRunId: string | null) {
    try {
      const shared = await listSharedStates();
      setSharedStates(shared);
    } catch {
      setSharedStates([]);
    }
    if (!activeRunId) {
      setRunStates([]);
      return;
    }
    try {
      const local = await listRunStates(activeRunId);
      setRunStates(local);
    } catch {
      setRunStates([]);
    }
  }

  async function refreshRunHistory() {
    try {
      setRunHistory(await listRuns());
    } catch {
      setRunHistory([]);
    }
  }

  async function handleReloadTraces() {
    const targetRunId = viewedRunId ?? eventRunIdRef.current ?? state?.run_id ?? null;
    if (!targetRunId) return;
    await runAction(() => refreshTraces(targetRunId, true), false);
    void refreshRunHistory();
  }

  async function handleSelectRun(runId: string | null) {
    setViewedRunId(runId);
    if (runId === null) {
      // Back to the active (live) run. Replay the persisted trace; live WS events resume.
      const activeRunId = eventRunIdRef.current ?? state?.run_id ?? null;
      if (activeRunId) {
        await refreshTraces(activeRunId);
        await refreshFrames(activeRunId);
        await refreshCheckpoints(activeRunId);
      }
      return;
    }
    await refreshTraces(runId);
    await refreshFrames(runId);
    await refreshCheckpoints(runId);
  }

  async function handleSaveCheckpoint() {
    if (!state) return;
    const name = (checkpointName.trim() || `chkpt-${state.frame}`).toLowerCase();
    await runAction(() => saveState(name), false);
    setCheckpointName("");
    await refreshCheckpoints(state.run_id);
  }

  async function handleLoadCheckpoint(name: string) {
    await runAction(() => loadState(name), true);
    await refreshFrames(state?.run_id ?? null);
  }

  async function handleDeleteCheckpoint(name: string) {
    if (!state) return;
    await runAction(() => deleteRunState(state.run_id, name), false);
    await refreshCheckpoints(state.run_id);
  }

  async function handleHarnessPlay() {
    if (!selectedHarnessId) return;
    // Switch to live view so the user sees the active run, not a stale past run.
    setViewedRunId(null);
    const activeRunId = eventRunIdRef.current ?? state?.run_id ?? null;
    if (activeRunId) {
      void refreshTraces(activeRunId);
      void refreshFrames(activeRunId);
    }
    await runAction(() => playHarness(selectedHarnessId), false);
  }

  async function handleHarnessStop() {
    if (!selectedHarnessId) return;
    await runAction(async () => {
      const result = await stopHarness(selectedHarnessId);
      // The agent writes `_auto_resume` on stop (used when the user later picks
      // this run in the View Run picker). Give the control loop a beat to finish
      // save_state before re-reading run history.
      await new Promise((resolve) => setTimeout(resolve, 500));
      await refreshRunHistory();
      return result;
    }, false);
  }

  async function handleHarnessReset() {
    if (!selectedHarnessId) return;
    await runAction(async () => {
      const result = await resetHarness(selectedHarnessId);
      await new Promise((resolve) => setTimeout(resolve, 500));
      await refreshRunHistory();
      return result;
    }, false);
  }

  async function handleHarnessResume() {
    if (!selectedHarnessId || !viewedRunId) return;
    // Resume only fires from the View Run picker — source = viewed run, checkpoint
    // = the run's auto-snapshot if present, else the newest user checkpoint.
    const auto = runStates.find((s) => s.name === "_auto_resume");
    const fallback = runStates[0];
    const checkpoint = (auto ?? fallback)?.name ?? "_auto_resume";
    const sourceRunId = viewedRunId;
    await runAction(async () => {
      const result = await resumeHarness(selectedHarnessId, {
        source_run_id: sourceRunId,
        checkpoint_name: checkpoint,
      });
      // Flip the UI to live view so it follows the new branched run.
      setViewedRunId(null);
      eventRunIdRef.current = result.run_id;
      await refreshTraces(result.run_id);
      await refreshFrames(result.run_id);
      await refreshCheckpoints(result.run_id);
      await refreshRunHistory();
      return result;
    }, true);
  }

  return (
    <main className="app-shell">
      <section className="game-pane">
        <header className="topbar">
          <div>
            <h1>Pokemon Harness</h1>
            <span className="connection-status">
              <span>API {API_BASE}</span>
              <span>WebSocket {wsConnected ? "● connected" : "○ disconnected"}</span>
            </span>
          </div>
        </header>

        {error ? <pre className="error">{error}</pre> : null}

        <div className="screen-wrap">
          {state ? (
            <img
              className="game-screen"
              src={scrubPreviewFrame != null ? frameThumbnailUrl(state.run_id, scrubPreviewFrame) : screenshotUrl(imageVersion)}
              alt="Pokemon emulator frame"
            />
          ) : (
            <div className="empty-screen">No active run</div>
          )}
        </div>

        <FrameScrubber
          runId={state?.run_id ?? null}
          frames={frameNumbers}
          selectedFrame={scrubSelectedFrame}
          previewFrame={scrubPreviewFrame}
          checkpoints={runStates}
          busy={busy}
          onSelectFrame={setScrubSelectedFrame}
          onPreviewFrame={setScrubPreviewFrame}
          onRewind={handleLoadCheckpoint}
        />

        <section className="control-band">
          <div className="speed-controls">
            <span className="speed-label">Emulator speed</span>
            {speeds.map((mode) => (
              <button
                key={mode}
                className={state?.speed_mode === mode ? "selected" : ""}
                onClick={() => runAction(() => setSpeed(mode))}
                disabled={!state || busy}
                title={mode === "paused" ? "Freeze background; agent still acts" : `Run at ${mode}`}
              >
                {mode === "paused" ? <Pause size={14} /> : null}{mode}
              </button>
            ))}
          </div>
        </section>

        <section className="state-grid">
          <Metric label="Run" value={state?.run_id ?? "-"} />
          <Metric label="Frame" value={state?.frame ?? "-"} />
          <Metric label="Speed" value={state?.speed_mode ?? "-"} />
          <Metric label="Map" value={state?.pokemon.map_id ?? "-"} />
          <Metric label="X/Y" value={state ? `${state.pokemon.x ?? "-"} / ${state.pokemon.y ?? "-"}` : "-"} />
          <Metric label="Party" value={state?.pokemon.party_count ?? "-"} />
          <Metric label="Spend" value={runCostDisplay(events)} />
        </section>

        <Checkpoints
          state={state}
          runStates={runStates}
          sharedStates={sharedStates}
          checkpointName={checkpointName}
          onCheckpointNameChange={setCheckpointName}
          onSave={handleSaveCheckpoint}
          onLoad={handleLoadCheckpoint}
          onDelete={handleDeleteCheckpoint}
          busy={busy}
        />
      </section>

      <aside className="trace-pane">
        <header className="harness-header">
          <div className="trace-title-row">
            <div>
              <h2>Trace</h2>
              <span>
                {events.length} events
                {viewedRunId ? ` · viewing ${viewedRunId}` : ""}
              </span>
            </div>
            <button onClick={handleReloadTraces} disabled={busy || !eventRunIdRef.current}>
              <RefreshCw size={14} /> Reload
            </button>
          </div>
          <RunPicker
            activeRunId={state?.run_id ?? null}
            viewedRunId={viewedRunId}
            runHistory={runHistory}
            onSelectRun={handleSelectRun}
          />
          <div className="agent-controls" aria-label="Agent controls">
            <span>Agent</span>
            <div className="harness-controls">
              <select
                value={selectedHarnessId ?? ""}
                onChange={(e) => setSelectedHarnessId(e.target.value || null)}
                disabled={harnessAgents.length === 0}
              >
                {harnessAgents.length === 0
                  ? <option value="">No harness connected</option>
                  : harnessAgents.map((h) => (
                      <option key={h.id} value={h.id}>{h.name} · {h.status}</option>
                    ))}
              </select>
              {primaryIntent === "resume" ? (
                <button
                  onClick={handleHarnessResume}
                  disabled={
                    busy
                    || resumeBlocker !== null
                    || !selectedHarness
                    || selectedHarness.status === "running"
                    || selectedHarness.status === "disconnected"
                  }
                  title={resumeBlocker ?? "Resume this run from its latest checkpoint"}
                >
                  <History size={14} /> Resume agent
                </button>
              ) : (
                <button
                  onClick={handleHarnessPlay}
                  disabled={busy || !selectedHarness || selectedHarness.status === "running" || selectedHarness.status === "disconnected"}
                  title="Start a fresh run from the bedroom save state"
                >
                  <Play size={14} /> Start agent
                </button>
              )}
              <button
                onClick={handleHarnessStop}
                disabled={busy || !selectedHarness || selectedHarness.status === "idle"}
              >
                <Square size={14} /> Stop agent
              </button>
              <button
                onClick={handleHarnessReset}
                disabled={busy || !selectedHarness || selectedHarness.status === "disconnected"}
                title="Stop agent and reset to bedroom save state"
              >
                <RotateCcw size={14} /> Reset
              </button>
            </div>
          </div>
          <TraceFilters filters={traceFilters} onChange={setTraceFilters} showImages={showImages} onToggleImages={setShowImages} />
          {selectedHarness && (
            <span className="harness-status" data-status={selectedHarness.status}>
              <Activity size={13} /> {selectedHarness.status}
            </span>
          )}
          {selectedHarness?.error && (
            <pre className="harness-error">{selectedHarness.error}</pre>
          )}
        </header>

        <div className="harness-events">
          <TraceList
            events={events}
            filters={traceFilters}
            showImages={showImages}
            isRunning={selectedHarness?.status === "running" || selectedHarness?.status === "starting"}
            autoScroll={scrubPreviewFrame == null}
            runStates={viewedRunId === null ? runStates : []}
            onLoadCheckpoint={viewedRunId === null ? handleLoadCheckpoint : undefined}
            onSaveCheckpoint={viewedRunId === null && state ? handleSaveCheckpoint : undefined}
          />
        </div>
      </aside>
    </main>
  );
}

function runCostDisplay(events: TraceEvent[]): string {
  // Walk events in reverse to find the latest run_cost_usd
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "budget_exceeded") {
      const cost = (e.payload as Record<string, unknown>).run_cost_usd;
      if (typeof cost === "number") return `$${cost.toFixed(3)} LIMIT`;
    }
    if (e.type === "llm_call") {
      const usage = (e.payload as Record<string, unknown>).usage as Record<string, unknown> | undefined;
      const cost = usage?.run_cost_usd;
      if (typeof cost === "number") return `$${cost.toFixed(3)}`;
    }
  }
  return "-";
}

function Metric({ label, value }: { label: string; value: string | number }) {
  const textValue = String(value);
  return (
    <div className="metric">
      <span>{label}</span>
      <strong title={textValue}>{value}</strong>
    </div>
  );
}
