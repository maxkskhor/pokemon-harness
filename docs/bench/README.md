# Gym Agent benchmark & saved runs

This folder holds leaderboard results comparing LLM models on the Gym Agent's journey
toward the Boulder Badge, plus self-contained HTML traces of the notable runs.

## What's measured

Each model drives the same harness (`harness/examples/gym_agent.py`) from the same
`bedroom` start state, capped at a fixed turn count and dollar budget. Scoring uses the
meta-harness milestones (`harness/meta.py`) — the headline metric is **how far it got and
at what cost**:

- **Milestones** — how many of the 12 ordered milestones it reached.
- **Furthest** — the label of the last milestone reached.
- **Turns** — agent turns taken.
- **Cost (USD)** — cumulative OpenRouter spend for the run.

Regenerate or extend the leaderboard:

```bash
# Live head-to-head (needs scripts/dev.sh running), capped per model:
uv run python scripts/bench.py run \
  --models openai/gpt-5-nano,google/gemini-2.5-flash-lite,openai/gpt-5-mini \
  --max-turns 80 --budget 0.60 -o docs/bench/results.json

# Score any runs that already happened, no backend needed:
uv run python scripts/bench.py score runs/<run-a> runs/<run-b>
```

## Latest Fire Red leaderboard

Run on 2026-06-15 against `pokefirered.gba`, capped at 150 turns / $0.70 with
stall-abort after 100 turns without a new milestone. Raw rows are in
`../../bench-results-fire-red.json`; rendered table in `../../bench-results-fire-red.md`;
analysis in `fire-red-post-analysis.md`.

| Rank | Model | Milestones | Furthest reached | Turns | Cost (USD) | Notes |
|---|---|---|---|---|---|---|
| 1 | `openai/gpt-5-nano` | 4/12 | Reach Route 1 | 111 | $0.0172 | Stalled on Route 1 → Viridian planning |
| 2 | `google/gemini-2.5-flash-lite` | 4/12 | Reach Route 1 | 72 | $0.0457 | Stalled on Route 1, then provider 401 |
| 3 | `qwen/qwen3.5-flash-02-23` | 0/12 | - | 1 | $0.0000 | Provider 401 before gameplay |
| 4 | `openai/gpt-5-mini` | 0/12 | - | 1 | $0.0000 | Provider 401 before gameplay |

### Current finding

The Fire Red harness path now clears the early scripted game sections: bedroom, Pallet,
Oak's lab, starter, and Route 1. The next framework problem is generic route planning with
real collision/map topology and interruption recovery, not prompt-tuning around one
particular baseline model.

## Gen-1 smoke-test leaderboard

Run on 2026-06-13: 5 models, each from the `bedroom` start state, capped at 150 turns /
$0.70, with stall-abort after 100 turns without a new milestone. Raw rows in
`results.json`; rendered table in `results.md`.

| Rank | Model | Milestones | Furthest reached | Turns | Cost (USD) |
|---|---|---|---|---|---|
| 1 | `openai/gpt-5-nano` | 3/12 | Get a starter Pokemon | 112 | $0.0408 |
| 2 | `qwen/qwen3.5-flash-02-23` | 3/12 | Get a starter Pokemon | 123 | $0.0413 |
| 3 | `google/gemini-2.5-flash-lite` | 3/12 | Get a starter Pokemon | 133 | $0.0650 |
| 4 | `openai/gpt-5-mini` | 2/12 | Step outside | 104 | $0.0749 |
| 5 | `anthropic/claude-haiku-4.5` | 2/12 | Step outside | 104 | $0.3563 |

Total spend for the five final runs: ≈ $0.58.

### Findings from that run

- **The three cheapest models got furthest.** `gpt-5-nano`, `qwen3.5-flash`, and
  `gemini-2.5-flash-lite` each obtained the starter Pokémon; `gpt-5-mini` and the much
  pricier `claude-haiku-4.5` both stalled a step earlier, in Pallet Town. `claude-haiku`
  spent ~9× the cost of the leaders to go *less* far.
- **The run exposed harness bugs, not just model limits.** Subsequent forensics found and
  fixed starter/lab/cutscene and pathing issues; the Fire Red leaderboard above is the
  current baseline.
- **Caveat: n = 1 per model.** These are single runs, so the ordering is noisy — treat it
  as a smoke test of "can this model make early progress cheaply", not a definitive
  ranking. Re-run with several seeds per model for a real comparison.
- The harness behaved correctly throughout: rollback recovery fired when models got stuck,
  and stall-abort capped genuinely-stuck runs (so no run burned the full 150 turns for
  nothing).

## Saved runs

The notable runs from the leaderboard are exported as **self-contained HTML traces** in
this folder (`<model>.html`) — one file each, with the game frames inlined, every turn's
reasoning, tool calls, token/cost usage, and milestone/rollback banners. Open one in a
browser to replay the whole run offline; no server required. These are the durable,
shareable artifacts (the raw `runs/<id>/` directories are local-only and git-ignored).

## How to replay a run

There are three ways, from richest to most portable:

### 1. In the live UI (scrub frames, branch, inspect)

```bash
scripts/dev.sh          # start backend + UI, open http://localhost:5173
```

- Go to the **Runs** tab → open the **View run** picker → choose the run.
- Use the frame **scrubber** to play back every captured frame, or jump to a checkpoint.
- Switch to the **Inspect** tab to read the turn-by-turn trace (reasoning, LLM calls,
  actions, raw payloads), or **Watch** to see the narration replay.
- From a checkpoint you can **Resume** to branch a fresh run from that point.

### 2. Open the exported HTML trace (offline, shareable)

```bash
open docs/bench/<model>.html          # macOS (or just double-click it)
```

Everything is embedded — frames, reasoning, costs, milestones. Nothing to install. This
is what to drop into a blog post or share with someone who doesn't have the repo.

Regenerate an HTML trace for any local run:

```bash
uv run python scripts/generate_trace_html.py runs/<run-id>     # writes runs/<run-id>/trace.html
```

### 3. Re-drive the button inputs through the emulator (CLI)

```bash
uv run python -m harness.replay runs/<run-id>/env.jsonl
```

Replays the recorded button presses against a fresh emulator — useful for verifying a run
deterministically reproduces.
