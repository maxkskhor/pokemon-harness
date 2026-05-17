import { RotateCcw } from "lucide-react";

import type { SavedState } from "../api";

function nearestAvailableFrame(frames: number[], target: number): number | null {
  if (!frames.length) return null;
  return frames.reduce((best, frame) => (Math.abs(frame - target) < Math.abs(best - target) ? frame : best), frames[0]);
}

function nearestPriorCheckpoint(checkpoints: SavedState[], frame: number | null): SavedState | null {
  if (frame == null) return null;
  return (
    checkpoints
      .filter((checkpoint) => checkpoint.frame != null && checkpoint.frame <= frame)
      .sort((a, b) => (b.frame ?? 0) - (a.frame ?? 0))[0] ?? null
  );
}

export function FrameScrubber({
  runId,
  frames,
  selectedFrame,
  previewFrame,
  checkpoints,
  busy,
  onSelectFrame,
  onPreviewFrame,
  onRewind,
}: {
  runId: string | null;
  frames: number[];
  selectedFrame: number | null;
  previewFrame: number | null;
  checkpoints: SavedState[];
  busy: boolean;
  onSelectFrame: (frame: number | null) => void;
  onPreviewFrame: (frame: number | null) => void;
  onRewind: (name: string) => void;
}) {
  const min = frames[0] ?? 0;
  const max = frames.at(-1) ?? 0;
  const value = selectedFrame ?? max;
  const checkpoint = nearestPriorCheckpoint(checkpoints, selectedFrame);

  function chooseFrame(raw: string) {
    const frame = nearestAvailableFrame(frames, Number(raw));
    onSelectFrame(frame);
    onPreviewFrame(frame);
  }

  return (
    <section className="frame-scrubber" aria-label="Frame scrubber">
      <div className="frame-scrubber-main">
        <span>{runId ? "Frames" : "No run"}</span>
        <input
          type="range"
          min={min}
          max={max}
          step={1}
          value={value}
          disabled={!runId || frames.length === 0}
          onChange={(event) => chooseFrame(event.currentTarget.value)}
          onPointerUp={() => onPreviewFrame(null)}
          onPointerCancel={() => onPreviewFrame(null)}
          onBlur={() => onPreviewFrame(null)}
          aria-label="Preview frame"
        />
        <output>{previewFrame != null ? `preview ${previewFrame}` : selectedFrame != null ? `frame ${selectedFrame}` : "-"}</output>
      </div>
      <button
        onClick={() => checkpoint && onRewind(checkpoint.name)}
        disabled={busy || !runId || !checkpoint}
        title={checkpoint ? `Load checkpoint ${checkpoint.name} captured at frame ${checkpoint.frame}` : "Save a checkpoint before rewinding"}
      >
        <RotateCcw size={14} /> {checkpoint ? `Rewind to ${checkpoint.name}` : "No checkpoint"}
      </button>
    </section>
  );
}
