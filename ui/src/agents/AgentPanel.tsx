import { History, Play, Power, RotateCcw, Square } from "lucide-react";

import type { AgentDefinition, HarnessAgent, RomInfo } from "../api";

function statusLabel(definition: AgentDefinition): string {
  if (!definition.running) return "offline";
  return definition.harness?.status ?? "starting";
}

export function AgentPanel({
  agents,
  harnessAgents,
  selectedHarnessId,
  onSelectHarness,
  roms,
  selectedRom,
  onSelectRom,
  primaryIntent,
  resumeBlocker,
  busy,
  onPlay,
  onResume,
  onStop,
  onReset,
  onLaunch,
  onTerminate,
}: {
  agents: AgentDefinition[];
  harnessAgents: HarnessAgent[];
  selectedHarnessId: string | null;
  onSelectHarness: (id: string | null) => void;
  roms: RomInfo[];
  selectedRom: string | null;
  onSelectRom: (filename: string | null) => void;
  primaryIntent: "start" | "resume";
  resumeBlocker: string | null;
  busy: boolean;
  onPlay: () => void;
  onResume: () => void;
  onStop: () => void;
  onReset: () => void;
  onLaunch: (name: string) => void;
  onTerminate: (name: string) => void;
}) {
  const selectedHarness = harnessAgents.find((h) => h.id === selectedHarnessId) ?? null;
  const managedHarnessIds = new Set(
    agents.map((a) => a.harness?.id).filter((id): id is string => Boolean(id)),
  );
  const unmanaged = harnessAgents.filter((h) => !managedHarnessIds.has(h.id));

  return (
    <section className="agent-panel" aria-label="Agents">
      <div className="agent-rows">
        {agents.map((definition) => {
          const harness = definition.harness;
          const selectable = harness != null;
          const selected = selectable && harness.id === selectedHarnessId;
          const status = statusLabel(definition);
          return (
            <div
              key={definition.name}
              className={`agent-row${selected ? " selected" : ""}${selectable ? " selectable" : ""}`}
              onClick={() => selectable && onSelectHarness(harness.id)}
              role={selectable ? "button" : undefined}
              title={definition.description ?? definition.module}
            >
              <span className={`agent-status-dot status-${status}`} />
              <div className="agent-row-main">
                <strong>{harness?.name ?? definition.name}</strong>
                <span className="agent-row-sub">
                  {harness?.model ?? definition.description ?? definition.module}
                </span>
              </div>
              <span className="agent-row-status">{status}</span>
              {definition.running ? (
                <button
                  className="agent-row-action"
                  onClick={(event) => {
                    event.stopPropagation();
                    onTerminate(definition.name);
                  }}
                  disabled={busy || harness?.status === "running"}
                  title={
                    harness?.status === "running"
                      ? "Stop the agent's run before shutting the process down"
                      : "Shut down this agent process"
                  }
                >
                  <Power size={13} />
                </button>
              ) : (
                <button
                  className="agent-row-action"
                  onClick={(event) => {
                    event.stopPropagation();
                    onLaunch(definition.name);
                  }}
                  disabled={busy}
                  title="Launch this agent process"
                >
                  Launch
                </button>
              )}
            </div>
          );
        })}
        {unmanaged.map((harness) => (
          <div
            key={harness.id}
            className={`agent-row selectable${harness.id === selectedHarnessId ? " selected" : ""}`}
            onClick={() => onSelectHarness(harness.id)}
            role="button"
            title="Externally launched agent process"
          >
            <span className={`agent-status-dot status-${harness.status}`} />
            <div className="agent-row-main">
              <strong>{harness.name}</strong>
              <span className="agent-row-sub">{harness.model ?? "external process"}</span>
            </div>
            <span className="agent-row-status">{harness.status}</span>
          </div>
        ))}
        {agents.length === 0 && harnessAgents.length === 0 && (
          <p className="agent-rows-empty">No agents defined. Add entries to agents.yaml.</p>
        )}
      </div>

      <div className="agent-run-controls">
        <select
          value={selectedRom ?? ""}
          onChange={(event) => onSelectRom(event.target.value || null)}
          disabled={busy || primaryIntent === "resume" || roms.length === 0}
          title={
            primaryIntent === "resume"
              ? "Resume keeps the original run's game"
              : "Game to start the next run with"
          }
          aria-label="Game ROM"
        >
          {roms.map((rom) => (
            <option key={rom.filename} value={rom.filename}>
              {rom.title ?? rom.filename}
            </option>
          ))}
        </select>
        {primaryIntent === "resume" ? (
          <button
            className="primary"
            onClick={onResume}
            disabled={
              busy
              || resumeBlocker !== null
              || !selectedHarness
              || selectedHarness.status === "running"
              || selectedHarness.status === "disconnected"
            }
            title={resumeBlocker ?? "Resume this run from its latest checkpoint"}
          >
            <History size={14} /> Resume
          </button>
        ) : (
          <button
            className="primary"
            onClick={onPlay}
            disabled={
              busy
              || !selectedHarness
              || selectedHarness.status === "running"
              || selectedHarness.status === "disconnected"
            }
            title="Start a fresh run from the bedroom save state"
          >
            <Play size={14} /> Start
          </button>
        )}
        <button
          onClick={onStop}
          disabled={busy || !selectedHarness || selectedHarness.status === "idle"}
          title="Stop the selected agent's run (saves an auto-resume checkpoint)"
        >
          <Square size={14} /> Stop
        </button>
        <button
          onClick={onReset}
          disabled={busy || !selectedHarness || selectedHarness.status === "disconnected"}
          title="Stop and discard auto-resume checkpoints for this agent"
        >
          <RotateCcw size={14} /> Reset
        </button>
      </div>

      {selectedHarness?.error && <pre className="harness-error">{selectedHarness.error}</pre>}
    </section>
  );
}
