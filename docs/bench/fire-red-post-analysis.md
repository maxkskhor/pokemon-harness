# Fire Red leaderboard post-analysis

Run date: 2026-06-15

Command:

```bash
uv run python scripts/bench.py run --models openai/gpt-5-nano,google/gemini-2.5-flash-lite,qwen/qwen3.5-flash-02-23,openai/gpt-5-mini --rom pokefirered.gba --max-turns 150 --budget 0.70 --stall-turns 100 -o bench-results-fire-red.json
```

Final leaderboard assembled from the valid run traces:

| Rank | Model | Run | Milestones | Furthest reached | Turns | Cost (USD) | Status |
|---|---|---|---|---|---|---|---|
| 1 | `openai/gpt-5-nano` | `agent-4151590b` | 4/12 | Reach Route 1 | 111 | $0.0172 | stopped |
| 2 | `google/gemini-2.5-flash-lite` | `agent-42240017` | 4/12 | Reach Route 1 | 72 | $0.0457 | stopped |
| 3 | `qwen/qwen3.5-flash-02-23` | `agent-1468d1e0` | 0/12 | - | 1 | $0.0000 | stopped |
| 4 | `openai/gpt-5-mini` | `agent-35599acc` | 0/12 | - | 1 | $0.0000 | stopped |

## What works

- Fire Red now starts from the intended ROM and reaches a playable bedroom state.
- FRLG post-starter handling works: the lab sequence can advance past the starter and return control outside the lab.
- The Gen 3 battle reader exposes enough state for battle-aware observations, including wild battle status, enemy HP/level, player HP, and moves.
- `goto`/`move` now refuse overworld movement while in battle, and wall recording ignores battle-menu input. This prevents wild encounters from poisoning learned wall memory with fake blockers.
- `run_away()` is good enough to clear ordinary Route 1 encounters when the model chooses it.
- `scripts/bench.py run` now isolates backend env sessions between rows and pins escalation to the measured model, so rows are not silently contaminated by a prior run or fallback model.
- The runner now survives provider failures: request timeouts are explicit, fast failures are scored, and disappeared harness records no longer hang the benchmark.

## What did not work

- Neither live gameplay row reached Viridian City. Both nano and Gemini reached Route 1, then stalled on the Route 1 ledge/waypoint problem.
- Prompt-only waypoints were not enough. This is a framework signal, not a request to tune prompts harder: the route needs persistent route state and map topology so any model can resume after interruptions.
- Learned-wall A* is the wrong abstraction for FRLG Route 1. It learns from failed moves, but ledges and route topology need true collision or static map knowledge rather than trial and error.
- Gemini exposed high provider latency and then a non-retryable OpenRouter 401. Qwen and mini were also blocked by the same 401 before gameplay, so their rows are provider/auth failures, not capability results.
- `meta.json` can still report `status: running` after a hard agent error until the backend run is stopped; scoring from `harness.jsonl` remains reliable, but the metadata is misleading without cleanup.

## Improvements

- Add a static collision graph, or read collision from RAM/map data, and make `goto` plan over real passability instead of learned walls. Fire Red Route 1 should be the test case, but the planner should stay generic.
- Track waypoint progress inside the meta-harness for route milestones. After an encounter or rollback, the prompt should say "resume at waypoint N" rather than restating the full route from the entrance.
- Model route progress as inspectable planner state. Avoid hidden one-off macros; if a route helper is added, emit trace events that show the chosen segment, collision inputs, and recovery after battle interruptions.
- Add provider preflight checks before a paid benchmark row. Authentication failures should be caught before spawning the agent.
- Mark backend runs stopped when `_run_wrapped` exits on an unrecoverable LLM error, so `meta.json` status matches the trace.
- Consider benchmark retries for transient provider failures, but keep non-retryable auth errors as explicit failed rows.

## Lessons learned

- Live benchmarks catch different failures than unit tests: the A* warp bounce, provider hangs, stale env sessions, and fast agent-error rows all surfaced only under end-to-end pressure.
- A fair leaderboard needs strict isolation. Stopping only the agent process is not enough; the backend env session must be stopped between rows.
- Hidden fallback models are dangerous in benchmarks. Pinning `POKEMON_ESCALATION_MODEL` to the row model made the results honest.
- Battle state is part of navigation, not a separate system. Route planning must account for wild encounter interruptions and resume cleanly afterward.
- Fire Red is now blocked by generic navigation/planning quality, not Oak's lab or starter harness bugs.
