# Architecture Notes

The project is intentionally split into three parts:

- `env/` owns emulator state, screenshots, controls, save states, and environment traces.
- `harness/` contains external clients and example agent loops that call the environment over HTTP.
- `ui/` shows the live game on the left and merged environment/harness traces on the right.

Generated ROMs, save states, traces, and cloned upstream source are local-only artifacts and are ignored by git.

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
- `POST /api/harness/event`
- `GET /api/runs/{run_id}/env-trace`
- `GET /api/runs/{run_id}/harness-trace`
- `WS /ws/events`
