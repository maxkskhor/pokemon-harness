import { Activity, Pause, Play, RefreshCw, RotateCcw, Square } from "lucide-react";
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

  const selectedHarness = harnessAgents.find((h) => h.id === selectedHarnessId) ?? null;

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

        if (event.source === "env") {
          setImageVersion((version) => version + 1);
          // playback_frame fires every 0.1s — skip full state refresh, image bump is enough
          if (event.type !== "playback_frame") {
            void refreshState(false);
          }
          if (event.type === "state_saved" || event.type === "state_loaded") {
            void refreshCheckpoints(event.run_id);
          }
          if (event.type === "run_started" || event.type === "run_stopped") {
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
    try {
      const next = await getState();
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
      }
      return;
    }
    await refreshTraces(runId);
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
    await runAction(() => stopHarness(selectedHarnessId), false);
  }

  async function handleHarnessReset() {
    if (!selectedHarnessId) return;
    await runAction(() => resetHarness(selectedHarnessId), false);
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
              <button
                onClick={handleHarnessPlay}
                disabled={busy || !selectedHarness || selectedHarness.status === "running" || selectedHarness.status === "disconnected"}
              >
                <Play size={14} /> Play agent
              </button>
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
