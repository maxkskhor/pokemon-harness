import type { TraceEvent } from "../api";

/** One turn's worth of "what the agent saw, thought, and did" — for the spectator stream. */
export interface Thought {
  turnId: string;
  turnIndex: number | null;
  goal: string | null;
  observation: string | null;
  reasoning: string | null;
  action: string | null;
  milestone: string | null;
  rollback: string | null;
  steer: string | null;
  frame: number | null;
  costUsd: number | null;
  status: "ok" | "error" | "running";
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function reasoningFrom(llm: TraceEvent | undefined): string | null {
  if (!llm) return null;
  const response = llm.payload.response;
  if (response && typeof response === "object") {
    const r = response as Record<string, unknown>;
    return str(r.reasoning) ?? str(r.content);
  }
  return str(llm.payload.reasoning) ?? str(llm.payload.content);
}

/** First non-LOCATION, non-GOAL line of the observation — a human-readable scene note. */
function sceneFrom(observation: string | null): string | null {
  if (!observation) return null;
  const goalLine = observation
    .split("\n")
    .find((l) => l.startsWith("GOAL:"));
  return goalLine ? goalLine.replace(/^GOAL:\s*/, "") : null;
}

export function buildThoughts(events: TraceEvent[]): Thought[] {
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
    const turnEvents = byTurn.get(turnId)!;
    const started = turnEvents.find((e) => e.type === "turn_started");
    const finished = turnEvents.find((e) => e.type === "turn_finished");
    const llm = turnEvents.find((e) => e.type === "llm_call");
    const actions = turnEvents.find((e) => e.type === "actions");
    const obs = turnEvents.find((e) => e.type === "observation");
    const milestone = turnEvents.find((e) => e.type === "milestone");
    const rollback = turnEvents.find((e) => e.type === "rollback");
    const steer = turnEvents.find((e) => e.type === "steering");

    const observation = obs ? str(obs.payload.text) : null;
    const usage = llm?.payload.usage as Record<string, unknown> | undefined;

    let status: Thought["status"] = "running";
    if (finished) status = (finished.payload.status as "ok" | "error") ?? "ok";

    return {
      turnId,
      turnIndex:
        (started?.payload.turn_index as number | null) ??
        (finished?.payload.turn_index as number | null) ??
        null,
      goal: str(started?.payload.goal) ?? sceneFrom(observation),
      observation,
      reasoning: reasoningFrom(llm),
      action: actions ? str(actions.payload.summary) : null,
      milestone: milestone ? str(milestone.payload.label) : null,
      rollback: rollback ? str(rollback.payload.reason) : null,
      steer: steer ? str(steer.payload.message) : null,
      frame: (started?.payload.frame as number | null) ?? null,
      costUsd: typeof usage?.run_cost_usd === "number" ? (usage.run_cost_usd as number) : null,
      status,
    };
  });
}

/** Latest cumulative run cost from any llm_call / budget event. */
export function runCost(events: TraceEvent[]): number | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "budget_exceeded") {
      const c = (e.payload as Record<string, unknown>).run_cost_usd;
      if (typeof c === "number") return c;
    }
    if (e.type === "llm_call") {
      const usage = (e.payload as Record<string, unknown>).usage as Record<string, unknown> | undefined;
      if (typeof usage?.run_cost_usd === "number") return usage.run_cost_usd as number;
    }
  }
  return null;
}
