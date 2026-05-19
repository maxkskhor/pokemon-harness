import { ChevronDown, ChevronRight, MessageSquareText } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { frameThumbnailUrl, type SavedState, type TraceEvent } from "../api";
import { TurnCard } from "./TurnCard";
import {
  CATEGORY_ICON,
  eventCategory,
  eventLabel,
  formatDelta,
  formatPayload,
  payloadText,
  summarizeEvent,
  type FilterType,
} from "./helpers";

export function TraceList({
  events,
  filters,
  isRunning,
  autoScroll,
  runStates = [],
  onLoadCheckpoint,
  onSaveCheckpoint,
}: {
  events: TraceEvent[];
  filters: Record<FilterType, boolean>;
  isRunning: boolean;
  autoScroll: boolean;
  runStates?: SavedState[];
  onLoadCheckpoint?: (name: string) => void;
  onSaveCheckpoint?: () => void;
}) {
  const listRef = useRef<HTMLOListElement | null>(null);
  useEffect(() => {
    if (autoScroll) {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
    }
  }, [events.length, isRunning, autoScroll]);

  if (!events.length) {
    return (
      <div className="trace-empty">
        {isRunning ? <span className="run-pulse" /> : null}
        {isRunning ? "Waiting for the next agent event..." : "No events yet"}
      </div>
    );
  }

  // Split events into turns (have turn_id) and session events (no turn_id)
  const sessionEvents = events.filter((e) => !e.turn_id && filters[eventCategory(e)]);
  const turnEventMap = new Map<string, TraceEvent[]>();
  for (const event of events) {
    if (!event.turn_id) continue;
    const bucket = turnEventMap.get(event.turn_id) ?? [];
    bucket.push(event);
    turnEventMap.set(event.turn_id, bucket);
  }

  // Order turns by first appearance
  const turnIds: string[] = [];
  for (const event of events) {
    if (event.turn_id && !turnIds.includes(event.turn_id)) {
      turnIds.push(event.turn_id);
    }
  }

  const hasTurns = turnIds.length > 0;
  const hasSession = sessionEvents.length > 0;

  if (!hasTurns && !hasSession) {
    return <div className="trace-empty">No events match the selected filters</div>;
  }

  const deltas = new Map<TraceEvent, string>();
  sessionEvents.forEach((event, index) => {
    deltas.set(event, formatDelta(event, sessionEvents[index - 1] ?? null));
  });

  return (
    <ol className="trace-list" ref={listRef}>
      {turnIds.map((turn_id) => (
        <TurnCard
          key={turn_id}
          turn_id={turn_id}
          events={turnEventMap.get(turn_id) ?? []}
          runStates={runStates}
          onLoadCheckpoint={onLoadCheckpoint}
          onSaveCheckpoint={onSaveCheckpoint}
        />
      ))}
      {hasSession && (
        <SessionGroup events={sessionEvents} deltas={deltas} />
      )}
      {isRunning ? (
        <li className="trace-item trace-waiting">
          <span className="run-pulse" />
          <span>Agent is running, waiting for the next event...</span>
        </li>
      ) : null}
    </ol>
  );
}

function SessionGroup({
  events,
  deltas,
}: {
  events: TraceEvent[];
  deltas: Map<TraceEvent, string>;
}) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <li className="trace-group">
      <button className="trace-group-header" onClick={() => setCollapsed((v) => !v)}>
        {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        <span>Session</span>
        <em>{events.length}</em>
      </button>
      {!collapsed && (
        <ol>
          {events.map((event, index) => (
            <TraceItem
              key={`${event.timestamp}-${event.type}-${index}`}
              event={event}
              delta={deltas.get(event) ?? "+0.0 s"}
            />
          ))}
        </ol>
      )}
    </li>
  );
}

function messageText(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const content = (message as Record<string, unknown>).content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const record = item as Record<string, unknown>;
      if (record.type === "text" && typeof record.text === "string") return record.text;
      if (record.type === "image_url") return "[image]";
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function LlmCallDetails({ payload }: { payload: Record<string, unknown> }) {
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const usage = payload.usage && typeof payload.usage === "object" ? (payload.usage as Record<string, unknown>) : {};
  return (
    <div className="llm-details">
      <div className="llm-usage">
        <span>{String(payload.model ?? "model unknown")}</span>
        <span>{String(usage.prompt_tokens ?? "-")} prompt</span>
        <span>{String(usage.completion_tokens ?? "-")} completion</span>
        <span>{String(usage.latency_ms ?? "-")} ms</span>
      </div>
      <div className="llm-messages">
        {messages.map((message, index) => {
          const record = message && typeof message === "object" ? (message as Record<string, unknown>) : {};
          return (
            <article key={`${String(record.role ?? "message")}-${index}`}>
              <strong>{String(record.role ?? "message")}</strong>
              <p>{messageText(message)}</p>
            </article>
          );
        })}
        {typeof payload.response === "string" && payload.response ? (
          <article>
            <strong>assistant response</strong>
            <p>{payload.response}</p>
          </article>
        ) : null}
      </div>
    </div>
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
      <button className="trace-head" onClick={() => setExpanded((value) => !value)}>
        <span className="trace-kind">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Icon size={14} />
          <span className="trace-source-badge" data-source={event.source}>
            {event.source === "harness" ? "agent" : "env"}
          </span>
          {eventLabel(event)}
        </span>
        <time>
          {new Date(event.timestamp).toLocaleTimeString()} <span>{delta}</span>
        </time>
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
          <blockquote className={reasoningExpanded ? "reasoning expanded" : "reasoning"}>{reasoning}</blockquote>
          <button className="reasoning-toggle" onClick={() => setReasoningExpanded((value) => !value)}>
            {reasoningExpanded ? "Collapse reasoning" : "Expand reasoning"}
          </button>
        </div>
      ) : null}
      {expanded && event.type === "llm_call" ? <LlmCallDetails payload={event.payload} /> : null}
      {expanded ? <pre>{formatPayload(event.payload)}</pre> : null}
    </li>
  );
}
