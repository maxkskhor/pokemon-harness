import { Flag, RotateCcw, Send, Sparkles, Target } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { GameStatus, TraceEvent } from "../api";
import { JourneyPanel } from "../journey/JourneyPanel";
import { StatusPanel } from "../status/StatusPanel";
import { buildThoughts, runCost, type Thought } from "./thought";

const SPEEDS = ["paused", "1x", "5x", "max"];

export function WatchView({
  screenSrc,
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
      <div className="watch-stage">
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
            <button
              key={mode}
              className={speedMode === mode ? "active" : ""}
              onClick={() => onSetSpeed(mode)}
              disabled={speedDisabled}
            >
              {mode}
            </button>
          ))}
        </div>
        <ThoughtStream thoughts={thoughts} thinking={thinking} />
      </div>

      <aside className="watch-side">
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

        <SteerBox canSteer={canSteer} onSteer={onSteer} />
      </aside>
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

function ThoughtStream({ thoughts, thinking }: { thoughts: Thought[]; thinking: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const atBottom = useRef(true);

  function onScroll() {
    const el = ref.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }

  useEffect(() => {
    if (atBottom.current) ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [thoughts.length, thinking]);

  const recent = thoughts.slice(-40);

  return (
    <div className="thought-stream" ref={ref} onScroll={onScroll}>
      <div className="thought-stream-title">
        <Sparkles size={13} /> Agent narration
      </div>
      {recent.length === 0 && <p className="thought-empty">The agent's reasoning will appear here as it plays.</p>}
      {recent.map((t, i) => (
        <ThoughtCard key={t.turnId} thought={t} isLast={i === recent.length - 1} thinking={thinking} />
      ))}
    </div>
  );
}

function ThoughtCard({ thought, isLast, thinking }: { thought: Thought; isLast: boolean; thinking: boolean }) {
  const [showObs, setShowObs] = useState(false);
  const live = isLast && thinking && thought.status === "running";
  return (
    <div className={`thought${isLast ? " thought-latest" : ""}`} data-status={thought.status}>
      <div className="thought-head">
        <span className="thought-turn">
          {thought.turnIndex != null ? `turn ${thought.turnIndex}` : thought.turnId}
        </span>
        {live && <span className="thought-live"><span className="dot-pulse" /> deciding…</span>}
      </div>

      {thought.steer && (
        <div className="thought-banner steer">🧑 You: {thought.steer}</div>
      )}
      {thought.milestone && (
        <div className="thought-banner milestone"><Flag size={12} /> Reached: {thought.milestone}</div>
      )}
      {thought.rollback && (
        <div className="thought-banner rollback"><RotateCcw size={12} /> Rolled back: {thought.rollback}</div>
      )}

      {thought.reasoning && <p className="thought-reasoning">{thought.reasoning}</p>}
      {thought.action && (
        <p className="thought-action">
          <span className="thought-action-chip">did</span>
          {thought.action}
        </p>
      )}

      {thought.observation && (
        <>
          <button className="thought-obs-toggle" onClick={() => setShowObs((v) => !v)}>
            {showObs ? "hide what it saw" : "what it saw"}
          </button>
          {showObs && <pre className="thought-obs">{thought.observation}</pre>}
        </>
      )}
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
        placeholder={canSteer ? "Nudge the agent…" : "Steering available while running"}
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
