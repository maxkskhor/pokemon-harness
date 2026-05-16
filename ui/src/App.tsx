import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Pause, Play, RotateCcw, Save, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  API_BASE,
  HarnessAgent,
  PokemonState,
  TraceEvent,
  getState,
  listHarnesses,
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

function eventLabel(event: TraceEvent): string {
  const frame = event.frame === null ? "" : `f${event.frame}`;
  const turn = event.turn_id ? ` ${event.turn_id}` : "";
  return `${frame}${turn} ${event.type}`.trim();
}

function formatPayload(payload: Record<string, unknown>): string {
  return JSON.stringify(payload, null, 2);
}

export function App() {
  const [runId, setRunId] = useState("manual-run");
  const [state, setState] = useState<PokemonState | null>(null);
  const [harnessEvents, setHarnessEvents] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("bedroom");
  const [imageVersion, setImageVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [harnessAgents, setHarnessAgents] = useState<HarnessAgent[]>([]);
  const [selectedHarnessId, setSelectedHarnessId] = useState<string | null>(null);
  const eventRunIdRef = useRef<string | null>(null);

  const selectedHarness = harnessAgents.find((h) => h.id === selectedHarnessId) ?? null;

  // Restore active run on page load
  useEffect(() => {
    getState()
      .then((next) => {
        setState(next);
        setImageVersion((v) => v + 1);
        eventRunIdRef.current = next.run_id;
        void refreshTraces(next.run_id);
      })
      .catch(() => {});
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
        if (eventRunIdRef.current !== event.run_id) {
          eventRunIdRef.current = event.run_id;
          setHarnessEvents([]);
        }
        if (event.source === "harness") {
          setHarnessEvents((events) => [...events.slice(-199), event]);
        } else {
          setImageVersion((version) => version + 1);
          // playback_frame fires every 0.1s — skip full state refresh, image bump is enough
          if (event.type !== "playback_frame") {
            void refreshState(false);
          }
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
    const harnessResponse = await fetch(traceUrl(activeRunId, "harness"));
    if (harnessResponse.ok) setHarnessEvents(await harnessResponse.json());
  }

  async function handleStart() {
    const next = await runAction(() => startRun(runId), false);
    if (next) {
      setState(next);
      eventRunIdRef.current = next.run_id;
      await refreshTraces(next.run_id);
      setImageVersion((v) => v + 1);
    }
  }

  async function handleStop() {
    await runAction(() => stopRun(), false);
    setState(null);
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
            <span>{API_BASE} {wsConnected ? "● connected" : "○ disconnected"}</span>
          </div>
          <div className="run-controls">
            <input value={runId} onChange={(e) => setRunId(e.target.value)} aria-label="Run id" />
            <button onClick={handleStart} disabled={busy}>
              <Play size={14} /> Start
            </button>
            <button onClick={handleStop} disabled={busy || !state}>
              <Square size={14} /> Stop
            </button>
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
            <button className="up" onClick={() => runAction(() => pressButton("UP"))} disabled={!state || busy}><ArrowUp size={18} /></button>
            <button className="left" onClick={() => runAction(() => pressButton("LEFT"))} disabled={!state || busy}><ArrowLeft size={18} /></button>
            <button className="right" onClick={() => runAction(() => pressButton("RIGHT"))} disabled={!state || busy}><ArrowRight size={18} /></button>
            <button className="down" onClick={() => runAction(() => pressButton("DOWN"))} disabled={!state || busy}><ArrowDown size={18} /></button>
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

          <div className="save-controls">
            <input value={saveName} onChange={(e) => setSaveName(e.target.value)} aria-label="Save state name" />
            <button onClick={() => runAction(() => saveState(saveName))} disabled={!state || busy}>
              <Save size={14} /> Save
            </button>
            <button onClick={() => runAction(() => loadState(saveName))} disabled={!state || busy}>
              Load
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
      </section>

      <aside className="trace-pane">
        <header className="harness-header">
          <h2>Harness</h2>
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
              <Play size={14} /> Play
            </button>
            <button
              onClick={handleHarnessStop}
              disabled={busy || !selectedHarness || selectedHarness.status === "idle"}
            >
              <Square size={14} /> Stop
            </button>
          </div>
          {selectedHarness && (
            <span className="harness-status" data-status={selectedHarness.status}>
              {selectedHarness.status}
            </span>
          )}
          {selectedHarness?.error && (
            <pre className="harness-error">{selectedHarness.error}</pre>
          )}
        </header>

        <div className="harness-events">
          <TraceList events={harnessEvents} />
        </div>
      </aside>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TraceList({ events }: { events: TraceEvent[] }) {
  if (!events.length) {
    return <div className="trace-empty">No events yet</div>;
  }
  return (
    <ol className="trace-list">
      {events
        .slice()
        .reverse()
        .map((event, index) => (
          <TraceItem key={`${event.timestamp}-${event.type}-${index}`} event={event} />
        ))}
    </ol>
  );
}

function TraceItem({ event }: { event: TraceEvent }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li onClick={() => setExpanded((e) => !e)} className="trace-item">
      <div className="trace-head">
        <span>{eventLabel(event)}</span>
        <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
      </div>
      {expanded ? <pre>{formatPayload(event.payload)}</pre> : null}
    </li>
  );
}
