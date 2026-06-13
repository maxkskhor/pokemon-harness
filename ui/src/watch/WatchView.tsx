import { MessagesSquare, Send, Sparkles, Target } from "lucide-react";
import { useState } from "react";

import type { GameStatus, TraceEvent } from "../api";
import { JourneyPanel } from "../journey/JourneyPanel";
import { StatusPanel } from "../status/StatusPanel";
import { Conversation } from "./Conversation";
import { buildThoughts, runCost } from "./thought";

const SPEEDS = ["paused", "1x", "5x", "max"];

export function WatchView({
  screenSrc,
  runId,
  isViewingPastRun,
  status,
  events,
  thinking,
  canSteer,
  onSteer,
  speedMode,
  onSetSpeed,
  speedDisabled,
}: {
  screenSrc: string | null;
  runId: string | null;
  isViewingPastRun: boolean;
  status: GameStatus | null;
  events: TraceEvent[];
  thinking: boolean;
  canSteer: boolean;
  onSteer: (message: string) => void;
  speedMode: string | null;
  onSetSpeed: (mode: string) => void;
  speedDisabled: boolean;
}) {
  const thoughts = buildThoughts(events);
  const latest = thoughts.at(-1) ?? null;
  const objective = latest?.goal ?? null;
  const cost = runCost(events);

  return (
    <div className="watch">
      <section className="watch-main">
        <div className="watch-screen-wrap">
          {screenSrc ? (
            <img className="watch-screen" src={screenSrc} alt="Pokemon game screen" />
          ) : (
            <div className="watch-screen-empty">
              {isViewingPastRun
                ? "No captured frames for this run"
                : "No active run — launch an agent and press Start"}
            </div>
          )}
          {thinking && (
            <div className="watch-thinking-badge">
              <Sparkles size={13} /> thinking…
            </div>
          )}
        </div>

        <div className="watch-speed">
          {SPEEDS.map((mode) => (
            <button key={mode} className={speedMode === mode ? "active" : ""} onClick={() => onSetSpeed(mode)} disabled={speedDisabled}>
              {mode}
            </button>
          ))}
        </div>

        <div className="objective-card">
          <span className="objective-label">
            <Target size={13} /> Current objective
          </span>
          <p className="objective-text">{objective ?? "Waiting for the agent to start…"}</p>
        </div>

        <JourneyPanel events={events} />
        <StatusPanel status={status} />

        <div className="watch-stats">
          <Stat label="Turn" value={latest?.turnIndex != null ? `#${latest.turnIndex}` : "—"} />
          <Stat label="Spend" value={cost != null ? `$${cost.toFixed(3)}` : "—"} />
          <Stat label="Location" value={status?.map_name ?? "—"} />
        </div>
      </section>

      <section className="watch-convo">
        <div className="panel-title">
          <MessagesSquare size={14} /> Conversation
          {thinking && <span className="panel-live"><span className="dot-pulse" /> live</span>}
        </div>
        <Conversation events={events} runId={runId} />
        <SteerBox canSteer={canSteer} onSteer={onSteer} />
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="watch-stat">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function SteerBox({ canSteer, onSteer }: { canSteer: boolean; onSteer: (m: string) => void }) {
  const [text, setText] = useState("");
  function send() {
    const m = text.trim();
    if (!m || !canSteer) return;
    onSteer(m);
    setText("");
  }
  return (
    <div className="steer-box">
      <input
        type="text"
        placeholder={canSteer ? "Nudge the agent — it sees this on its next turn…" : "Steering available while running"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
        disabled={!canSteer}
      />
      <button onClick={send} disabled={!canSteer || !text.trim()} title="Send guidance for the next turn">
        <Send size={14} />
      </button>
    </div>
  );
}
