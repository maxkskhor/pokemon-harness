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
