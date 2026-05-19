import { Bookmark, ChevronDown, ChevronRight, Clock, Gamepad2, MessageSquareText, RotateCcw } from "lucide-react";
import { useState } from "react";
import { frameThumbnailUrl, type SavedState, type TraceEvent } from "../api";
import { CATEGORY_ICON, eventCategory, eventLabel, formatPayload, payloadText, summarizeEvent, type FilterType } from "./helpers";

interface TurnSummary {
  turn_id: string;
  turn_index: number | null;
  goal: string | null;
  status: "ok" | "error" | "in-progress";
  elapsed_ms: number | null;
  frame: number | null;
  run_id: string;
  events: TraceEvent[];
  decision: string | null;
  action_summary: string | null;
  position_delta: string | null;
  llm_model: string | null;
  llm_tokens: number | null;
  llm_latency_ms: number | null;
  llm_cost_usd: number | null;
  reasoning: string | null;
}

function buildTurnSummary(turn_id: string, events: TraceEvent[]): TurnSummary {
  const started = events.find((e) => e.type === "turn_started");
  const finished = events.find((e) => e.type === "turn_finished");
  const run_id = events[0]?.run_id ?? "";

  const turn_index =
    (started?.payload.turn_index as number | null) ??
    (finished?.payload.turn_index as number | null) ??
    null;

  const goal = (started?.payload.goal as string | null) ?? null;

  let status: TurnSummary["status"] = "in-progress";
  if (finished) {
    status = (finished.payload.status as "ok" | "error") ?? "ok";
  }

  const elapsed_ms = (finished?.payload.elapsed_ms as number | null) ?? null;
  const frame =
    (finished?.payload.frame as number | null) ??
    (started?.payload.frame as number | null) ??
    null;

  const decisionEvent = events.find((e) => e.type === "decision");
  const decision =
    decisionEvent
      ? payloadText(decisionEvent.payload, ["action", "button", "reasoning", "summary"]) ??
        summarizeEvent(decisionEvent)
      : null;

  const actionEvent = events.find(
    (e) => e.type === "button_press" || e.type === "button_sequence" || e.type === "action",
  );
  const action_summary = actionEvent ? summarizeEvent(actionEvent) : null;

  let position_delta: string | null = null;
  if (actionEvent) {
    const before = actionEvent.payload.before as Record<string, unknown> | undefined;
    const after = actionEvent.payload.after as Record<string, unknown> | undefined;
    if (before && after) {
      const bPos = `map ${before.map_id ?? "-"} (${before.x ?? "-"},${before.y ?? "-"})`;
      const aPos = `(${after.x ?? "-"},${after.y ?? "-"})`;
      if (bPos !== aPos) position_delta = `${bPos} → ${aPos}`;
    }
  }

  const llmEvent = events.find((e) => e.type === "llm_call");
  const usage =
    llmEvent?.payload.usage && typeof llmEvent.payload.usage === "object"
      ? (llmEvent.payload.usage as Record<string, unknown>)
      : null;
  const llm_model = llmEvent ? ((llmEvent.payload.model as string) ?? null) : null;
  const llm_tokens = usage ? ((usage.total_tokens as number) ?? null) : null;
  const llm_latency_ms = usage ? ((usage.latency_ms as number) ?? null) : null;
  const llm_cost_usd = usage ? ((usage.cost_usd as number) ?? null) : null;

  const reasoning =
    decisionEvent
      ? payloadText(decisionEvent.payload, ["reasoning", "thought", "thinking", "raw_thought"])
      : llmEvent
        ? payloadText(llmEvent.payload, ["reasoning", "thought", "thinking", "raw_thought"])
        : null;

  return {
    turn_id,
    turn_index,
    goal,
    status,
    elapsed_ms,
    frame,
    run_id,
    events,
    decision,
    action_summary,
    position_delta,
    llm_model,
    llm_tokens,
    llm_latency_ms,
    llm_cost_usd,
    reasoning,
  };
}

function RawEventItem({ event }: { event: TraceEvent }) {
  const [expanded, setExpanded] = useState(false);
  const category = eventCategory(event);
  const Icon = CATEGORY_ICON[category] ?? MessageSquareText;
  return (
    <li className="trace-item" data-tone={category} data-source={event.source}>
      <button className="trace-head" onClick={() => setExpanded((v) => !v)}>
        <span className="trace-kind">
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <Icon size={13} />
          <span className="trace-source-badge" data-source={event.source}>
            {event.source === "harness" ? "agent" : "env"}
          </span>
          {eventLabel(event)}
        </span>
        <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
      </button>
      <p className="trace-summary">{summarizeEvent(event)}</p>
      {expanded ? <pre>{formatPayload(event.payload)}</pre> : null}
    </li>
  );
}

export function TurnCard({
  turn_id,
  events,
  filters,
  showImages,
  runStates = [],
  onLoadCheckpoint,
  onSaveCheckpoint,
}: {
  turn_id: string;
  events: TraceEvent[];
  filters: Record<FilterType, boolean>;
  showImages: boolean;
  runStates?: SavedState[];
  onLoadCheckpoint?: (name: string) => void;
  onSaveCheckpoint?: () => void;
}) {
  const [rawExpanded, setRawExpanded] = useState(false);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const [thumbnailEnlarged, setThumbnailEnlarged] = useState(false);
  const [reasoningExpanded, setReasoningExpanded] = useState(false);
  const s = buildTurnSummary(turn_id, events);

  // Find checkpoint nearest to this turn's starting frame
  const nearestCheckpoint =
    s.frame != null && runStates.length > 0
      ? runStates
          .filter((ck) => ck.frame != null && (ck.frame as number) <= (s.frame as number))
          .sort((a, b) => (b.frame as number) - (a.frame as number))[0] ?? null
      : null;

  const statusClass =
    s.status === "ok" ? "turn-status-ok" : s.status === "error" ? "turn-status-error" : "turn-status-running";
  const showThumbnail = showImages && s.frame != null && !thumbnailFailed;

  const rawEvents = s.events.filter(
    (e) => e.type !== "turn_started" && e.type !== "turn_finished" && filters[eventCategory(e)],
  );
  const rawCount = rawEvents.length;

  return (
    <li className="turn-card" data-status={s.status}>
      <div className="turn-card-header">
        <span className="turn-card-id">
          {s.turn_index != null ? `turn-${String(s.turn_index).padStart(3, "0")}` : turn_id}
        </span>
        <span className={`turn-card-status ${statusClass}`}>
          {s.status === "in-progress" ? (
            <><span className="run-pulse" /> running</>
          ) : (
            s.status
          )}
        </span>
        {s.elapsed_ms != null && (
          <span className="turn-card-elapsed">
            <Clock size={12} /> {(s.elapsed_ms / 1000).toFixed(1)}s
          </span>
        )}
        {s.goal && <span className="turn-card-goal">{s.goal}</span>}
      </div>

      <div className="turn-card-body">
        {showThumbnail && (
          <button
            type="button"
            className={thumbnailEnlarged ? "trace-thumbnail enlarged" : "trace-thumbnail turn-thumbnail"}
            onClick={() => setThumbnailEnlarged((v) => !v)}
            title={`Frame ${s.frame}`}
          >
            <img
              src={frameThumbnailUrl(s.run_id, s.frame as number)}
              alt={`Game screen at frame ${s.frame}`}
              loading="lazy"
              onError={() => setThumbnailFailed(true)}
            />
            <span className="trace-thumbnail-frame">frame {s.frame}</span>
          </button>
        )}

        <div className="turn-card-details">
          {s.decision && (
            <p className="turn-card-row">
              <strong>Decision:</strong> {s.decision}
            </p>
          )}
          {s.action_summary && (
            <p className="turn-card-row">
              <Gamepad2 size={12} /> {s.action_summary}
            </p>
          )}
          {s.position_delta && (
            <p className="turn-card-row turn-card-position">{s.position_delta}</p>
          )}
          {(s.llm_model || s.llm_tokens != null || s.llm_latency_ms != null || s.llm_cost_usd != null) && (
            <p className="turn-card-row turn-card-llm">
              <MessageSquareText size={12} />
              {[
                s.llm_model,
                s.llm_tokens != null ? `${s.llm_tokens} tokens` : null,
                s.llm_latency_ms != null ? `${s.llm_latency_ms}ms` : null,
                s.llm_cost_usd != null ? `$${s.llm_cost_usd.toFixed(4)}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {s.reasoning && (
            <div className="reasoning-wrap">
              <blockquote className={reasoningExpanded ? "reasoning expanded" : "reasoning"}>
                {s.reasoning}
              </blockquote>
              <button className="reasoning-toggle" onClick={() => setReasoningExpanded((v) => !v)}>
                {reasoningExpanded ? "Collapse reasoning" : "Expand reasoning"}
              </button>
            </div>
          )}
        </div>
      </div>

      {rawCount > 0 && (
        <div className="turn-card-events">
          <button className="turn-card-events-toggle" onClick={() => setRawExpanded((v) => !v)}>
            {rawExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {rawCount} event{rawCount === 1 ? "" : "s"}
          </button>
          {rawExpanded && (
            <ol className="trace-list turn-raw-events">
              {rawEvents.map((event, i) => (
                <RawEventItem key={`${event.timestamp}-${event.type}-${i}`} event={event} />
              ))}
            </ol>
          )}
        </div>
      )}

      {(nearestCheckpoint || onSaveCheckpoint) && (
        <div className="turn-card-actions">
          {nearestCheckpoint && onLoadCheckpoint && (
            <button
              className="turn-card-action-btn"
              onClick={() => onLoadCheckpoint(nearestCheckpoint.name)}
              title={`Load checkpoint "${nearestCheckpoint.name}" (frame ${nearestCheckpoint.frame})`}
            >
              <RotateCcw size={12} /> Load checkpoint near this turn
            </button>
          )}
          {onSaveCheckpoint && (
            <button
              className="turn-card-action-btn"
              onClick={onSaveCheckpoint}
              title="Save a checkpoint at the current live frame"
            >
              <Bookmark size={12} /> Save checkpoint here
            </button>
          )}
        </div>
      )}
    </li>
  );
}
