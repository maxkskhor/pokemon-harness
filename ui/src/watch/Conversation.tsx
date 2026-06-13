import { ChevronDown, ChevronRight, Cpu, Flag, ImageIcon, RotateCcw, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { frameThumbnailUrl, type TraceEvent } from "../api";

/** A single agent↔model exchange for one turn. */
interface Exchange {
  turnId: string;
  turnIndex: number | null;
  goal: string | null;
  status: "ok" | "error" | "running";
  frame: number | null;
  observation: string | null;
  reasoning: string | null;
  toolCalls: { tool: string; args: Record<string, unknown>; result: Record<string, unknown>; via?: string }[];
  milestone: string | null;
  rollback: string | null;
  steer: string | null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function systemPrompt(events: TraceEvent[]): string | null {
  // The agent only includes the system prompt in the first turn's llm_call messages.
  const llm = events.find((e) => e.type === "llm_call");
  const messages = llm && Array.isArray(llm.payload.messages) ? llm.payload.messages : [];
  for (const m of messages) {
    const rec = m as Record<string, unknown>;
    if (rec.role !== "system") continue;
    const c = rec.content;
    if (typeof c === "string") return c;
    if (Array.isArray(c)) {
      const text = c.map((it) => (it && typeof it === "object" ? (it as Record<string, unknown>).text : "")).filter(Boolean).join("\n");
      if (text) return text;
    }
  }
  return null;
}

function buildExchanges(events: TraceEvent[]): Exchange[] {
  const order: string[] = [];
  const byTurn = new Map<string, TraceEvent[]>();
  for (const ev of events) {
    if (!ev.turn_id) continue;
    if (!byTurn.has(ev.turn_id)) {
      byTurn.set(ev.turn_id, []);
      order.push(ev.turn_id);
    }
    byTurn.get(ev.turn_id)!.push(ev);
  }
  return order.map((turnId) => {
    const te = byTurn.get(turnId)!;
    const started = te.find((e) => e.type === "turn_started");
    const finished = te.find((e) => e.type === "turn_finished");
    const obs = te.find((e) => e.type === "observation");
    const llm = te.find((e) => e.type === "llm_call");
    const actions = te.find((e) => e.type === "actions");
    const response = (llm?.payload.response ?? {}) as Record<string, unknown>;
    const rawCalls = Array.isArray(actions?.payload.tool_calls) ? (actions!.payload.tool_calls as unknown[]) : [];

    let status: Exchange["status"] = "running";
    if (finished) status = (finished.payload.status as "ok" | "error") ?? "ok";

    return {
      turnId,
      turnIndex: (started?.payload.turn_index as number | null) ?? null,
      goal: str(started?.payload.goal),
      status,
      frame: (obs?.frame as number | null) ?? (started?.payload.frame as number | null) ?? null,
      observation: obs ? str(obs.payload.text) : null,
      reasoning: str(response.reasoning) ?? str(response.content),
      toolCalls: rawCalls.map((c) => {
        const r = c as Record<string, unknown>;
        return {
          tool: String(r.tool ?? "?"),
          args: (r.args as Record<string, unknown>) ?? {},
          result: (r.result as Record<string, unknown>) ?? {},
          via: r.via as string | undefined,
        };
      }),
      milestone: te.find((e) => e.type === "milestone") ? str(te.find((e) => e.type === "milestone")!.payload.label) : null,
      rollback: te.find((e) => e.type === "rollback") ? str(te.find((e) => e.type === "rollback")!.payload.reason) : null,
      steer: te.find((e) => e.type === "steering") ? str(te.find((e) => e.type === "steering")!.payload.message) : null,
    };
  });
}

function resultBlurb(tool: string, result: Record<string, unknown>): string | null {
  if (result.error) return `⚠ ${result.error}`;
  const pos = (result.to ?? result.position) as Record<string, unknown> | undefined;
  if ((tool === "move" || tool === "goto") && pos) {
    const moved = result.moved ?? result.arrived;
    const where = `(${pos.x ?? "?"},${pos.y ?? "?"})`;
    if (result.entered_new_map) return `→ entered ${pos.map_name ?? `map ${pos.map}`}`;
    return moved === false ? `→ blocked at ${where}` : `→ ${where}`;
  }
  if (tool === "press" && Array.isArray(result.pressed)) return `→ pressed ${(result.pressed as string[]).join(" ")}`;
  if (tool === "battle_move") {
    const e = result.enemy_hp, b = result.enemy_hp_before;
    if (e != null && b != null) return `→ enemy HP ${b}→${e}${result.battle_over ? " (battle over)" : ""}`;
  }
  if (tool === "take_starter") return result.acquired ? "→ got starter" : "→ no starter";
  if (tool === "note") return "→ saved";
  return null;
}

function argStr(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
}

export function Conversation({
  events,
  runId,
  showImages = true,
  upToFrame = null,
  emptyHint,
}: {
  events: TraceEvent[];
  runId: string | null;
  showImages?: boolean;
  upToFrame?: number | null;
  emptyHint?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const currentRef = useRef<HTMLDivElement | null>(null);
  const atBottom = useRef(true);
  const [sysOpen, setSysOpen] = useState(false);

  let exchanges = buildExchanges(events);
  // Replay sync: only show exchanges up to the scrubbed frame.
  if (upToFrame != null) {
    exchanges = exchanges.filter((x) => x.frame == null || x.frame <= upToFrame);
  }
  const sys = systemPrompt(events);

  function onScroll() {
    const el = ref.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }
  useEffect(() => {
    if (upToFrame == null) {
      // Live: follow the newest turn at the bottom.
      if (atBottom.current) ref.current?.scrollTo({ top: ref.current.scrollHeight });
    } else {
      // Replay: scrub to a frame → bring the turn at that frame into view so the
      // conversation follows the playhead instead of staying pinned at turn 1.
      currentRef.current?.scrollIntoView({ block: "center", behavior: "auto" });
    }
  }, [exchanges.length, upToFrame]);

  return (
    <div className="convo" ref={ref} onScroll={onScroll}>
      {sys && (
        <div className="convo-system">
          <button onClick={() => setSysOpen((v) => !v)}>
            {sysOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />} System prompt
          </button>
          {sysOpen && <pre>{sys}</pre>}
        </div>
      )}

      {exchanges.length === 0 && (
        <p className="convo-empty">{emptyHint ?? "The agent↔model conversation will appear here, turn by turn."}</p>
      )}

      {exchanges.map((x, i) => {
        const last = i === exchanges.length - 1;
        const isCurrent = last && upToFrame != null;
        return (
          <div
            key={x.turnId}
            ref={isCurrent ? currentRef : undefined}
            className={`exchange${isCurrent ? " exchange-current" : ""}`}
            data-status={x.status}
          >
            <div className="exchange-head">
              <span className="exchange-turn">turn {x.turnIndex ?? "?"}</span>
              {x.goal && <span className="exchange-goal">{x.goal}</span>}
            </div>

            {x.steer && <div className="convo-banner steer">🧑 You: {x.steer}</div>}
            {x.milestone && <div className="convo-banner milestone"><Flag size={12} /> Reached: {x.milestone}</div>}
            {x.rollback && <div className="convo-banner rollback"><RotateCcw size={12} /> Rolled back: {x.rollback}</div>}

            {/* what the agent SENT the model */}
            <div className="msg msg-user">
              <div className="msg-role"><User size={12} /> agent → model</div>
              {showImages && x.frame != null && runId && (
                <div className="msg-image">
                  <img src={frameThumbnailUrl(runId, x.frame)} alt={`screen the model saw at frame ${x.frame}`} loading="lazy" />
                  <span><ImageIcon size={11} /> screen sent to the model</span>
                </div>
              )}
              {x.observation && <pre className="msg-observation">{x.observation}</pre>}
            </div>

            {/* what the model REPLIED */}
            {(x.reasoning || x.toolCalls.length > 0) && (
              <div className="msg msg-model">
                <div className="msg-role"><Cpu size={12} /> model</div>
                {x.reasoning && <p className="msg-reasoning">{x.reasoning}</p>}
                {x.toolCalls.map((tc, j) => (
                  <div key={j} className="msg-toolcall">
                    <code>{tc.tool}({argStr(tc.args)})</code>
                    {tc.via === "text" && <span className="via-text" title="recovered from the model's text">text</span>}
                    {resultBlurb(tc.tool, tc.result) && <span className="toolcall-result">{resultBlurb(tc.tool, tc.result)}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
