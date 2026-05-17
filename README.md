# Pokemon LLM Harness

## Quick Start

**First time only:**
```bash
brew install rgbds
UV_CACHE_DIR=/private/tmp/uv-cache uv sync --dev
cd ui && npm install && cd ..
scripts/setup_pokered.sh          # build ROM (~2 min)
uv run python scripts/setup_bedroom.py  # create bedroom save state (backend must be running first)
```

**Every session:**
```bash
scripts/dev.sh                                   # terminal 1: backend + UI
uv run python -m harness.examples.my_agent       # terminal 2: your agent
# Open http://localhost:5173 → select agent from dropdown → click Play
```

---

A local Pokemon Red/Blue environment for learning how to build an LLM agent harness.

The repo is intentionally split into three parts:

- `env/` owns emulator state, screenshots, controls, save states, and environment traces.
- `harness/` contains external clients and example agent loops that call the environment over HTTP.
- `ui/` shows the live game on the left and separate environment/harness traces on the right.

Generated ROMs, save states, traces, and cloned upstream source are local-only artifacts and are ignored by git.

## License

This project is released under the [MIT License](LICENSE).

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

## Building an Agent Harness

### One-time setup: bedroom save state

After building the ROM, create a save state with Red already standing in the bedroom (post-intro):

```bash
uv run python scripts/setup_bedroom.py
```

This boots the game at max speed, skips the intro dialogue, names the character RED by default, and saves state as `bedroom`. Your harness loads this automatically on every Play.

### Writing your agent

Create a subclass of `PokemonAgent`, set a name, and implement `run()`:

```python
# my_agent.py
from harness import PokemonAgent

class MyAgent(PokemonAgent):
    name = "My Agent"

    def run(self) -> None:
        while not self.should_stop():
            png = self.screenshot_bytes()   # current frame as PNG bytes
            game = self.state()             # frame, map position, party, etc.

            # call your LLM here, then act:
            self.press("A")                 # press a button
            self.emit("step", {"note": "reasoning here"})  # visible in UI

if __name__ == "__main__":
    MyAgent().serve()
```

A minimal working template is at `harness/examples/my_agent.py`.

### Reusable LLM client

`harness.llm.LLMClient` wraps provider calls with retry/backoff and normalized response/error payloads. The example agent uses OpenRouter by default:

```python
from harness.llm import LLMClient, provider_from_env

llm = LLMClient(provider_from_env("openrouter"))
response = llm.chat(messages, model="qwen/qwen3.6-flash")
```

Built-in provider presets:

| Preset | Env var | Notes |
|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | Default example path; supports OpenRouter model IDs such as `qwen/qwen3.6-flash` |
| `openai` | `OPENAI_API_KEY` | Uses the OpenAI SDK default base URL |
| `gemini` | `GEMINI_API_KEY` | Uses Gemini's OpenAI-compatible endpoint |

For another OpenAI-compatible provider, pass your own `LLMProviderConfig`. For a provider with a different API shape, implement the small `LLMProvider` protocol (`name`, `default_model`, and `complete(...)`) and keep the same retry/error handling.

### Running your agent with the UI

1. Start the backend and UI: `scripts/dev.sh`
2. Launch your agent script: `uv run python my_agent.py`
3. Open the UI in your browser
4. Select your agent from the **Harness dropdown** in the right panel
5. Click **Play** — the agent starts, loads the bedroom state, and begins its loop
6. Click **Stop** to interrupt the agent

The right panel shows all events your agent emits via `self.emit(...)`. Click any event to expand its payload.

### Harness API reference

Inside `run()`, these methods are available:

| Method | Description |
|---|---|
| `screenshot_bytes()` | Current frame as raw PNG bytes |
| `screenshot(path)` | Save frame to a file |
| `state()` | Game state dict (frame, map_id, x, y, party_count, …) |
| `press(button, frames=8)` | Press A / B / UP / DOWN / LEFT / RIGHT / START / SELECT |
| `wait(frames)` | Advance the emulator by N frames without pressing a button |
| `sequence(steps)` | Run a list of press/wait dicts as a single atomic sequence |
| `save_state(name)` | Save the current emulator state under a run-local name |
| `load_state(name)` | Load a run-local or shared emulator state by name |
| `emit(type, payload, *, turn_id=None)` | Send an event to the UI trace panel |
| `should_stop()` | True when Stop was clicked — check this in your loop |

For sequence payloads, the helper builders are exported from the package root:

```python
from harness import press, wait

self.sequence([press("RIGHT"), wait(12), press("A")])
```

### Other utilities

- **`harness/replay.py`** — replays button actions from a recorded `env.jsonl` trace back into a live environment. Useful for reproducing a prior run.

  ```bash
  uv run python -m harness.replay runs/<run-id>/env.jsonl
  ```

## Full Verification

```bash
scripts/verify.sh
```

This runs backend tests and the frontend production build. ROM-backed integration checks require `roms/pokered.gbc`, which is created by `scripts/setup_pokered.sh`.
