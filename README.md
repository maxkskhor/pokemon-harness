# Pokemon LLM Harness

A local Pokemon Red/Blue environment for learning how to build an LLM agent harness.

The repo is intentionally split into three parts:

- `env/` owns emulator state, screenshots, controls, save states, and environment traces.
- `harness/` contains external clients and example agent loops that call the environment over HTTP.
- `ui/` shows the live game on the left and separate environment/harness traces on the right.

Generated ROMs, save states, traces, and cloned upstream source are local-only artifacts and are ignored by git.

## Legal Boundary

This project does not download or distribute commercial ROM files. The setup script can build local ROM-compatible binaries from `pret/pokered` source for personal development, but you are responsible for making sure your use complies with applicable law.

## Setup

Install system tools:

```bash
brew install rgbds
```

Install Python dependencies:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv sync --dev
```

Install UI dependencies:

```bash
cd ui
npm install
```

Build local Pokemon Red/Blue ROMs:

```bash
scripts/setup_pokered.sh
```

This clones `pret/pokered` into `third_party/pokered`, runs `make` and `make compare`, then copies generated ROM and symbol files into `roms/`.

## Run

Start backend and frontend:

```bash
scripts/dev.sh
```

Open the Vite URL printed by the script. The backend defaults to `http://127.0.0.1:8000`; the frontend defaults to `http://127.0.0.1:5173`.

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

## Deterministic Verification Harness

Once the backend is running and `roms/pokered.gbc` exists:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run python -m harness.examples.starter_route --run-id verify-starter
```

The example starts a run, emits harness trace events, drives deterministic button sequences, saves state, and records environment actions separately from harness events. The final event includes `starter_obtained`; the current script is primarily a smoke test for the full stack and trace plumbing, not a solved Pokemon route.

## Full Verification

```bash
scripts/verify.sh
```

This runs backend tests and the frontend production build. ROM-backed integration checks require `roms/pokered.gbc`, which is created by `scripts/setup_pokered.sh`.
