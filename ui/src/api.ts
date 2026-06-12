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

export interface PartyMon {
  slot: number;
  species: string;
  nickname: string;
  level: number;
  hp: number;
  max_hp: number;
  status: string | null;
}

export interface BattleInfo {
  kind: "wild" | "trainer";
  enemy_species: string | null;
  enemy_level: number | null;
  enemy_hp: number | null;
}

export interface GameStatus {
  player_name: string | null;
  money: number | null;
  map_id: number | null;
  map_name: string | null;
  badges: string[];
  pokedex_owned: number | null;
  pokedex_seen: number | null;
  play_time: string | null;
  party: PartyMon[];
  battle: BattleInfo | null;
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
  status: GameStatus | null;
}

export interface HealthState {
  ok: boolean;
  active_run: string | null;
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

export function getHealth(): Promise<HealthState> {
  return request<HealthState>("/api/health");
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
  model: string | null;
  metadata: Record<string, unknown> | null;
  status: "idle" | "starting" | "running" | "stopping" | "error" | "disconnected";
  error: string | null;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
}

export function listHarnesses(): Promise<HarnessAgent[]> {
  return request<HarnessAgent[]>("/api/harness/list");
}

export function playHarness(id: string, rom?: string | null): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/harness/${id}/play`, {
    method: "POST",
    body: JSON.stringify({ rom: rom ?? null }),
  });
}

export interface RomInfo {
  filename: string;
  title: string | null;
  sha1: string;
  kind: "gb" | "gba";
  default: boolean;
}

export function listRoms(): Promise<RomInfo[]> {
  return request<RomInfo[]>("/api/roms");
}

export interface AgentDefinition {
  name: string;
  module: string;
  description: string | null;
  running: boolean;
  pid: number | null;
  log: string;
  harness: HarnessAgent | null;
}

export function listAgents(): Promise<AgentDefinition[]> {
  return request<AgentDefinition[]>("/api/agents");
}

export function launchAgent(name: string, model?: string | null): Promise<{ name: string; pid: number }> {
  return request(`/api/agents/${encodeURIComponent(name)}/launch`, {
    method: "POST",
    body: JSON.stringify({ model: model ?? null }),
  });
}

export function terminateAgent(name: string): Promise<{ terminated: boolean }> {
  return request(`/api/agents/${encodeURIComponent(name)}/terminate`, { method: "POST" });
}

export function stopHarness(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/harness/${id}/stop`, { method: "POST" });
}

export function resetHarness(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/harness/${id}/reset`, { method: "POST" });
}

export function resumeHarness(
  id: string,
  body: { source_run_id: string; checkpoint_name?: string },
): Promise<{ ok: boolean; run_id: string; parent_run_id: string; parent_checkpoint: string; frame: number }> {
  return request(`/api/harness/${id}/resume_run`, {
    method: "POST",
    body: JSON.stringify({
      source_run_id: body.source_run_id,
      checkpoint_name: body.checkpoint_name ?? "_auto_resume",
    }),
  });
}

export interface SavedState {
  name: string;
  size: number;
  modified_at: string;
  frame?: number;
}

export interface RunSummary {
  run_id: string;
  modified_at: string;
  has_env: boolean;
  has_harness: boolean;
  has_checkpoints?: boolean;
  has_auto_resume?: boolean;
  active: boolean;
  bytes: number;
  // meta.json fields (present when available)
  status?: string;
  started_at?: string;
  ended_at?: string | null;
  turns?: number;
  last_turn_summary?: string | null;
  agent?: {
    harness_id?: string;
    name?: string;
    model?: string | null;
    metadata?: Record<string, unknown>;
  } | null;
  rom?: {
    filename?: string;
    sha1?: string | null;
    title?: string | null;
  } | null;
  start_state?: string | null;
  parent_run_id?: string | null;
  parent_checkpoint?: string | null;
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>("/api/runs");
}

export function listRunStates(runId: string): Promise<SavedState[]> {
  return request<SavedState[]>(`/api/runs/${encodeURIComponent(runId)}/states`);
}

export function listRunFrames(runId: string): Promise<number[]> {
  return request<number[]>(`/api/runs/${encodeURIComponent(runId)}/frames`);
}

export function listSharedStates(): Promise<SavedState[]> {
  return request<SavedState[]>("/api/states/shared");
}

export function deleteRunState(runId: string, name: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(
    `/api/runs/${encodeURIComponent(runId)}/states/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
}

export function traceUrl(
  runId: string,
  source: TraceSource,
  params: { sinceTimestamp?: string; limit?: number } = {},
): string {
  const url = new URL(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/${source}-trace`);
  if (params.sinceTimestamp) url.searchParams.set("since_timestamp", params.sinceTimestamp);
  if (params.limit) url.searchParams.set("limit", String(params.limit));
  return url.toString();
}

export function screenshotUrl(version: number): string {
  return `${API_BASE}/api/screenshot.png?v=${version}`;
}

export function frameThumbnailUrl(runId: string, frame: number): string {
  return `${API_BASE}/api/runs/${encodeURIComponent(runId)}/frames/${frame}.png`;
}

export function wsUrl(): string {
  const base = new URL(API_BASE);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = "/ws/events";
  return base.toString();
}
