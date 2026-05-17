import { Download, Save, Trash2 } from "lucide-react";

import type { PokemonState, SavedState } from "../api";

function formatCheckpointTime(iso: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function Checkpoints({
  state,
  runStates,
  sharedStates,
  checkpointName,
  onCheckpointNameChange,
  onSave,
  onLoad,
  onDelete,
  busy,
}: {
  state: PokemonState | null;
  runStates: SavedState[];
  sharedStates: SavedState[];
  checkpointName: string;
  onCheckpointNameChange: (value: string) => void;
  onSave: () => void;
  onLoad: (name: string) => void;
  onDelete: (name: string) => void;
  busy: boolean;
}) {
  const placeholder = state ? `chkpt-${state.frame}` : "chkpt-name";
  return (
    <section className="checkpoints" aria-label="Checkpoints">
      <header>
        <h3>Checkpoints</h3>
        <div className="checkpoints-save">
          <input
            value={checkpointName}
            onChange={(event) => onCheckpointNameChange(event.currentTarget.value)}
            placeholder={placeholder}
            aria-label="Checkpoint name (optional)"
            disabled={!state || busy}
          />
          <button onClick={onSave} disabled={!state || busy}>
            <Save size={14} /> Save
          </button>
        </div>
      </header>

      <div className="checkpoints-list">
        {runStates.length === 0 ? (
          <p className="checkpoints-empty">
            {state ? "No checkpoints yet - click Save to capture this frame." : "Start a run to save checkpoints."}
          </p>
        ) : (
          <ul>
            {runStates.map((entry) => (
              <li key={entry.name}>
                <div className="checkpoint-meta">
                  <strong title={entry.name}>{entry.name}</strong>
                  <span>
                    {formatCheckpointTime(entry.modified_at)}
                    {entry.frame != null ? ` - frame ${entry.frame}` : ""}
                  </span>
                </div>
                <div className="checkpoint-actions">
                  <button onClick={() => onLoad(entry.name)} disabled={!state || busy} title="Load this checkpoint">
                    <Download size={13} /> Load
                  </button>
                  <button
                    onClick={() => onDelete(entry.name)}
                    disabled={!state || busy}
                    title="Delete this checkpoint"
                    className="checkpoint-delete"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {sharedStates.length > 0 && (
          <>
            <p className="checkpoints-divider">Shared</p>
            <ul>
              {sharedStates.map((entry) => (
                <li key={`shared-${entry.name}`}>
                  <div className="checkpoint-meta">
                    <strong title={entry.name}>{entry.name}</strong>
                    <span>read-only - {formatCheckpointTime(entry.modified_at)}</span>
                  </div>
                  <div className="checkpoint-actions">
                    <button onClick={() => onLoad(entry.name)} disabled={!state || busy} title="Load this shared state">
                      <Download size={13} /> Load
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
