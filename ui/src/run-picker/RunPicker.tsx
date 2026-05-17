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
  return (
    <div className="run-picker" aria-label="View run">
      <span>View run</span>
      <select value={viewedRunId ?? ""} onChange={(event) => onSelectRun(event.currentTarget.value || null)}>
        <option value="">{activeRunId ? `Active - ${activeRunId}` : "Active (no run)"}</option>
        {runHistory
          .filter((entry) => !entry.active)
          .map((entry) => (
            <option key={entry.run_id} value={entry.run_id}>
              {entry.run_id} - {formatBytes(entry.bytes)} - {new Date(entry.modified_at).toLocaleString()}
            </option>
          ))}
      </select>
    </div>
  );
}
