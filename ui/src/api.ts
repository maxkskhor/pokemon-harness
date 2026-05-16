export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export type TraceSource = "env" | "harness";

export interface TraceEvent {
  run_id: string;
  source: TraceSource;
  type: string;
  turn_id: string | null;
  frame: number | null;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface PokemonState {
  run_id: string;
  running: boolean;
  frame: number;
  speed_mode: string;
  timestamp: string;
  rom: {
    filename: string;
    sha1: string | null;
    title: string | null;
    symbols_loaded: boolean;
  };
  screen: {
    width: number;
    height: number;
    sha256: string;
  };
  pokemon: Record<string, number | null>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function startRun(runId: string): Promise<PokemonState> {
  return request<PokemonState>("/api/run/start", {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });
}

export function stopRun(): Promise<{ running: boolean; run_id: string }> {
  return request<{ running: boolean; run_id: string }>("/api/run/stop", { method: "POST" });
}

export function getState(): Promise<PokemonState> {
  return request<PokemonState>("/api/state");
}

export function pressButton(button: string, frames = 8): Promise<PokemonState> {
  return request<PokemonState>("/api/action/press", {
    method: "POST",
    body: JSON.stringify({ button, frames }),
  });
}

export function stepFrames(frames: number): Promise<PokemonState> {
  return request<PokemonState>("/api/step", {
    method: "POST",
    body: JSON.stringify({ frames }),
  });
}

export function setSpeed(mode: string): Promise<{ run_id: string; speed_mode: string }> {
  return request<{ run_id: string; speed_mode: string }>("/api/speed", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function saveState(name: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/api/save-state", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function loadState(name: string): Promise<PokemonState> {
  return request<PokemonState>("/api/load-state", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export interface HarnessAgent {
  id: string;
  name: string;
  status: "idle" | "running" | "stopping" | "error";
  error: string | null;
}

export function listHarnesses(): Promise<HarnessAgent[]> {
  return request<HarnessAgent[]>("/api/harness/list");
}

export function playHarness(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/harness/${id}/play`, { method: "POST" });
}

export function stopHarness(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/harness/${id}/stop`, { method: "POST" });
}

export function traceUrl(runId: string, source: TraceSource): string {
  return `${API_BASE}/api/runs/${runId}/${source}-trace`;
}

export function screenshotUrl(version: number): string {
  return `${API_BASE}/api/screenshot.png?v=${version}`;
}

export function wsUrl(): string {
  const base = new URL(API_BASE);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = "/ws/events";
  return base.toString();
}

