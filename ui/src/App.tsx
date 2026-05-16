import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Pause, Play, RotateCcw, Save, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  PokemonState,
  TraceEvent,
  getState,
  loadState,
  pressButton,
  saveState,
  screenshotUrl,
  setSpeed,
  startRun,
  stepFrames,
  stopRun,
  traceUrl,
  wsUrl,
} from "./api";

const buttons = ["UP", "LEFT", "RIGHT", "DOWN", "A", "B", "START", "SELECT"];
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
  const [envEvents, setEnvEvents] = useState<TraceEvent[]>([]);
  const [harnessEvents, setHarnessEvents] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("baseline");
  const [imageVersion, setImageVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const eventRunIdRef = useRef<string | null>(null);

  const latestEvents = useMemo(() => {
    return [...envEvents.slice(-12), ...harnessEvents.slice(-12)].sort((a, b) =>
      a.timestamp.localeCompare(b.timestamp),
    );
  }, [envEvents, harnessEvents]);

  // Restore any active run on page load.
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
          setEnvEvents([]);
          setHarnessEvents([]);
        }
        if (event.source === "env") {
          if (event.type !== "playback_frame") {
            setEnvEvents((events) => [...events.slice(-199), event]);
          }
          setImageVersion((version) => version + 1);
        } else {
          setHarnessEvents((events) => [...events.slice(-199), event]);
        }
        void refreshState(false);
      };
    }

    connect();
    return () => {
      alive = false;
      ws?.close();
    };
  }, []);

  async function runAction<T>(action: () => Promise<T>, refresh = true): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (refresh) {
        await refreshState();
      }
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
      if (updateImage) {
        setImageVersion((version) => version + 1);
      }
    } catch {
      return;
    }
  }

  async function refreshTraces(activeRunId: string) {
    const [envResponse, harnessResponse] = await Promise.all([
      fetch(traceUrl(activeRunId, "env")),
      fetch(traceUrl(activeRunId, "harness")),
    ]);
    if (envResponse.ok) {
      setEnvEvents(await envResponse.json());
    }
    if (harnessResponse.ok) {
      setHarnessEvents(await harnessResponse.json());
    }
  }

  async function handleStart() {
    const next = await runAction(() => startRun(runId), false);
    if (next) {
      setState(next);
      eventRunIdRef.current = next.run_id;
      await refreshTraces(next.run_id);
      setImageVersion((version) => version + 1);
    }
  }

  async function handleStop() {
    await runAction(() => stopRun(), false);
    setState(null);
  }

  async function handleSpeed(mode: string) {
    await runAction(() => setSpeed(mode));
  }

  async function handlePress(button: string) {
    const next = await runAction(() => pressButton(button));
    if (next) {
      setState(next);
    }
  }

  async function handleStep(frames: number) {
    const next = await runAction(() => stepFrames(frames));
    if (next) {
      setState(next);
    }
  }

  async function handleSave() {
    await runAction(() => saveState(saveName));
  }

  async function handleLoad() {
    const next = await runAction(() => loadState(saveName));
    if (next) {
      setState(next);
    }
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
            <input value={runId} onChange={(event) => setRunId(event.target.value)} aria-label="Run id" />
            <button onClick={handleStart} disabled={busy}>
              <Play size={16} /> Start
            </button>
            <button onClick={handleStop} disabled={busy || !state}>
              <Square size={16} /> Stop
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
            <button className="up" onClick={() => handlePress("UP")} disabled={!state || busy} title="Up">
              <ArrowUp size={20} />
            </button>
            <button className="left" onClick={() => handlePress("LEFT")} disabled={!state || busy} title="Left">
              <ArrowLeft size={20} />
            </button>
            <button className="right" onClick={() => handlePress("RIGHT")} disabled={!state || busy} title="Right">
              <ArrowRight size={20} />
            </button>
            <button className="down" onClick={() => handlePress("DOWN")} disabled={!state || busy} title="Down">
              <ArrowDown size={20} />
            </button>
          </div>

          <div className="button-cluster">
            {buttons.slice(4).map((button) => (
              <button key={button} onClick={() => handlePress(button)} disabled={!state || busy}>
                {button}
              </button>
            ))}
          </div>

          <div className="speed-controls">
            {speeds.map((mode) => (
              <button
                key={mode}
                className={state?.speed_mode === mode ? "selected" : ""}
                onClick={() => handleSpeed(mode)}
                disabled={!state || busy}
              >
                {mode === "paused" ? <Pause size={16} /> : null}
                {mode}
              </button>
            ))}
            <button onClick={() => handleStep(30)} disabled={!state || busy}>
              <RotateCcw size={16} /> 30f
            </button>
          </div>

          <div className="save-controls">
            <input value={saveName} onChange={(event) => setSaveName(event.target.value)} aria-label="Save state name" />
            <button onClick={handleSave} disabled={!state || busy}>
              <Save size={16} /> Save
            </button>
            <button onClick={handleLoad} disabled={!state || busy}>
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
        <section>
          <h2>Latest</h2>
          <TraceList events={latestEvents} compact />
        </section>
        <div className="split-traces">
          <section>
            <h2>Environment</h2>
            <TraceList events={envEvents} />
          </section>
          <section>
            <h2>Harness</h2>
            <TraceList events={harnessEvents} />
          </section>
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

function TraceList({ events, compact = false }: { events: TraceEvent[]; compact?: boolean }) {
  if (!events.length) {
    return <div className="trace-empty">No events</div>;
  }
  return (
    <ol className={compact ? "trace-list compact" : "trace-list"}>
      {events
        .slice()
        .reverse()
        .map((event, index) => (
          <li key={`${event.timestamp}-${event.type}-${index}`}>
            <div className="trace-head">
              <span>{eventLabel(event)}</span>
              <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
            </div>
            {!compact ? <pre>{formatPayload(event.payload)}</pre> : null}
          </li>
        ))}
    </ol>
  );
}
