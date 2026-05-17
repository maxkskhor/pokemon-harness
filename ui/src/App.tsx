import { Activity, AlertCircle, AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bot, ChevronDown, ChevronRight, Download, Gamepad2, MessageSquareText, Pause, Play, RefreshCw, RotateCcw, Save, Square, Trash2 } from "lucide-react";
import type { ComponentType } from "react";
import type { Dispatch, SetStateAction } from "react";
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
  listRunStates,
  listRuns,
  listSharedStates,
  loadState,
  playHarness,
  pressButton,
  saveState,
  screenshotUrl,
  setSpeed,
  startRun,
  stepFrames,
  stopHarness,
  stopRun,
  traceUrl,
  wsUrl,
} from "./api";

const speeds = ["paused", "1x", "5x", "max"];
const filterTypes = ["decision", "action", "state", "lifecycle", "warning", "error"] as const;
type FilterType = (typeof filterTypes)[number];

// Env events that fire continuously (~10/sec at max speed). Skip in timeline.
const NOISY_EVENT_TYPES = new Set(["playback_frame"]);

function eventCategory(event: TraceEvent): FilterType {
  switch (event.type) {
    case "decision":
      return "decision";
    case "action":
    case "button_press":
    case "button_sequence":
    case "step":
      return "action";
    case "state_saved":
    case "state_loaded":
    case "speed_changed":
    case "run_started":
    case "run_stopped":
      return "state";
    case "warning":
      return "warning";
    case "error":
      return "error";
    default:
      return "lifecycle";
  }
}

function eventLabel(event: TraceEvent): string {
  const turn = event.turn_id ? `${event.turn_id} ` : "";
  return `${turn}${event.type}`.trim();
}

function formatPayload(payload: Record<string, unknown>): string {
  return JSON.stringify(payload, null, 2);
}

function payloadText(payload: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function formatPosition(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const pos = value as Record<string, unknown>;
  if (pos.map_id == null && pos.x == null && pos.y == null) return null;
  return `map ${pos.map_id ?? "-"} (${pos.x ?? "-"},${pos.y ?? "-"})`;
}

function summarizeEvent(event: TraceEvent): string {
  const payload = event.payload;
  if (event.type === "action") {
    // Legacy event shape (pre 2026-05-17) — env now emits button_press as the single source of truth.
    const button = payload.button ?? payload.action ?? payload.input ?? "-";
    const frames = payload.frames != null ? `, frames=${payload.frames}` : "";
    const before = formatPosition(payload.before);
    const after = formatPosition(payload.after);
    const movement = before && after ? ` — ${before} → ${after}` : "";
    return `press_button(${button}${frames})${movement}`;
  }
  if (event.type === "button_press") {
    const button = payload.button ?? "-";
    const frames = payload.frames != null ? `, frames=${payload.frames}` : "";
    const before = formatPosition(payload.before);
    const after = formatPosition(payload.after);
    const movement = before && after ? ` — ${before} → ${after}` : "";
    return `button_press(${button}${frames})${movement}`;
  }
  if (event.type === "button_sequence") {
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    const before = formatPosition(payload.before);
    const after = formatPosition(payload.after);
    const movement = before && after ? ` — ${before} → ${after}` : "";
    return `button_sequence(${steps.length} step${steps.length === 1 ? "" : "s"})${movement}`;
  }
  if (event.type === "step") {
    return `step ${payload.frames ?? "?"}f`;
  }
  if (event.type === "decision") {
    const action = payload.action ?? payload.button ?? "-";
    return `Chose ${action}`;
  }
  if (event.type === "lifecycle") {
    return String(payload.status ?? event.type).replaceAll("_", " ");
  }
  if (event.type === "warning") {
    return payloadText(payload, ["message", "warning"]) ?? "Warning";
  }
  if (event.type === "error") {
    return payloadText(payload, ["message", "error"]) ?? "Error";
  }
  if (event.type === "state_saved") {
    return `saved “${payload.name ?? "?"}” @ frame ${payload.frame ?? "?"}`;
  }
  if (event.type === "state_loaded") {
    return `loaded “${payload.name ?? "?"}”`;
  }
  if (event.type === "speed_changed") {
    return `speed → ${payload.mode ?? "?"}`;
  }
  if (event.type === "run_started") {
    const rom = payload.rom as Record<string, unknown> | undefined;
    const title = rom && typeof rom === "object" ? rom.title : null;
    return `run started${title ? ` (${title})` : ""}`;
  }
  if (event.type === "run_stopped") {
    return "run stopped";
  }
  return payloadText(payload, ["summary", "message", "content", "text"]) ?? event.type.replaceAll("_", " ");
}

function eventTone(event: TraceEvent): string {
  return eventCategory(event);
}

const CATEGORY_ICON: Record<FilterType, ComponentType<{ size?: number }>> = {
  decision: Bot,
  action: Gamepad2,
  state: Save,
  lifecycle: Activity,
  warning: AlertTriangle,
  error: AlertCircle,
};

function groupLabel(event: TraceEvent): string {
  return event.turn_id ?? "Session";
}

function formatDelta(current: TraceEvent, previous: TraceEvent | null): string {
  if (!previous) return "+0.0 s";
  const deltaMs = new Date(current.timestamp).getTime() - new Date(previous.timestamp).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 0) return "+0.0 s";
  return `+${(deltaMs / 1000).toFixed(1)} s`;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

export function App() {
  const [runId, setRunId] = useState("manual-run");
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
  const viewedRunIdRef = useRef<string | null>(null);
  viewedRunIdRef.current = viewedRunId;
  const [traceFilters, setTraceFilters] = useState<Record<FilterType, boolean>>({
    decision: true,
    action: true,
    state: true,
    lifecycle: true,
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
        }

        if (viewingPast) return;

        if (eventRunIdRef.current !== event.run_id) {
          eventRunIdRef.current = event.run_id;
          setEvents([]);
          void refreshCheckpoints(event.run_id);
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
      } catch {}
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
    } catch {}
  }

  async function refreshTraces(activeRunId: string) {
    const [envResponse, harnessResponse] = await Promise.all([
      fetch(traceUrl(activeRunId, "env")),
      fetch(traceUrl(activeRunId, "harness")),
    ]);
    const envEvents: TraceEvent[] = envResponse.ok ? await envResponse.json() : [];
    const harnessEvents: TraceEvent[] = harnessResponse.ok ? await harnessResponse.json() : [];
    const merged = [...envEvents, ...harnessEvents]
      .filter((event) => !NOISY_EVENT_TYPES.has(event.type))
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    setEvents(merged);
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
    await runAction(() => refreshTraces(targetRunId), false);
    void refreshRunHistory();
  }

  async function handleSelectRun(runId: string | null) {
    setViewedRunId(runId);
    if (runId === null) {
      // Back to the active (live) run. Replay the persisted trace; live WS events resume.
      const activeRunId = eventRunIdRef.current ?? state?.run_id ?? null;
      if (activeRunId) await refreshTraces(activeRunId);
      return;
    }
    eventRunIdRef.current = runId;
    await refreshTraces(runId);
  }

  async function handleStart() {
    const next = await runAction(() => startRun(runId), false);
    if (next) {
      setState(next);
      eventRunIdRef.current = next.run_id;
      await refreshTraces(next.run_id);
      await refreshCheckpoints(next.run_id);
      setImageVersion((v) => v + 1);
    }
  }

  async function handleStop() {
    await runAction(() => stopRun(), false);
    setState(null);
    setRunStates([]);
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
  }

  async function handleDeleteCheckpoint(name: string) {
    if (!state) return;
    await runAction(() => deleteRunState(state.run_id, name), false);
    await refreshCheckpoints(state.run_id);
  }

  async function handleHarnessPlay() {
    if (!selectedHarnessId) return;
    await runAction(() => playHarness(selectedHarnessId), false);
  }

  async function handleHarnessStop() {
    if (!selectedHarnessId) return;
    await runAction(() => stopHarness(selectedHarnessId), false);
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
          <div className="emulator-controls" aria-label="Emulator controls">
            <span>Emulator</span>
            <div className="run-controls">
              <input value={runId} onChange={(e) => setRunId(e.target.value)} aria-label="Run id" />
              <button onClick={handleStart} disabled={busy}>
                <Play size={14} /> Start run
              </button>
              <button onClick={handleStop} disabled={busy || !state}>
                <Square size={14} /> Stop run
              </button>
            </div>
          </div>
        </header>

        {error ? <pre className="error">{error}</pre> : null}

        <div className="screen-wrap">
          {state ? (
            <img className="game-screen" src={screenshotUrl(imageVersion)} alt="Pokemon emulator frame" />
          ) : (
            <div className="empty-screen">No active run</div>
          )}
        </div>

        <section className="control-band">
          <div className="dpad">
            <button aria-label="UP" className="up" onClick={() => runAction(() => pressButton("UP"))} disabled={!state || busy}><ArrowUp size={18} /></button>
            <button aria-label="LEFT" className="left" onClick={() => runAction(() => pressButton("LEFT"))} disabled={!state || busy}><ArrowLeft size={18} /></button>
            <button aria-label="RIGHT" className="right" onClick={() => runAction(() => pressButton("RIGHT"))} disabled={!state || busy}><ArrowRight size={18} /></button>
            <button aria-label="DOWN" className="down" onClick={() => runAction(() => pressButton("DOWN"))} disabled={!state || busy}><ArrowDown size={18} /></button>
          </div>

          <div className="button-cluster">
            {["A", "B", "START", "SELECT"].map((btn) => (
              <button key={btn} onClick={() => runAction(() => pressButton(btn))} disabled={!state || busy}>{btn}</button>
            ))}
          </div>

          <div className="speed-controls">
            {speeds.map((mode) => (
              <button
                key={mode}
                className={state?.speed_mode === mode ? "selected" : ""}
                onClick={() => runAction(() => setSpeed(mode))}
                disabled={!state || busy}
              >
                {mode === "paused" ? <Pause size={14} /> : null}{mode}
              </button>
            ))}
            <button onClick={() => runAction(() => stepFrames(30))} disabled={!state || busy}>
              <RotateCcw size={14} /> 30f
            </button>
          </div>

        </section>

        <section className="state-grid">
          <Metric label="Run" value={state?.run_id ?? "-"} />
          <Metric label="Frame" value={state?.frame ?? "-"} />
          <Metric label="Speed" value={state?.speed_mode ?? "-"} />
          <Metric label="ROM" value={state?.rom.filename ?? "-"} />
          <Metric label="Map" value={state?.pokemon.map_id ?? "-"} />
          <Metric label="X/Y" value={state ? `${state.pokemon.x ?? "-"} / ${state.pokemon.y ?? "-"}` : "-"} />
          <Metric label="Party" value={state?.pokemon.party_count ?? "-"} />
          <Metric label="Symbols" value={state?.rom.symbols_loaded ? "loaded" : "missing"} />
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
          <div className="run-picker" aria-label="View run">
            <span>View run</span>
            <select
              value={viewedRunId ?? ""}
              onChange={(event) => handleSelectRun(event.currentTarget.value || null)}
            >
              <option value="">{state ? `Active · ${state.run_id}` : "Active (no run)"}</option>
              {runHistory
                .filter((entry) => !entry.active)
                .map((entry) => (
                  <option key={entry.run_id} value={entry.run_id}>
                    {entry.run_id} · {formatBytes(entry.bytes)} · {new Date(entry.modified_at).toLocaleString()}
                  </option>
                ))}
            </select>
          </div>
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
                      <option key={h.id} value={h.id}>{h.name}</option>
                    ))}
              </select>
              <button
                onClick={handleHarnessPlay}
                disabled={busy || !selectedHarness || selectedHarness.status === "running"}
              >
                <Play size={14} /> Play agent
              </button>
              <button
                onClick={handleHarnessStop}
                disabled={busy || !selectedHarness || selectedHarness.status === "idle"}
              >
                <Square size={14} /> Stop agent
              </button>
            </div>
          </div>
          <TraceFilters filters={traceFilters} onChange={setTraceFilters} />
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
            isRunning={selectedHarness?.status === "running" || selectedHarness?.status === "starting"}
          />
        </div>
      </aside>
    </main>
  );
}

function formatCheckpointTime(iso: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Checkpoints({
  state,
  runStates,
  sharedStates,
  checkpointName,
  onCheckpointNameChange,
  onSave,
  onLoad,
  onDelete,
  busy,
}: {
  state: PokemonState | null;
  runStates: SavedState[];
  sharedStates: SavedState[];
  checkpointName: string;
  onCheckpointNameChange: (value: string) => void;
  onSave: () => void;
  onLoad: (name: string) => void;
  onDelete: (name: string) => void;
  busy: boolean;
}) {
  const placeholder = state ? `chkpt-${state.frame}` : "chkpt-name";
  return (
    <section className="checkpoints" aria-label="Checkpoints">
      <header>
        <h3>Checkpoints</h3>
        <div className="checkpoints-save">
          <input
            value={checkpointName}
            onChange={(event) => onCheckpointNameChange(event.currentTarget.value)}
            placeholder={placeholder}
            aria-label="Checkpoint name (optional)"
            disabled={!state || busy}
          />
          <button onClick={onSave} disabled={!state || busy}>
            <Save size={14} /> Save
          </button>
        </div>
      </header>

      <div className="checkpoints-list">
        {runStates.length === 0 ? (
          <p className="checkpoints-empty">
            {state ? "No checkpoints yet — click Save to capture this frame." : "Start a run to save checkpoints."}
          </p>
        ) : (
          <ul>
            {runStates.map((entry) => (
              <li key={entry.name}>
                <div className="checkpoint-meta">
                  <strong title={entry.name}>{entry.name}</strong>
                  <span>
                    {formatCheckpointTime(entry.modified_at)}
                    {entry.frame != null ? ` · frame ${entry.frame}` : ""}
                  </span>
                </div>
                <div className="checkpoint-actions">
                  <button onClick={() => onLoad(entry.name)} disabled={!state || busy} title="Load this checkpoint">
                    <Download size={13} /> Load
                  </button>
                  <button
                    onClick={() => onDelete(entry.name)}
                    disabled={!state || busy}
                    title="Delete this checkpoint"
                    className="checkpoint-delete"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {sharedStates.length > 0 && (
          <>
            <p className="checkpoints-divider">Shared</p>
            <ul>
              {sharedStates.map((entry) => (
                <li key={`shared-${entry.name}`}>
                  <div className="checkpoint-meta">
                    <strong title={entry.name}>{entry.name}</strong>
                    <span>read-only · {formatCheckpointTime(entry.modified_at)}</span>
                  </div>
                  <div className="checkpoint-actions">
                    <button onClick={() => onLoad(entry.name)} disabled={!state || busy} title="Load this shared state">
                      <Download size={13} /> Load
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
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

function TraceFilters({
  filters,
  onChange,
}: {
  filters: Record<FilterType, boolean>;
  onChange: Dispatch<SetStateAction<Record<FilterType, boolean>>>;
}) {
  return (
    <div className="trace-filters" aria-label="Trace event filters">
      {filterTypes.map((type) => (
        <label key={type} className={filters[type] ? "selected" : ""}>
          <input
            type="checkbox"
            checked={filters[type]}
            onChange={(event) => {
              const checked = event.currentTarget.checked;
              onChange((current) => ({ ...current, [type]: checked }));
            }}
          />
          {type}
        </label>
      ))}
    </div>
  );
}

function TraceList({
  events,
  filters,
  isRunning,
}: {
  events: TraceEvent[];
  filters: Record<FilterType, boolean>;
  isRunning: boolean;
}) {
  const listRef = useRef<HTMLOListElement | null>(null);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [events.length, isRunning]);

  const visibleEvents = events.filter((event) => filters[eventCategory(event)]);
  const groupedEvents = visibleEvents.reduce<Array<{ label: string; events: TraceEvent[] }>>((groups, event) => {
    const label = groupLabel(event);
    const current = groups[groups.length - 1];
    if (current?.label === label) {
      current.events.push(event);
    } else {
      groups.push({ label, events: [event] });
    }
    return groups;
  }, []);
  const deltas = new Map<TraceEvent, string>();
  visibleEvents.forEach((event, index) => {
    deltas.set(event, formatDelta(event, visibleEvents[index - 1] ?? null));
  });

  if (!events.length) {
    return (
      <div className="trace-empty">
        {isRunning ? <span className="run-pulse" /> : null}
        {isRunning ? "Waiting for the next agent event..." : "No events yet"}
      </div>
    );
  }

  if (!visibleEvents.length) {
    return <div className="trace-empty">No events match the selected filters</div>;
  }

  return (
    <ol className="trace-list" ref={listRef}>
      {groupedEvents.map((group) => (
        <TraceGroup key={`${group.label}-${group.events[0]?.timestamp}`} group={group} deltas={deltas} />
      ))}
      {isRunning ? (
        <li className="trace-item trace-waiting">
          <span className="run-pulse" />
          <span>Agent is running, waiting for the next event...</span>
        </li>
      ) : null}
    </ol>
  );
}

function TraceGroup({
  group,
  deltas,
}: {
  group: { label: string; events: TraceEvent[] };
  deltas: Map<TraceEvent, string>;
}) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <li className="trace-group">
      <button className="trace-group-header" onClick={() => setCollapsed((value) => !value)}>
        {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        <span>{group.label}</span>
        <em>{group.events.length}</em>
      </button>
      {!collapsed ? (
        <ol>
          {group.events.map((event, index) => {
            return (
              <TraceItem
                key={`${event.timestamp}-${event.type}-${index}`}
                event={event}
                delta={deltas.get(event) ?? "+0.0 s"}
              />
            );
          })}
        </ol>
      ) : null}
    </li>
  );
}

function TraceItem({ event, delta }: { event: TraceEvent; delta: string }) {
  const [expanded, setExpanded] = useState(false);
  const [reasoningExpanded, setReasoningExpanded] = useState(false);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const [thumbnailEnlarged, setThumbnailEnlarged] = useState(false);
  const reasoning = payloadText(event.payload, ["reasoning", "thought", "thinking", "raw_thought"]);
  const category = eventCategory(event);
  const Icon = CATEGORY_ICON[category] ?? MessageSquareText;
  const showThumbnail = event.frame != null && !thumbnailFailed;
  return (
    <li className="trace-item" data-tone={category} data-source={event.source}>
      <button className="trace-head" onClick={() => setExpanded((e) => !e)}>
        <span className="trace-kind">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Icon size={14} />
          <span className="trace-source-badge" data-source={event.source}>{event.source === "harness" ? "agent" : "env"}</span>
          {eventLabel(event)}
        </span>
        <time>{new Date(event.timestamp).toLocaleTimeString()} <span>{delta}</span></time>
      </button>
      <p className="trace-summary">{summarizeEvent(event)}</p>
      {showThumbnail ? (
        <button
          type="button"
          className={thumbnailEnlarged ? "trace-thumbnail enlarged" : "trace-thumbnail"}
          onClick={() => setThumbnailEnlarged((value) => !value)}
          title={`Game screen at frame ${event.frame}. Click to ${thumbnailEnlarged ? "shrink" : "enlarge"}.`}
        >
          <img
            src={frameThumbnailUrl(event.run_id, event.frame as number)}
            alt={`Game screen at frame ${event.frame}`}
            loading="lazy"
            onError={() => setThumbnailFailed(true)}
          />
          <span className="trace-thumbnail-frame">frame {event.frame}</span>
        </button>
      ) : null}
      {reasoning ? (
        <div className="reasoning-wrap">
          <blockquote className={reasoningExpanded ? "reasoning expanded" : "reasoning"}>
            {reasoning}
          </blockquote>
          <button className="reasoning-toggle" onClick={() => setReasoningExpanded((value) => !value)}>
            {reasoningExpanded ? "Collapse reasoning" : "Expand reasoning"}
          </button>
        </div>
      ) : null}
      {expanded ? <pre>{formatPayload(event.payload)}</pre> : null}
    </li>
  );
}
