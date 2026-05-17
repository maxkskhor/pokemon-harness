import { Activity, AlertCircle, AlertTriangle, Bot, Gamepad2, MessageSquareText, Save } from "lucide-react";
import type { ComponentType } from "react";

import type { TraceEvent } from "../api";

export const filterTypes = ["decision", "llm", "action", "state", "lifecycle", "warning", "error"] as const;
export type FilterType = (typeof filterTypes)[number];

// Env events that fire continuously (~10/sec at max speed). Skip in timeline.
export const NOISY_EVENT_TYPES = new Set(["playback_frame"]);

export function eventCategory(event: TraceEvent): FilterType {
  switch (event.type) {
    case "decision":
      return "decision";
    case "llm_call":
      return "llm";
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

export function eventLabel(event: TraceEvent): string {
  const turn = event.turn_id ? `${event.turn_id} ` : "";
  return `${turn}${event.type}`.trim();
}

export function formatPayload(payload: Record<string, unknown>): string {
  return JSON.stringify(payload, null, 2);
}

export function payloadText(payload: Record<string, unknown>, keys: string[]): string | null {
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

export function summarizeEvent(event: TraceEvent): string {
  const payload = event.payload;
  if (event.type === "action") {
    const button = payload.button ?? payload.action ?? payload.input ?? "-";
    const frames = payload.frames != null ? `, frames=${payload.frames}` : "";
    const before = formatPosition(payload.before);
    const after = formatPosition(payload.after);
    const movement = before && after ? ` - ${before} -> ${after}` : "";
    return `press_button(${button}${frames})${movement}`;
  }
  if (event.type === "button_press") {
    const button = payload.button ?? "-";
    const frames = payload.frames != null ? `, frames=${payload.frames}` : "";
    const before = formatPosition(payload.before);
    const after = formatPosition(payload.after);
    const movement = before && after ? ` - ${before} -> ${after}` : "";
    return `button_press(${button}${frames})${movement}`;
  }
  if (event.type === "button_sequence") {
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    const before = formatPosition(payload.before);
    const after = formatPosition(payload.after);
    const movement = before && after ? ` - ${before} -> ${after}` : "";
    return `button_sequence(${steps.length} step${steps.length === 1 ? "" : "s"})${movement}`;
  }
  if (event.type === "step") {
    return `step ${payload.frames ?? "?"}f`;
  }
  if (event.type === "decision") {
    const action = payload.action ?? payload.button ?? "-";
    return `Chose ${action}`;
  }
  if (event.type === "llm_call") {
    const usage = payload.usage as Record<string, unknown> | undefined;
    const total = usage && typeof usage === "object" ? usage.total_tokens : null;
    const latency = usage && typeof usage === "object" ? usage.latency_ms : null;
    const suffix = [
      total != null ? `${total} tokens` : null,
      latency != null ? `${latency} ms` : null,
    ].filter(Boolean).join(" · ");
    return `LLM call ${payload.model ?? ""}${suffix ? ` - ${suffix}` : ""}`.trim();
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
    return `saved "${payload.name ?? "?"}" @ frame ${payload.frame ?? "?"}`;
  }
  if (event.type === "state_loaded") {
    return `loaded "${payload.name ?? "?"}"`;
  }
  if (event.type === "speed_changed") {
    return `speed -> ${payload.mode ?? "?"}`;
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

export const CATEGORY_ICON: Record<FilterType, ComponentType<{ size?: number }>> = {
  decision: Bot,
  llm: MessageSquareText,
  action: Gamepad2,
  state: Save,
  lifecycle: Activity,
  warning: AlertTriangle,
  error: AlertCircle,
};

export function groupLabel(event: TraceEvent): string {
  return event.turn_id ?? "Session";
}

export function formatDelta(current: TraceEvent, previous: TraceEvent | null): string {
  if (!previous) return "+0.0 s";
  const deltaMs = new Date(current.timestamp).getTime() - new Date(previous.timestamp).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 0) return "+0.0 s";
  return `+${(deltaMs / 1000).toFixed(1)} s`;
}
