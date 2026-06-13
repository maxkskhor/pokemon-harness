from __future__ import annotations

from unittest.mock import patch

from harness.examples.gym_agent import GymAgent


def make_agent() -> GymAgent:
    with patch("harness.examples.gym_agent.LLMClient"), \
         patch("harness.examples.gym_agent.provider_from_env"):
        return GymAgent()


def test_purge_boxed_tiles_removes_all_four_blocked() -> None:
    walls = {f"5,5,{d}" for d in ("UP", "DOWN", "LEFT", "RIGHT")}
    walls.add("6,6,UP")  # an unrelated, legitimate wall
    GymAgent._purge_boxed_tiles(walls, 5, 5)
    assert not any(entry.startswith("5,5,") for entry in walls)
    assert "6,6,UP" in walls


def test_restore_sanitizes_boxed_walls() -> None:
    agent = make_agent()
    agent.restore_history({
        "history": [],
        "notes": "",
        "walls": {"40": ["5,5,UP", "5,5,DOWN", "5,5,LEFT", "5,5,RIGHT", "7,4,UP"]},
        "meta": {},
    })
    walls = agent._walls[40]
    assert not any(e.startswith("5,5,") for e in walls)  # bogus boxed tile dropped
    assert "7,4,UP" in walls  # genuine single-direction wall kept


def test_input_locked_reads_status_flags5_bit6() -> None:
    agent = make_agent()
    with patch.object(agent, "state", return_value={"pokemon": {"joy_ignore": 0, "status_flags5": 0x40}}):
        assert agent._input_locked() is True
    with patch.object(agent, "state", return_value={"pokemon": {"joy_ignore": 0, "status_flags5": 0}}):
        assert agent._input_locked() is False
    with patch.object(agent, "state", return_value={"pokemon": {"joy_ignore": 252, "status_flags5": 0}}):
        assert agent._input_locked() is True


def test_loop_detection_after_eight_close_positions() -> None:
    agent = make_agent()
    looping = False
    for _ in range(8):
        looping = agent._is_looping(40, 5, 5)
    assert looping is True
    # Moving far away breaks the loop.
    assert agent._is_looping(40, 20, 20) is False


def test_take_starter_stops_on_acquire_and_declines_nickname() -> None:
    agent = make_agent()
    sim = {"party_count": 0, "a": 0, "menu_state": 0, "party": []}
    presses: list[str] = []

    def fake_press(button: str) -> None:
        presses.append(button)
        if button == "A":
            sim["a"] += 1
            # The 2nd A confirms "Do you want SQUIRTLE? -> YES": the mon is added.
            if sim["a"] == 2:
                sim["party_count"] = 1
                sim["party"] = [{
                    "slot": 1, "nickname": "SQUIRTLE", "level": 5,
                    "hp": 19, "max_hp": 19, "status": None, "moves": [],
                }]

    def fake_state() -> dict:
        return {
            "pokemon": {"party_count": sim["party_count"], "menu_state": sim["menu_state"]},
            "status": {"party": sim["party"], "battle": None, "map_id": 40},
        }

    with patch.object(agent, "press", side_effect=fake_press), \
         patch.object(agent, "sequence"), \
         patch.object(agent, "state", side_effect=fake_state):
        result = agent._tool_take_starter()

    assert result["acquired"] is True
    assert result["phantom_slot"] is False
    # The macro must stop pressing A the instant the party gains a mon (after the
    # 2nd A) — never a 3rd A inside the confirm loop that would open the naming
    # screen. Then it declines the nickname with DOWN+A.
    assert presses == ["UP", "A", "UP", "A", "A", "DOWN", "A", "A"]


def test_take_starter_refuses_in_battle() -> None:
    agent = make_agent()
    with patch.object(agent, "state", return_value={"status": {"battle": {"kind": "wild"}}, "pokemon": {}}):
        result = agent._tool_take_starter()
    assert "error" in result


def test_world_memory_round_trips_through_checkpoint() -> None:
    agent = make_agent()
    agent._world = {
        0: {"name": "Pallet Town", "first_turn": 3, "visits": 5, "connections": {"north": "Route 1"}},
        12: {"name": "Route 1", "first_turn": 8, "visits": 2, "connections": {}},
    }
    snapshot = agent.serialize_history()

    restored = make_agent()
    restored.restore_history(snapshot)
    assert restored._world == agent._world  # int keys preserved, contents intact


def test_update_world_emits_on_first_visit_only() -> None:
    agent = make_agent()
    emitted: list[tuple[str, dict]] = []
    with patch.object(agent, "emit", side_effect=lambda t, p: emitted.append((t, p))):
        agent._update_world({"map_id": 0, "map_name": "Pallet Town", "connections": {}})
        agent._update_world({"map_id": 0, "map_name": "Pallet Town", "connections": {}})
        agent._update_world({"map_id": 12, "map_name": "Route 1", "connections": {}})

    world_updates = [p for t, p in emitted if t == "world_update"]
    assert len(world_updates) == 2  # one per newly discovered map, not per visit
    assert agent._world[0]["visits"] == 2
    assert {u["map_id"] for u in world_updates} == {0, 12}


def test_observation_includes_steer_and_visited_maps() -> None:
    agent = make_agent()
    agent._world = {0: {"name": "Pallet Town", "first_turn": 1, "visits": 1, "connections": {}}}
    status = {"map_id": 0, "map_name": "Pallet Town", "party": [], "badges": [], "money": 0}
    with patch.object(agent, "state", return_value={"pokemon": {"x": 5, "y": 6}}):
        text = agent._observation_text(status, steer=["go back south, you passed the exit"])

    assert "HUMAN STEER" in text
    assert "go back south" in text
    assert "VISITED MAPS" in text and "Pallet Town" in text
