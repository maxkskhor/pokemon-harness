# LESSONS.md — Lessons learned building the Pokemon harness

## Don't conflate game state with LLM context

Game state and the LLM message list are two separate things that serve different purposes. Mixing them causes subtle, compounding problems.

**Game state** is the authoritative record of what happened in the world: positions, tool call results, screenshots, actions taken, turn summaries. It belongs in observability events (`actions`, `get_state` results, run traces).

**LLM context** is what you choose to show the model so it can make good decisions. It should be minimal, stable, and cache-friendly. It is a *projection* of game state — not a dump of it.

### What goes wrong when you conflate them

- Raw tool call JSON (`json.dumps(actions_taken)`) ends up in the assistant message slot in history. The model sees API plumbing (tool names, argument dicts, result dicts) instead of a clean game summary.
- Screenshots get stored in history. Every historical turn carries its image into the next LLM call, inflating token count linearly and making it impossible to trim history without busting the prefix cache.
- Observability events become a mix of LLM internals (reasoning, raw response) and game-level facts (what button was pressed), making it hard to answer either question: "what did the model see?" or "what happened in the game?"

### The fix

Keep two explicit tracks:

1. **LLM track** (`llm_call` event): exact messages sent, raw response, usage with cache hit info. Emitted once per API round.
2. **Game track** (`actions` event): tool calls with game-world results, plain-text action summary. Emitted once per turn.

Build history from game-level summaries (e.g. `"move RIGHT×3→(x=5,y=6,map=38), press A"`), not from raw API objects. Store only the current screenshot in the live user message; strip images from history entries so the prefix stays text-only and cache-stable.
