from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# scripts/ is not a package — load bench.py directly from its file path.
_BENCH_PATH = Path(__file__).resolve().parent.parent / "scripts" / "bench.py"
_spec = importlib.util.spec_from_file_location("bench", _BENCH_PATH)
bench = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
# Register before exec so @dataclass can resolve the module's __dict__.
sys.modules["bench"] = bench
_spec.loader.exec_module(bench)


def _write_run(run_dir: Path, *, milestones: int, turns: int, last_cost: float, model: str) -> None:
    run_dir.mkdir(parents=True)
    events: list[dict] = []
    for i in range(milestones):
        events.append({
            "type": "milestone",
            "turn_id": f"turn-{i:03d}",
            "payload": {"index": i, "total": 12, "label": f"Milestone {i}", "turn": i + 1,
                        "run_cost_usd": round(last_cost * (i + 1) / max(milestones, 1), 4)},
        })
    for t in range(turns):
        events.append({"type": "llm_call", "payload": {"usage": {"run_cost_usd": round(last_cost * (t + 1) / turns, 4)}}})
        events.append({"type": "turn_finished", "payload": {"turn_index": t + 1, "status": "ok"}})
    (run_dir / "harness.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (run_dir / "meta.json").write_text(json.dumps({
        "run_id": run_dir.name, "status": "stopped", "agent": {"name": "Gym Agent", "model": model},
    }))


def test_score_run_reads_milestones_turns_and_cost(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-a"
    _write_run(run_dir, milestones=3, turns=20, last_cost=0.05, model="openai/gpt-5-nano")

    result = bench.score_run(run_dir)

    assert result.milestones_reached == 3
    assert result.milestones_total == 12
    assert result.furthest == "Milestone 2"
    assert result.turns == 20
    assert result.cost_usd == 0.05  # max run_cost_usd across llm_call events
    assert result.model == "openai/gpt-5-nano"
    assert result.status == "stopped"


def test_score_run_handles_zero_milestones(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-empty"
    _write_run(run_dir, milestones=0, turns=5, last_cost=0.01, model="m")
    result = bench.score_run(run_dir)
    assert result.milestones_reached == 0
    assert result.furthest == "—"
    assert result.turns == 5


def test_leaderboard_ranks_by_milestones_then_cost() -> None:
    results = [
        bench.BenchResult("cheap-but-stuck", "r1", 2, 12, "Step outside", 40, 0.02, "stopped"),
        bench.BenchResult("furthest", "r2", 5, 12, "Reach Route 1", 60, 0.30, "stopped"),
        bench.BenchResult("tie-pricey", "r3", 2, 12, "Step outside", 30, 0.10, "stopped"),
    ]
    table = bench.render_leaderboard(results)
    lines = [l for l in table.splitlines() if l.startswith("|") and "Rank" not in l and "---" not in l]

    # Most milestones first; then for the 2-milestone tie, cheaper ranks higher.
    assert "`furthest`" in lines[0]
    assert "`cheap-but-stuck`" in lines[1]
    assert "`tie-pricey`" in lines[2]
