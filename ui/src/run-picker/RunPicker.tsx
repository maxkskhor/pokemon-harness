import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { RunSummary } from "../api";

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function formatTime(iso: string | undefined | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function StatusBadge({ status, active }: { status?: string; active: boolean }) {
  const s = active ? "running" : (status ?? "stopped");
  return <span className={`run-status-badge run-status-${s}`}>{s}</span>;
}

export function RunPicker({
  activeRunId,
  viewedRunId,
  runHistory,
  onSelectRun,
}: {
  activeRunId: string | null;
  viewedRunId: string | null;
  runHistory: RunSummary[];
  onSelectRun: (runId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  const selectedLabel =
    viewedRunId
      ? viewedRunId
      : activeRunId
        ? `Active – ${activeRunId}`
        : "No run";

  return (
    <div className="run-picker">
      <button
        className="run-picker-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Select run to view"
      >
        <span>View run: <strong>{selectedLabel}</strong></span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {open && (
        <div className="run-picker-drawer">
          <table className="run-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Agent</th>
                <th>Model</th>
                <th>Turns</th>
                <th>Last turn</th>
                <th>Started</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {activeRunId && (
                <tr
                  className={viewedRunId === null ? "run-row selected" : "run-row"}
                  onClick={() => { onSelectRun(null); setOpen(false); }}
                >
                  <td className="run-id-cell" title={activeRunId}>{activeRunId}</td>
                  <td><StatusBadge status="running" active /></td>
                  <td>{runHistory.find((r) => r.run_id === activeRunId)?.agent?.name ?? "–"}</td>
                  <td>{runHistory.find((r) => r.run_id === activeRunId)?.agent?.model ?? "–"}</td>
                  <td>{runHistory.find((r) => r.run_id === activeRunId)?.turns ?? "–"}</td>
                  <td className="run-summary-cell">{runHistory.find((r) => r.run_id === activeRunId)?.last_turn_summary ?? "–"}</td>
                  <td>{formatTime(runHistory.find((r) => r.run_id === activeRunId)?.started_at)}</td>
                  <td>{formatBytes(runHistory.find((r) => r.run_id === activeRunId)?.bytes ?? 0)}</td>
                </tr>
              )}
              {runHistory
                .filter((entry) => !entry.active)
                .map((entry) => (
                  <tr
                    key={entry.run_id}
                    className={viewedRunId === entry.run_id ? "run-row selected" : "run-row"}
                    onClick={() => { onSelectRun(entry.run_id); setOpen(false); }}
                  >
                    <td className="run-id-cell" title={entry.run_id}>{entry.run_id}</td>
                    <td><StatusBadge status={entry.status} active={false} /></td>
                    <td>{entry.agent?.name ?? "–"}</td>
                    <td>{entry.agent?.model ?? "–"}</td>
                    <td>{entry.turns ?? "–"}</td>
                    <td className="run-summary-cell">{entry.last_turn_summary ?? "–"}</td>
                    <td>{formatTime(entry.started_at ?? entry.modified_at)}</td>
                    <td>{formatBytes(entry.bytes)}</td>
                  </tr>
                ))}
              {runHistory.length === 0 && !activeRunId && (
                <tr>
                  <td colSpan={8} style={{ textAlign: "center", padding: "8px", opacity: 0.5 }}>No runs yet</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
