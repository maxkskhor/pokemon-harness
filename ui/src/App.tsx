import { Pause, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  API_BASE,
  AgentDefinition,
  HarnessAgent,
  PokemonState,
  RomInfo,
  RunSummary,
  SavedState,
  TraceEvent,
  deleteRunState,
  frameThumbnailUrl,
  getHealth,
  getState,
  launchAgent,
  listAgents,
  listHarnesses,
  listRoms,
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
  steerHarness,
  stopHarness,
  terminateAgent,
  traceUrl,
  wsUrl,
} from "./api";
import { AgentPanel } from "./agents/AgentPanel";
import { Checkpoints } from "./checkpoints/Checkpoints";
import { JourneyPanel } from "./journey/JourneyPanel";
import { ReplayBar } from "./checkpoints/ReplayBar";
import { RunPicker } from "./run-picker/RunPicker";
import { StatusPanel } from "./status/StatusPanel";
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
  const [agentDefs, setAgentDefs] = useState<AgentDefinition[]>([]);
  const [roms, setRoms] = useState<RomInfo[]>([]);
  const [selectedRom, setSelectedRom] = useState<string | null>(null);
  const [selectedHarnessId, setSelectedHarnessId] = useState<string | null>(null);
  const [runStates, setRunStates] = useState<SavedState[]>([]);
  const [sharedStates, setSharedStates] = useState<SavedState[]>([]);
  const [checkpointName, setCheckpointName] = useState("");
  const [steerText, setSteerText] = useState("");
  const [runHistory, setRunHistory] = useState<RunSummary[]>([]);
  const [viewedRunId, setViewedRunId] = useState<string | null>(null);
  const [frameNumbers, setFrameNumbers] = useState<number[]>([]);
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
  //   "start"  – agent selection only; click starts fresh from `bedroom`.
  //   "resume" – user explicitly picked a past run; click branches from that run's checkpoint.
  // Changing the agent must never silently imply resume.
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
    listRoms()
      .then((available) => {
        setRoms(available);
        setSelectedRom((current) => current ?? available.find((r) => r.default)?.filename ?? available[0]?.filename ?? null);
      })
      .catch(() => setRoms([]));
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
          // Only traced events persist a frame thumbnail — playback_frame ticks
          // don't, so adding them would put broken images on the replay timeline.
          if (event.frame != null && !NOISY_EVENT_TYPES.has(event.type)) {
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
  // selection with the harness that started that run. Subsequent runs are
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

  // Poll harness registry + agent process list
  useEffect(() => {
    const poll = async () => {
      try {
        const [agents, defs] = await Promise.all([listHarnesses(), listAgents()]);
        setHarnessAgents(agents);
        setAgentDefs(defs);
        setSelectedHarnessId((prev) => {
          if (prev && agents.find((a) => a.id === prev)) return prev;
          return agents[0]?.id ?? null;
        });
      } catch {
        setHarnessAgents([]);
        setAgentDefs([]);
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
      setScrubPreviewFrame(null);
      return;
    }
    try {
      const frames = await listRunFrames(activeRunId);
      setFrameNumbers(frames);
    } catch {
      setFrameNumbers([]);
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
    setScrubPreviewFrame(null);
    if (runId === null) {
      // Back to the active (live) run. Replay the persisted trace; live WS events resume.
      const activeRunId = eventRunIdRef.current ?? state?.run_id ?? null;
      if (activeRunId) {
        await refreshTraces(activeRunId);
        await refreshFrames(activeRunId);
        await refreshCheckpoints(activeRunId);
      } else {
        setEvents([]);
        setFrameNumbers([]);
        await refreshCheckpoints(null);
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
    setScrubPreviewFrame(null);
    const activeRunId = eventRunIdRef.current ?? state?.run_id ?? null;
    if (activeRunId) {
      void refreshTraces(activeRunId);
      void refreshFrames(activeRunId);
    }
    await runAction(() => playHarness(selectedHarnessId, selectedRom), false);
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

  async function handleSteer() {
    const message = steerText.trim();
    if (!selectedHarnessId || !message) return;
    await runAction(() => steerHarness(selectedHarnessId, message), false);
    setSteerText("");
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
      setScrubPreviewFrame(null);
      eventRunIdRef.current = result.run_id;
      await refreshTraces(result.run_id);
      await refreshFrames(result.run_id);
      await refreshCheckpoints(result.run_id);
      await refreshRunHistory();
      return result;
    }, true);
  }

  async function handleLaunchAgent(name: string) {
    await runAction(() => launchAgent(name), false);
  }

  async function handleTerminateAgent(name: string) {
    await runAction(() => terminateAgent(name), false);
  }

  // What the main screen shows: a scrubbed/replayed frame, the viewed past
  // run's last captured frame, or the live emulator screenshot.
  const screenRunId = viewedRunId ?? state?.run_id ?? null;
  let screenSrc: string | null = null;
  if (scrubPreviewFrame != null && screenRunId) {
    screenSrc = frameThumbnailUrl(screenRunId, scrubPreviewFrame);
  } else if (isViewingPastRun && viewedRunId) {
    const lastFrame = frameNumbers.at(-1);
    screenSrc = lastFrame != null ? frameThumbnailUrl(viewedRunId, lastFrame) : null;
  } else if (state) {
    screenSrc = screenshotUrl(imageVersion);
  }

  const liveStatus = !isViewingPastRun ? state?.status ?? null : null;

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
          <div className="topbar-context">
            {isViewingPastRun ? (
              <span className="screen-mode-badge replaying">viewing {viewedRunId}</span>
            ) : state ? (
              <span className="screen-mode-badge live">
                {state.rom.title ?? state.rom.filename} · {state.run_id}
              </span>
            ) : null}
          </div>
        </header>

        {error ? <pre className="error">{error}</pre> : null}

        <JourneyPanel events={events} />

        <div className="screen-wrap">
          {screenSrc ? (
            <img className="game-screen" src={screenSrc} alt="Pokemon emulator frame" />
          ) : (
            <div className="empty-screen">
              {isViewingPastRun ? "No captured frames for this run" : "No active run — launch an agent and press Start"}
            </div>
          )}
          {scrubPreviewFrame != null && <span className="screen-overlay">REPLAY</span>}
        </div>

        <ReplayBar
          runId={screenRunId}
          frames={frameNumbers}
          previewFrame={scrubPreviewFrame}
          checkpoints={runStates}
          busy={busy}
          canRewind={!isViewingPastRun && state != null}
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
                disabled={!state || busy || isViewingPastRun}
                title={mode === "paused" ? "Freeze background; agent still acts" : `Run at ${mode}`}
              >
                {mode === "paused" ? <Pause size={14} /> : null}{mode}
              </button>
            ))}
          </div>
          <div className="metric-strip">
            <Metric label="Frame" value={state?.frame ?? "-"} />
            <Metric label="Spend" value={runCostDisplay(events)} />
          </div>
        </section>

        <section className="steer-band">
          <input
            className="steer-input"
            type="text"
            placeholder={
              selectedHarness?.status === "running"
                ? "Steer the agent — e.g. 'go back south, you passed the exit'"
                : "Steering is available while an agent is running"
            }
            value={steerText}
            onChange={(event) => setSteerText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void handleSteer();
            }}
            disabled={busy || selectedHarness?.status !== "running"}
          />
          <button
            onClick={() => void handleSteer()}
            disabled={busy || !steerText.trim() || selectedHarness?.status !== "running"}
            title="Send a one-off instruction the agent folds into its next turn"
          >
            Steer
          </button>
        </section>

        <StatusPanel status={liveStatus} />

        <Checkpoints
          state={state}
          viewedRunId={viewedRunId}
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
          <AgentPanel
            agents={agentDefs}
            harnessAgents={harnessAgents}
            selectedHarnessId={selectedHarnessId}
            onSelectHarness={setSelectedHarnessId}
            roms={roms}
            selectedRom={selectedRom}
            onSelectRom={setSelectedRom}
            primaryIntent={primaryIntent}
            resumeBlocker={resumeBlocker}
            busy={busy}
            onPlay={handleHarnessPlay}
            onResume={handleHarnessResume}
            onStop={handleHarnessStop}
            onReset={handleHarnessReset}
            onLaunch={handleLaunchAgent}
            onTerminate={handleTerminateAgent}
          />
          <RunPicker
            activeRunId={state?.run_id ?? null}
            viewedRunId={viewedRunId}
            runHistory={runHistory}
            onSelectRun={handleSelectRun}
          />
          <div className="trace-title-row">
            <div>
              <h2>Trace</h2>
              <span>
                {events.length} events
                {viewedRunId ? ` · viewing ${viewedRunId}` : ""}
              </span>
            </div>
            <button onClick={handleReloadTraces} disabled={busy || (!eventRunIdRef.current && !viewedRunId)}>
              <RefreshCw size={14} /> Reload
            </button>
          </div>
          <TraceFilters filters={traceFilters} onChange={setTraceFilters} showImages={showImages} onToggleImages={setShowImages} />
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
