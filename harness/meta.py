"""Meta-harness: progress tracking, curriculum, checkpointing, and recovery.

Wraps an agent's run with game-aware supervision derived from RAM (via the env
`status` block), independent of what the LLM believes is happening:

- **Milestones**: an ordered journey (bedroom -> ... -> Boulder Badge). Each
  newly reached milestone emits a `milestone` trace event and saves an
  auto-checkpoint, so any point of real progress can be revisited or branched.
- **Curriculum**: the current milestone carries a concrete goal prompt the
  agent injects into its observation, so the LLM always has a near-term
  objective instead of a vague "play the game".
- **Recovery**: detects party wipes (blackout) and prolonged lack of progress,
  and rolls the emulator + agent memory back to the last milestone checkpoint
  (bounded per milestone so it cannot loop forever).
- **Model routing**: cheap model by default, optional escalation model while
  stuck.
- **Budget**: hard USD ceiling for the run.

The class is deliberately agent-facing (composition, not inheritance): the
agent calls `observe()` once per turn and consults `goal()` / `model()`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

Status = dict[str, Any]


def _map_id(status: Status) -> int | None:
    return status.get("map_id")


def _party(status: Status) -> list[dict[str, Any]]:
    return status.get("party") or []


def _max_level(status: Status) -> int:
    return max((mon.get("level") or 0 for mon in _party(status)), default=0)


def _has_real_pokemon(status: Status) -> bool:
    """A genuinely owned Pokemon, not a transient party-count flicker.

    The wPartyCount byte briefly reads 1 during acquisition before the mon's
    species/level are written, so gate on a real (level >= 1) Pokemon.
    """
    return any((mon.get("level") or 0) >= 1 for mon in _party(status))


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    goal: str
    check: Callable[[Status, set[str]], bool]


MILESTONES: list[Milestone] = [
    Milestone(
        "leave-bedroom",
        "Leave the bedroom",
        "You are in your bedroom upstairs. Walk to the staircase in the TOP-RIGHT corner "
        "of the room and step onto it to go downstairs.",
        lambda s, done: _map_id(s) == 37,
    ),
    Milestone(
        "exit-house",
        "Step outside",
        "You are downstairs in your house. Walk DOWN/south to the door mat at the bottom "
        "edge and step outside into Pallet Town.",
        lambda s, done: _map_id(s) == 0,
    ),
    Milestone(
        "get-starter",
        "Get a starter Pokemon",
        "Pallet Town's opening to Route 1 is a gap in the trees on the TOP edge around "
        "x=10, y=0. Walk to x=10 first (do NOT re-enter any house), then keep going UP. "
        "Professor Oak will stop you and bring you to his lab. Advance dialogue with A. "
        "In the lab, the three pokeballs sit ON the table at (6,3), (7,3), (8,3). Choose "
        "SQUIRTLE (strong against the first gym): goto(7,4) — one tile BELOW the middle "
        "ball — then move UP once to face it, and call take_starter() to pick it up "
        "(it confirms YES and declines the nickname for you — do NOT mash A). Your rival "
        "will then challenge you — fight with battle_move(1) until it ends; win or lose, "
        "the story continues.",
        lambda s, done: _has_real_pokemon(s),
    ),
    Milestone(
        "route-1",
        "Reach Route 1",
        "Leave Oak's lab (exit mat at the bottom), then head to Pallet Town's north "
        "opening (top edge around x=10) and walk UP onto Route 1. Fight wild Pokemon "
        "you meet with battle_move(1) for experience.",
        lambda s, done: _map_id(s) == 12,
    ),
    Milestone(
        "viridian-city",
        "Reach Viridian City",
        "Walk north through Route 1 (follow the path, hop down ledges only if they lead "
        "north) until you enter Viridian City.",
        lambda s, done: _map_id(s) == 1,
    ),
    Milestone(
        "deliver-parcel",
        "Deliver Oak's Parcel",
        "In Viridian City, enter the POKE MART (blue roof, east side). The clerk hands you "
        "Oak's Parcel. Walk all the way SOUTH back through Route 1 to Pallet Town and into "
        "Oak's lab; talk to Oak (press A facing him) to deliver the parcel and receive the "
        "Pokedex. Heal at your mom's house next door if your Pokemon are weak.",
        lambda s, done: "viridian-city" in done and _map_id(s) == 40,
    ),
    Milestone(
        "route-2",
        "Head north to Route 2",
        "Return north to Viridian City (heal at the Pokemon Center, red roof, if hurt). "
        "Then walk north out of the city onto Route 2.",
        lambda s, done: "deliver-parcel" in done and _map_id(s) in (13, 50),
    ),
    Milestone(
        "viridian-forest",
        "Enter Viridian Forest",
        "Walk north on Route 2 and through the gate building into Viridian Forest.",
        lambda s, done: _map_id(s) == 51,
    ),
    Milestone(
        "pewter-city",
        "Reach Pewter City",
        "Navigate north through Viridian Forest's winding paths (trainers will battle you "
        "— use battle_move with your strongest move; Bubble or Water Gun if you have it). "
        "Exit the north gate and continue to Pewter City.",
        lambda s, done: _map_id(s) == 2,
    ),
    Milestone(
        "ready-for-gym",
        "Train to level 10+",
        "Before the gym, make sure your lead Pokemon is at least level 10 (Squirtle learns "
        "Bubble at 8). If under-leveled, fight wild Pokemon in the grass south of Pewter "
        "City. Heal at the Pokemon Center when below half HP.",
        lambda s, done: "pewter-city" in done and _max_level(s) >= 10,
    ),
    Milestone(
        "pewter-gym",
        "Enter Pewter Gym",
        "Heal at the Pokemon Center first. The gym is the grey building in the north-west "
        "of Pewter City. Walk in.",
        lambda s, done: _map_id(s) == 54,
    ),
    Milestone(
        "boulder-badge",
        "Beat Brock — Boulder Badge",
        "Walk north past (or through) the junior trainer to Brock and talk to him to start "
        "the fight. His Geodude and Onix are Rock/Ground: water moves (Bubble/Water Gun) do "
        "4x damage. Use battle_move on your water move every turn. If a Pokemon faints, the "
        "next one is sent out automatically — keep fighting.",
        lambda s, done: "Boulder" in (s.get("badges") or []),
    ),
]


@dataclass
class MetaConfig:
    budget_usd: float = 3.0
    overworld_model: str = os.environ.get("POKEMON_AGENT_MODEL") or "openai/gpt-5-nano"
    escalation_model: str = os.environ.get("POKEMON_ESCALATION_MODEL") or "openai/gpt-5-mini"
    # Turns on the same map with no milestone before escalating the model.
    escalate_after_turns: int = 30
    # Turns of no progress before rolling back to the last checkpoint.
    rollback_after_turns: int = 70
    max_rollbacks_per_milestone: int = 2
    auto_rollback: bool = True


@dataclass
class MetaState:
    reached: list[str] = field(default_factory=list)
    turns: int = 0
    turns_since_progress: int = 0
    rollbacks_this_milestone: int = 0
    last_checkpoint: str | None = None
    wipe_pending: bool = False
    cost_at_milestone: dict[str, float] = field(default_factory=dict)
    turn_at_milestone: dict[str, int] = field(default_factory=dict)


class MetaHarness:
    """Per-run supervisor. The owning agent calls `observe()` once per turn."""

    def __init__(
        self,
        *,
        emit: Callable[[str, dict[str, Any]], None],
        save_checkpoint: Callable[[str], Any],
        load_checkpoint: Callable[[str], Any],
        config: MetaConfig | None = None,
    ) -> None:
        self._emit = emit
        self._save = save_checkpoint
        self._load = load_checkpoint
        self.config = config or MetaConfig()
        self.state = MetaState()

    # ── persistence (rides along in checkpoint sidecars) ─────────────

    def serialize(self) -> dict[str, Any]:
        s = self.state
        return {
            "reached": list(s.reached),
            "turns": s.turns,
            "cost_at_milestone": dict(s.cost_at_milestone),
            "turn_at_milestone": dict(s.turn_at_milestone),
        }

    def restore(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        self.state.reached = [k for k in data.get("reached", []) if isinstance(k, str)]
        self.state.turns = int(data.get("turns", 0))
        self.state.turns_since_progress = 0
        self.state.cost_at_milestone = dict(data.get("cost_at_milestone", {}))
        self.state.turn_at_milestone = dict(data.get("turn_at_milestone", {}))

    # ── per-turn supervision ──────────────────────────────────────────

    def observe(self, status: Status, run_cost_usd: float) -> dict[str, Any]:
        """Update progress; returns {'rolled_back': bool, 'over_budget': bool}."""
        s = self.state
        s.turns += 1
        s.turns_since_progress += 1
        done = set(s.reached)

        # Wipe recovery takes precedence over milestone scanning: a blackout
        # respawn can land on a milestone map (e.g. back in Pallet Town) and
        # must not be celebrated as progress.
        #
        # Ignore fainting *during* a battle: a Pokemon at 0 HP mid-fight (or a
        # lost battle) is not a blackout — Gen 1 only blacks you out when the
        # whole party is down in the overworld. Treating the rival-battle loss
        # as a wipe would roll back and discard a freshly caught starter.
        # Only count genuinely owned Pokemon (level >= 1): a mid-acquisition
        # party-count flicker leaves a level-0 / species "#0" slot with 0 HP
        # that would otherwise read as a wipe.
        real_party = [mon for mon in _party(status) if (mon.get("level") or 0) >= 1]
        in_battle = bool(status.get("battle"))
        all_fainted = (
            bool(real_party)
            and not in_battle
            and all((mon.get("hp") or 0) == 0 for mon in real_party)
        )
        if all_fainted and not s.wipe_pending:
            s.wipe_pending = True
            self._emit("warning", {"message": "party wiped — blackout incoming"})
        elif s.wipe_pending and real_party and any((mon.get("hp") or 0) > 0 for mon in real_party):
            s.wipe_pending = False
            rolled = self._rollback("blacked out (party wipe)")
            return {
                "rolled_back": rolled,
                "over_budget": run_cost_usd >= self.config.budget_usd,
            }

        progressed = False
        for index, milestone in enumerate(MILESTONES):
            if milestone.key in done:
                continue
            try:
                hit = milestone.check(status, done)
            except Exception:
                hit = False
            if not hit:
                break  # journey is ordered: stop at the first unreached milestone
            s.reached.append(milestone.key)
            done.add(milestone.key)
            s.turns_since_progress = 0
            s.rollbacks_this_milestone = 0
            s.cost_at_milestone[milestone.key] = round(run_cost_usd, 4)
            s.turn_at_milestone[milestone.key] = s.turns
            checkpoint = f"ms-{index:02d}-{milestone.key}"
            try:
                self._save(checkpoint)
                s.last_checkpoint = checkpoint
            except Exception as exc:
                self._emit("warning", {"message": f"milestone checkpoint failed: {exc}"})
            self._emit(
                "milestone",
                {
                    "key": milestone.key,
                    "label": milestone.label,
                    "index": index,
                    "total": len(MILESTONES),
                    "turn": s.turns,
                    "run_cost_usd": round(run_cost_usd, 4),
                    "checkpoint": checkpoint,
                },
            )
            progressed = True

        rolled_back = False
        if not progressed:
            rolled_back = self._maybe_recover(status)

        return {
            "rolled_back": rolled_back,
            "over_budget": run_cost_usd >= self.config.budget_usd,
        }

    def _maybe_recover(self, status: Status) -> bool:
        if self.state.turns_since_progress >= self.config.rollback_after_turns:
            return self._rollback(f"no progress for {self.state.turns_since_progress} turns")
        return False

    def _rollback(self, reason: str) -> bool:
        s = self.state
        if not self.config.auto_rollback:
            return False
        if s.last_checkpoint is None:
            return False
        if s.rollbacks_this_milestone >= self.config.max_rollbacks_per_milestone:
            self._emit(
                "warning",
                {"message": f"{reason}, but rollback limit reached — continuing as-is"},
            )
            s.turns_since_progress = 0
            return False
        try:
            self._load(s.last_checkpoint)
        except Exception as exc:
            self._emit("warning", {"message": f"rollback failed: {exc}"})
            return False
        s.rollbacks_this_milestone += 1
        s.turns_since_progress = 0
        self._emit(
            "rollback",
            {
                "reason": reason,
                "checkpoint": s.last_checkpoint,
                "rollbacks_this_milestone": s.rollbacks_this_milestone,
            },
        )
        return True

    # ── what the agent consumes ───────────────────────────────────────

    def current_milestone(self) -> Milestone | None:
        done = set(self.state.reached)
        for milestone in MILESTONES:
            if milestone.key not in done:
                return milestone
        return None

    def goal(self) -> str:
        milestone = self.current_milestone()
        if milestone is None:
            return "All milestones complete! Keep exploring."
        done = len(self.state.reached)
        return f"[{done}/{len(MILESTONES)} milestones] {milestone.label}: {milestone.goal}"

    def model(self) -> str:
        if self.state.turns_since_progress >= self.config.escalate_after_turns:
            return self.config.escalation_model
        return self.config.overworld_model

    def journey(self) -> list[dict[str, Any]]:
        done = set(self.state.reached)
        return [
            {"key": m.key, "label": m.label, "reached": m.key in done}
            for m in MILESTONES
        ]
