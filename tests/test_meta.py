from __future__ import annotations

from harness.meta import FRLG_MILESTONES, MILESTONES, MetaConfig, MetaHarness


def test_frlg_milestones_mirror_gen1_keys_and_labels() -> None:
    # Same keys + labels across generations so the UI journey tracker (keyed by milestone
    # key) works for both Red/Blue and Fire Red; only the checks/prompts differ.
    assert [m.key for m in FRLG_MILESTONES] == [m.key for m in MILESTONES]
    assert [m.label for m in FRLG_MILESTONES] == [m.label for m in MILESTONES]


def test_frlg_checks_use_frlg_map_ids() -> None:
    by_key = {m.key: m for m in FRLG_MILESTONES}
    # House 1F = 1024, Pallet Town = 768 (FRLG ids), not the Gen-1 37 / 0.
    assert by_key["leave-bedroom"].check({"map_id": 1024}, set()) is True
    assert by_key["leave-bedroom"].check({"map_id": 37}, set()) is False
    assert by_key["exit-house"].check({"map_id": 768}, set()) is True


def make_meta(**config_kwargs):
    events: list[tuple[str, dict]] = []
    saved: list[str] = []
    loaded: list[str] = []
    meta = MetaHarness(
        emit=lambda t, p: events.append((t, p)),
        save_checkpoint=saved.append,
        load_checkpoint=loaded.append,
        config=MetaConfig(**config_kwargs),
    )
    return meta, events, saved, loaded


def overworld(map_id: int, party=None, badges=None) -> dict:
    return {"map_id": map_id, "party": party or [], "badges": badges or []}


def healthy(level=7, hp=20):
    return [{"slot": 1, "level": level, "hp": hp, "max_hp": 24}]


def test_milestones_fire_in_order_and_checkpoint() -> None:
    meta, events, saved, _ = make_meta()
    meta.observe(overworld(37), 0.01)
    meta.observe(overworld(0), 0.02)
    assert meta.state.reached == ["leave-bedroom", "exit-house"]
    assert saved == ["ms-00-leave-bedroom", "ms-01-exit-house"]
    assert [e[0] for e in events] == ["milestone", "milestone"]
    # Later milestones do not fire early: Pewter City requires the journey order.
    meta.observe(overworld(2), 0.03)
    assert "pewter-city" not in meta.state.reached


def test_goal_follows_current_milestone() -> None:
    meta, _, _, _ = make_meta()
    assert "bedroom" in meta.goal().lower()
    meta.observe(overworld(37), 0.0)
    assert "outside" in meta.goal().lower() or "house" in meta.goal().lower()


def test_blackout_triggers_rollback_to_last_checkpoint() -> None:
    meta, events, saved, loaded = make_meta()
    meta.observe(overworld(37, party=healthy()), 0.0)
    # Party wipes, then revives (the game respawned us).
    meta.observe(overworld(12, party=[{"slot": 1, "level": 7, "hp": 0, "max_hp": 24}]), 0.0)
    verdict = meta.observe(overworld(0, party=healthy()), 0.0)
    assert verdict["rolled_back"] is True
    assert loaded == ["ms-00-leave-bedroom"]
    assert any(e[0] == "rollback" for e in events)


def test_fainting_in_battle_is_not_a_blackout() -> None:
    meta, events, _, loaded = make_meta()
    meta.observe(overworld(37, party=healthy()), 0.0)
    # Lead faints DURING a battle — must not be treated as a wipe/rollback.
    fainted = [{"slot": 1, "level": 5, "hp": 0, "max_hp": 20}]
    verdict = meta.observe({"map_id": 40, "party": fainted, "badges": [], "battle": {"kind": "trainer"}}, 0.0)
    assert verdict["rolled_back"] is False
    assert meta.state.wipe_pending is False
    assert loaded == []


def test_rollback_is_bounded_per_milestone() -> None:
    meta, events, _, loaded = make_meta(rollback_after_turns=2, max_rollbacks_per_milestone=1)
    meta.observe(overworld(37), 0.0)
    for _ in range(2):
        meta.observe(overworld(37), 0.0)
    assert loaded == ["ms-00-leave-bedroom"]  # first rollback
    for _ in range(2):
        meta.observe(overworld(37), 0.0)
    assert loaded == ["ms-00-leave-bedroom"]  # no second rollback
    assert any(e[0] == "warning" and "limit" in e[1]["message"] for e in events)


def test_model_escalates_when_stuck() -> None:
    meta, _, _, _ = make_meta(escalate_after_turns=3, rollback_after_turns=100)
    base = meta.model()
    for _ in range(3):
        meta.observe(overworld(38), 0.0)
    assert meta.model() == meta.config.escalation_model != base


def test_budget_verdict() -> None:
    meta, _, _, _ = make_meta(budget_usd=0.5)
    verdict = meta.observe(overworld(38), 0.6)
    assert verdict["over_budget"] is True


def test_serialize_restore_round_trip() -> None:
    meta, _, _, _ = make_meta()
    meta.observe(overworld(37), 0.01)
    blob = meta.serialize()
    meta2, _, _, _ = make_meta()
    meta2.restore(blob)
    assert meta2.state.reached == ["leave-bedroom"]
    assert meta2.current_milestone().key == "exit-house"


def test_journey_shape() -> None:
    meta, _, _, _ = make_meta()
    journey = meta.journey()
    assert len(journey) == len(MILESTONES)
    assert journey[0]["key"] == "leave-bedroom"
    assert journey[-1]["key"] == "boulder-badge"
