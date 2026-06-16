import { Pause, Play, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { SavedState } from "../api";

const REPLAY_INTERVAL_MS = 220;

function nearestAvailableFrame(frames: number[], target: number): number | null {
  if (!frames.length) return null;
  return frames.reduce(
    (best, frame) => (Math.abs(frame - target) < Math.abs(best - target) ? frame : best),
    frames[0],
  );
}

function nearestPriorCheckpoint(checkpoints: SavedState[], frame: number | null): SavedState | null {
  if (frame == null) return null;
  return (
    checkpoints
      .filter((checkpoint) => checkpoint.frame != null && checkpoint.frame <= frame)
      .sort((a, b) => (b.frame ?? 0) - (a.frame ?? 0))[0] ?? null
  );
}

/**
 * Timeline over a run's captured frames: scrub, step, and replay them in order
 * on the main screen, plus "rewind emulator to nearest checkpoint".
 */
export function ReplayBar({
  runId,
  frames,
  previewFrame,
  checkpoints,
  busy,
  canRewind,
  onPreviewFrame,
  onRewind,
}: {
  runId: string | null;
  frames: number[];
  previewFrame: number | null;
  checkpoints: SavedState[];
  busy: boolean;
  canRewind: boolean;
  onPreviewFrame: (frame: number | null) => void;
  onRewind: (name: string) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    frameRef.current = previewFrame;
  }, [previewFrame]);

  // Stop playback when the run changes or frames reset.
  useEffect(() => {
    const timer = window.setTimeout(() => setPlaying(false), 0);
    playingRef.current = false;
    return () => window.clearTimeout(timer);
  }, [runId]);

  useEffect(() => {
    if (!playing) return;
    playingRef.current = true;
    const timer = setInterval(() => {
      if (!playingRef.current) return;
      const current = frameRef.current;
      const index = current == null ? -1 : frames.indexOf(current);
      const next = frames[index + 1];
      if (next == null) {
        setPlaying(false);
        playingRef.current = false;
        return;
      }
      onPreviewFrame(next);
    }, REPLAY_INTERVAL_MS);
    return () => {
      playingRef.current = false;
      clearInterval(timer);
    };
  }, [playing, frames, onPreviewFrame]);

  const min = frames[0] ?? 0;
  const max = frames.at(-1) ?? 0;
  const value = previewFrame ?? max;
  const checkpoint = nearestPriorCheckpoint(checkpoints, previewFrame ?? max);
  const hasFrames = frames.length > 1;
  const position = previewFrame == null ? frames.length : frames.indexOf(previewFrame) + 1;

  function step(direction: 1 | -1) {
    const current = frameRef.current ?? max;
    const index = frames.indexOf(current);
    const next = frames[(index === -1 ? frames.length - 1 : index) + direction];
    if (next != null) onPreviewFrame(next);
  }

  function togglePlay() {
    if (playing) {
      setPlaying(false);
      return;
    }
    // Restart from the beginning when the cursor sits at the live end.
    if (frameRef.current == null || frameRef.current === max) {
      onPreviewFrame(frames[0] ?? null);
    }
    setPlaying(true);
  }

  return (
    <section className="replay-bar" aria-label="Replay timeline">
      <div className="replay-transport">
        <button onClick={() => step(-1)} disabled={!hasFrames} title="Previous captured frame">
          <SkipBack size={13} />
        </button>
        <button onClick={togglePlay} disabled={!hasFrames} title={playing ? "Pause replay" : "Replay captured frames"}>
          {playing ? <Pause size={13} /> : <Play size={13} />}
        </button>
        <button onClick={() => step(1)} disabled={!hasFrames || previewFrame == null} title="Next captured frame">
          <SkipForward size={13} />
        </button>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        disabled={!runId || !hasFrames}
        onChange={(event) => {
          setPlaying(false);
          onPreviewFrame(nearestAvailableFrame(frames, Number(event.currentTarget.value)));
        }}
        aria-label="Replay position"
      />
      <output>
        {previewFrame != null
          ? `${position}/${frames.length} · frame ${previewFrame}`
          : frames.length
            ? `latest · ${frames.length} frames`
            : "no frames"}
      </output>
      {previewFrame != null && (
        <button onClick={() => { setPlaying(false); onPreviewFrame(null); }} title="Back to the live screen">
          Live
        </button>
      )}
      {canRewind && (
        <button
          onClick={() => checkpoint && onRewind(checkpoint.name)}
          disabled={busy || !runId || !checkpoint}
          title={
            checkpoint
              ? `Rewind the emulator to checkpoint "${checkpoint.name}" (frame ${checkpoint.frame})`
              : "Save a checkpoint to enable rewinding"
          }
        >
          <RotateCcw size={13} /> Rewind
        </button>
      )}
    </section>
  );
}
