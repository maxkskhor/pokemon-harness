# TODO

Open work only. Move completed items to `CHANGELOG.md` instead of striking them through.

## Gym Agent / reaching Brock

- The `get-starter` step now has a deterministic `take_starter` pickup macro
  (`harness/examples/gym_agent.py`), but it has only been verified against a simulated
  lab dialogue in tests — confirm the YES/nickname-NO choreography on a live Oak's-lab
  run and tune the frame waits if the prompts land differently.
- Tune the meta-harness curriculum prompts per phase with screenshots once a stronger
  default model is wired in; gpt-5-nano needs very explicit tile coordinates.
- Add a per-milestone "skip from shared checkpoint" path so a run can resume past a
  known-hard scripted section (a `post-starter` shared state already exists).

## Benchmark

- `scripts/bench.py run` (live head-to-head) has not been exercised end-to-end against a
  running backend yet — only the `score`/leaderboard path is covered by tests. Do a real
  multi-model run and capture a `bench-results.md` for the blog/CV writeup.

## Harness

- The structured world map (`GymAgent._world`) records visited maps + connections; extend
  it toward a richer inspectable world model (items seen, NPC hints, per-tile collision)
  that also rewinds with checkpoints.
