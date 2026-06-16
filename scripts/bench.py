#!/usr/bin/env python3
"""Benchmark LLM models on the Gym Agent's journey to the Boulder Badge.

Two modes:

  # Score runs that already happened (no emulator/API needed) and print a table:
  python3 scripts/bench.py score runs/agent-0089ab6b runs/gym-agent-f518afc1

  # Run a fresh head-to-head against a live backend (scripts/dev.sh must be up),
  # capping each model at 120 turns / $0.50, then write results.json + leaderboard:
  python3 scripts/bench.py run --models openai/gpt-5-nano,google/gemini-2.5-flash-lite \
      --max-turns 120 --budget 0.50

Scoring uses the meta-harness milestones (the same ordered journey the Gym Agent
follows), so the headline metric is "how far did it get, and at what cost". The
scoring + reporting are pure functions over a run's harness.jsonl, so any past
run can be scored after the fact.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
# Total milestone count — mirrors harness/meta.py. Imported lazily so `score`
# mode works even if optional deps for the agent aren't importable.
try:
    from harness.meta import MILESTONES

    TOTAL_MILESTONES = len(MILESTONES)
except Exception:  # pragma: no cover — fall back to the known journey length
    TOTAL_MILESTONES = 12


# ── pure scoring + reporting (testable without a backend) ──────────────────


@dataclass
class BenchResult:
    model: str
    run_id: str
    milestones_reached: int
    milestones_total: int
    furthest: str
    turns: int
    cost_usd: float
    status: str

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def score_run(run_dir: Path, model_override: str | None = None) -> BenchResult:
    """Score a completed (or in-progress) run directory from its harness trace.

    The furthest milestone reached and its cumulative cost come from `milestone`
    events; total cost falls back to the max `run_cost_usd` seen on any LLM call.
    """
    events = _read_jsonl(run_dir / "harness.jsonl")
    meta = {}
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            meta = {}

    milestones = [e for e in events if e.get("type") == "milestone"]
    reached = len(milestones)
    total = milestones[-1]["payload"].get("total", TOTAL_MILESTONES) if milestones else TOTAL_MILESTONES
    furthest = milestones[-1]["payload"].get("label", "—") if milestones else "—"

    turns = sum(1 for e in events if e.get("type") == "turn_finished")

    costs = [
        e["payload"].get("usage", {}).get("run_cost_usd", 0)
        for e in events
        if e.get("type") == "llm_call"
    ]
    cost = max(costs, default=0.0)

    agent = meta.get("agent") or {}
    model = model_override or agent.get("model") or "?"
    status = meta.get("status", "?")

    return BenchResult(
        model=model,
        run_id=meta.get("run_id", run_dir.name),
        milestones_reached=reached,
        milestones_total=total,
        furthest=furthest,
        turns=turns,
        cost_usd=round(cost, 4),
        status=status,
    )


def render_leaderboard(results: list[BenchResult]) -> str:
    """Markdown leaderboard, best first (most milestones, then cheapest)."""
    ranked = sorted(results, key=lambda r: (-r.milestones_reached, r.cost_usd, r.turns))
    lines = [
        "| Rank | Model | Milestones | Furthest reached | Turns | Cost (USD) | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for rank, r in enumerate(ranked, start=1):
        lines.append(
            f"| {rank} | `{r.model}` | {r.milestones_reached}/{r.milestones_total} "
            f"| {r.furthest} | {r.turns} | ${r.cost_usd:.4f} | {r.status} |"
        )
    return "\n".join(lines)


# ── live runner (needs scripts/dev.sh backend running) ─────────────────────


def _api(base_url: str, method: str, path: str, body: dict | None = None) -> Any:
    import httpx

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        resp = client.request(method, path, json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else None


def _stop_active_run(base_url: str, *, timeout_s: float = 10.0) -> None:
    """Best-effort hard boundary between benchmark models.

    Stopping through the harness control FIFO is not enough for live benchmarks:
    the runner may terminate the agent process before it drains the stop command,
    leaving the backend env session alive for the next model to resume. Stop the
    env directly and wait until /api/state no longer exposes an active session.
    """
    try:
        _api(base_url, "POST", "/api/run/stop")
    except Exception:
        pass

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            state = _api(base_url, "GET", "/api/state")
        except Exception:
            return
        if not (isinstance(state, dict) and state.get("run_id")):
            return
        time.sleep(0.25)


def _model_env(model: str, *, max_turns: int, budget: float, stall_turns: int) -> dict[str, str]:
    return {
        **os.environ,
        "POKEMON_AGENT_MODEL": model,
        # Benchmark rows should measure the requested model, not the meta-harness
        # default escalation fallback.
        "POKEMON_ESCALATION_MODEL": model,
        "POKEMON_MAX_TURNS": str(max_turns),
        "POKEMON_BUDGET_USD": str(budget),
        "POKEMON_STALL_TURNS": str(stall_turns),
    }


def run_model_live(
    model: str,
    *,
    base_url: str,
    max_turns: int,
    budget: float,
    start_state: str,
    poll_timeout_s: float,
    stall_turns: int = 0,
    rom: str | None = None,
) -> BenchResult:
    """Spawn a Gym Agent subprocess pinned to `model`, drive one capped run, score it.

    Mirrors how the UI launcher works: the agent registers over HTTP, we send Play,
    then poll until it returns to idle (turn cap, budget, journey complete, or error).
    """
    env = _model_env(model, max_turns=max_turns, budget=budget, stall_turns=stall_turns)
    # A live benchmark must start a fresh env run. If the backend still has a
    # session from a prior manual/aborted run, PokemonAgent would otherwise
    # resume it instead of loading the requested start state.
    _stop_active_run(base_url)
    before = {h["id"] for h in _api(base_url, "GET", "/api/harness/list")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "harness.examples.gym_agent"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        harness_id = _await_registration(base_url, before, deadline=time.monotonic() + 60)
        if harness_id is None:
            raise RuntimeError(f"agent for {model} never registered")
        _api(base_url, "POST", f"/api/harness/{harness_id}/play", {"rom": rom} if rom else None)
        run_id = _await_run_and_finish(base_url, harness_id, deadline=time.monotonic() + poll_timeout_s)
        # Stop cleanly so the run's auto-resume snapshot + meta.json are flushed.
        try:
            _api(base_url, "POST", f"/api/harness/{harness_id}/stop")
        except Exception:
            pass
        _stop_active_run(base_url)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    run_dir = RUNS_DIR / run_id if run_id else None
    if run_dir and run_dir.exists():
        return score_run(run_dir, model_override=model)
    return BenchResult(model, run_id or "?", 0, TOTAL_MILESTONES, "—", 0, 0.0, "no-run")


def _await_registration(base_url: str, before: set[str], deadline: float) -> str | None:
    while time.monotonic() < deadline:
        for h in _api(base_url, "GET", "/api/harness/list"):
            if h["id"] not in before and (h.get("name") == "Gym Agent"):
                return h["id"]
        time.sleep(0.5)
    return None


def _await_run_and_finish(base_url: str, harness_id: str, deadline: float) -> str | None:
    """Wait for the agent to start running, capture its run_id, then wait for idle."""
    run_id: str | None = None
    saw_running = False
    while time.monotonic() < deadline:
        try:
            state = _api(base_url, "GET", "/api/state")
            if isinstance(state, dict) and state.get("run_id"):
                run_id = state["run_id"]
        except Exception:
            pass
        record = next(
            (h for h in _api(base_url, "GET", "/api/harness/list") if h["id"] == harness_id),
            None,
        )
        status = (record or {}).get("status")
        if status == "running":
            saw_running = True
        elif saw_running and record is None:
            return run_id
        elif (saw_running or run_id) and status in ("idle", "error"):
            return run_id
        time.sleep(1.0)
    return run_id


# ── CLI ────────────────────────────────────────────────────────────────────


def _print_and_save(results: list[BenchResult], out: Path | None) -> None:
    table = render_leaderboard(results)
    print("\n" + table + "\n")
    if out:
        out.write_text(
            json.dumps([r.as_row() for r in results], indent=2) + "\n", encoding="utf-8"
        )
        out.with_suffix(".md").write_text(
            "# Gym Agent benchmark\n\n" + table + "\n", encoding="utf-8"
        )
        print(f"Wrote {out} and {out.with_suffix('.md')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    score_p = sub.add_parser("score", help="Score existing run directories")
    score_p.add_argument("run_dirs", nargs="+", type=Path)
    score_p.add_argument("-o", "--out", type=Path, default=None, help="Write results.json + .md")

    run_p = sub.add_parser("run", help="Run a live head-to-head (backend must be up)")
    run_p.add_argument("--models", required=True, help="Comma-separated model ids")
    run_p.add_argument("--max-turns", type=int, default=120)
    run_p.add_argument("--stall-turns", type=int, default=0,
                       help="Abort a model early if no new milestone for this many turns (0=off)")
    run_p.add_argument("--budget", type=float, default=0.50)
    run_p.add_argument("--start-state", default="bedroom")
    run_p.add_argument("--rom", default=None, help="ROM filename in roms/ (e.g. pokefirered.gba); default = backend default")
    run_p.add_argument("--base-url", default="http://127.0.0.1:8000")
    run_p.add_argument("--poll-timeout", type=float, default=1800.0, help="Per-model seconds")
    run_p.add_argument("-o", "--out", type=Path, default=REPO_ROOT / "bench-results.json")

    args = parser.parse_args()

    if args.mode == "score":
        results = [score_run(d) for d in args.run_dirs]
        _print_and_save(results, args.out)
        return

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    results = []
    for model in models:
        print(f"=== Benchmarking {model} (max {args.max_turns} turns, ${args.budget} budget) ===")
        try:
            result = run_model_live(
                model,
                base_url=args.base_url,
                max_turns=args.max_turns,
                budget=args.budget,
                start_state=args.start_state,
                poll_timeout_s=args.poll_timeout,
                stall_turns=args.stall_turns,
                rom=args.rom,
            )
        except Exception as exc:
            print(f"  {model} failed: {exc}", file=sys.stderr)
            result = BenchResult(model, "?", 0, TOTAL_MILESTONES, "—", 0, 0.0, f"error: {exc}")
        print(f"  -> {result.milestones_reached}/{result.milestones_total} milestones, "
              f"{result.turns} turns, ${result.cost_usd:.4f}")
        results.append(result)
    _print_and_save(results, args.out)


if __name__ == "__main__":
    main()
