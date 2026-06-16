# TODO

Open work only. Move completed items to `CHANGELOG.md` instead of striking them through.

## Gym Agent / reaching Brock

- Add generic map-aware route planning for outdoor maps. Fire Red Route 1 is the current
  proof point: ledges, grass, and wild-battle interruptions need structured map/collision
  state rather than more model-specific waypoint prompting.
- Generalize the per-milestone "skip from shared checkpoint" path beyond the current
  post-starter recovery so known-hard scripted sections can be bypassed consistently.

## Benchmark

- Add provider/API preflight checks for `scripts/bench.py run` so authentication failures
  are reported before spending a row on gameplay setup.

## Harness

- The structured world map (`GymAgent._world`) records visited maps + connections; extend
  it toward a richer inspectable world model (items seen, NPC hints, per-tile collision)
  that also rewinds with checkpoints.
- Replace optimistic learned-wall A* with true static/RAM collision where available, while
  keeping the resulting planner generic across supported games.
