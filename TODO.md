# TODO

Open work only. Move completed items to `CHANGELOG.md` instead of striking them through.

## Gym Agent / reaching Brock

- The `get-starter` step is the flakiest: a cheap model sometimes opens the Squirtle ball
  but fumbles the "do you want SQUIRTLE? / nickname?" confirmation, leaving a phantom
  level-0 party slot. Consider a deterministic "confirm pokeball pickup" macro (like
  `battle_move`) that drives the YES/NO prompts from menu-cursor reads.
- Tune the meta-harness curriculum prompts per phase with screenshots once a stronger
  default model is wired in; gpt-5-nano needs very explicit tile coordinates.
- Add a per-milestone "skip from shared checkpoint" path so a run can resume past a
  known-hard scripted section (a `post-starter` shared state already exists).

## Advanced Features

- Add human-in-the-loop steering so a human can guide or override an agent during a live run without losing trace continuity.

## Harness

- Add agent memory layers beyond the notes scratchpad (e.g. a structured world map)
  that can be inspected, checkpointed, and restored alongside emulator state.
