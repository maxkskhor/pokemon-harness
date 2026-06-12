import { Flag } from "lucide-react";

import type { TraceEvent } from "../api";

// Mirrors harness/meta.py MILESTONES. Keys must match; labels are display-only.
const JOURNEY: { key: string; label: string }[] = [
  { key: "leave-bedroom", label: "Leave bedroom" },
  { key: "exit-house", label: "Step outside" },
  { key: "get-starter", label: "Get starter" },
  { key: "route-1", label: "Route 1" },
  { key: "viridian-city", label: "Viridian City" },
  { key: "deliver-parcel", label: "Deliver parcel" },
  { key: "route-2", label: "Route 2" },
  { key: "viridian-forest", label: "Viridian Forest" },
  { key: "pewter-city", label: "Pewter City" },
  { key: "ready-for-gym", label: "Train to Lv10" },
  { key: "pewter-gym", label: "Enter gym" },
  { key: "boulder-badge", label: "BOULDER BADGE" },
];

interface MilestoneHit {
  key: string;
  turn?: number;
  run_cost_usd?: number;
}

function milestoneHits(events: TraceEvent[]): Map<string, MilestoneHit> {
  const hits = new Map<string, MilestoneHit>();
  for (const event of events) {
    if (event.type !== "milestone") continue;
    const payload = event.payload as Record<string, unknown>;
    const key = payload.key;
    if (typeof key !== "string") continue;
    hits.set(key, {
      key,
      turn: typeof payload.turn === "number" ? payload.turn : undefined,
      run_cost_usd: typeof payload.run_cost_usd === "number" ? payload.run_cost_usd : undefined,
    });
  }
  return hits;
}

/**
 * Compact journey tracker: one dot per milestone, fed by `milestone` trace
 * events from the meta-harness. Shows nothing for runs without milestones
 * (e.g. the simpler example agents).
 */
export function JourneyPanel({ events }: { events: TraceEvent[] }) {
  const hits = milestoneHits(events);
  if (hits.size === 0) return null;

  const currentIndex = JOURNEY.findIndex((m) => !hits.has(m.key));
  const reachedCount = JOURNEY.filter((m) => hits.has(m.key)).length;
  const current = currentIndex === -1 ? null : JOURNEY[currentIndex];
  const lastHit = [...hits.values()].at(-1);

  return (
    <section className="journey" aria-label="Journey to the Boulder Badge">
      <div className="journey-track">
        {JOURNEY.map((milestone, index) => {
          const hit = hits.get(milestone.key);
          const state = hit ? "done" : index === currentIndex ? "current" : "todo";
          const title = hit
            ? `${milestone.label} — turn ${hit.turn ?? "?"}, $${(hit.run_cost_usd ?? 0).toFixed(3)}`
            : milestone.label;
          return (
            <span key={milestone.key} className={`journey-dot ${state}`} title={title}>
              {index === JOURNEY.length - 1 ? <Flag size={9} /> : null}
            </span>
          );
        })}
      </div>
      <div className="journey-caption">
        {current ? (
          <>
            <strong>{reachedCount}/{JOURNEY.length}</strong>
            <span className="journey-next">next: {current.label}</span>
          </>
        ) : (
          <strong className="journey-complete">BOULDER BADGE WON!</strong>
        )}
        {lastHit?.run_cost_usd != null && (
          <span className="journey-cost">${lastHit.run_cost_usd.toFixed(3)} spent</span>
        )}
      </div>
    </section>
  );
}
