# Architecture Notes

The project is intentionally split into three parts:

- `env/` owns emulator state, screenshots, controls, save states, and environment traces.
- `harness/` contains external clients and example agent loops that call the environment over HTTP.
- `ui/` shows the live game on the left and merged environment/harness traces on the right.
- `scripts/` contains first-time setup, local dev, verification, ROM build, and run cleanup helpers.

Generated ROMs, save states, traces, and cloned upstream source are local-only artifacts and are ignored by git.

## Runtime Artifacts

- `runs/<run_id>/env.jsonl` stores environment events such as button presses, state loads, and playback markers.
- `runs/<run_id>/harness.jsonl` stores agent events such as turn boundaries, observations, LLM calls, decisions, warnings, and errors.
- `runs/<run_id>/meta.json` is written by the env backend and drives the run picker fields: status, agent, model, ROM, turn count, and last turn summary.
- `runs/<run_id>/frames/<frame>.png` stores deduplicated thumbnails used by the trace UI and frame scrubber.
- `states/<run_id>/<name>.state` stores run-local checkpoints; matching `<name>.agent.json` sidecars store agent history when supplied.
- `states/shared/bedroom.state` is the default shared starting point created by `scripts/setup.sh`.

## API Shape

The environment API is provider-neutral. A harness can be written in any language as long as it calls HTTP endpoints and optionally listens to WebSocket events.

Important endpoints:

- `GET /api/health`
- `POST /api/run/start`
- `POST /api/run/stop`
- `GET /api/state`
- `GET /api/screenshot.png`
- `POST /api/action/press`
- `POST /api/action/sequence`
- `POST /api/step`
- `POST /api/speed`
- `POST /api/save-state`
- `POST /api/load-state`
- `GET /api/runs/{run_id}/states/{name}/agent`
- `POST /api/harness/register`
- `GET /api/harness/list`
- `POST /api/harness/event`
- `POST /api/harness/{harness_id}/play`
- `POST /api/harness/{harness_id}/stop`
- `POST /api/harness/{harness_id}/reset`
- `GET /api/harness/{harness_id}/poll`
- `POST /api/harness/{harness_id}/status`
- `POST /api/harness/{harness_id}/error`
- `POST /api/harness/{harness_id}/unregister`
- `GET /api/runs`
- `GET /api/runs/{run_id}/env-trace`
- `GET /api/runs/{run_id}/harness-trace`
- `GET /api/runs/{run_id}/frames`
- `GET /api/runs/{run_id}/frames/{frame}.png`
- `GET /api/runs/{run_id}/states`
- `GET /api/states/shared`
- `DELETE /api/runs/{run_id}/states/{name}`
- `WS /ws/events`
- `WS /api/harness/{harness_id}/control`

`/api/harness/{harness_id}/poll` remains available for compatibility, but current agents use the control WebSocket.
