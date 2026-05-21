from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from harness.examples.tool_agent import MOVE_SETTLE_FRAMES, ToolAgent
from harness.llm import LLMResponse


def _tool_call(name: str, arguments: str = "{}") -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call-{name}",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _llm_response(content: str = "", tool_calls: list[SimpleNamespace] | None = None) -> LLMResponse:
    raw_message = SimpleNamespace(content=content or None, tool_calls=tool_calls or [])
    return LLMResponse(
        provider="fake",
        model="fake-model",
        content=content,
        reasoning=None,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        latency_ms=1,
        attempts=1,
        raw_response=SimpleNamespace(choices=[SimpleNamespace(message=raw_message)]),
    )


def _make_agent(client: MagicMock | None = None) -> ToolAgent:
    client = client or MagicMock()
    client.get_state.return_value = {
        "frame": 1,
        "speed_mode": "paused",
        "pokemon": {"map_id": 38, "x": 3, "y": 6},
    }
    client.client = MagicMock()
    client.client.get.return_value = MagicMock(content=b"\x89PNG\r\n", status_code=200)
    client.emit.return_value = {}
    client.press_button.return_value = {}
    client.press_sequence.return_value = {}
    client.set_speed.return_value = {}
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        agent = ToolAgent(load_state=None, client_factory=lambda _: client)
    agent._llm = MagicMock()
    return agent


def test_move_tool_waits_for_settle_and_reports_before_after() -> None:
    client = MagicMock()
    client.get_state.side_effect = [
        {"pokemon": {"map_id": 38, "x": 3, "y": 6}},
        {"pokemon": {"map_id": 38, "x": 4, "y": 6}},
    ]
    agent = _make_agent(client)

    result = agent._execute_tool("move", {"direction": "RIGHT", "steps": 1})

    assert client.press_button.call_args.args == ("RIGHT", 16)
    assert client.press_sequence.call_args.args == ([{"type": "wait", "frames": MOVE_SETTLE_FRAMES}],)
    assert result == {
        "direction": "RIGHT",
        "steps": 1,
        "before": {"map_id": 38, "x": 3, "y": 6},
        "after": {"map_id": 38, "x": 4, "y": 6},
        "moved": True,
    }


def test_plain_text_response_gets_current_turn_retry_without_history_mutation() -> None:
    client = MagicMock()
    client.get_state.return_value = {
        "frame": 1,
        "speed_mode": "1x",
        "pokemon": {"map_id": 38, "x": 3, "y": 6},
    }
    agent = _make_agent(client)
    client.get_state.return_value = {
        "frame": 1,
        "speed_mode": "1x",
        "pokemon": {"map_id": 38, "x": 3, "y": 6},
    }
    calls: list[list[dict]] = []

    def chat(messages: list[dict], **_: object) -> LLMResponse:
        calls.append(copy.deepcopy(messages))
        if len(calls) == 1:
            return _llm_response("move LEFT")
        if len(calls) == 2:
            return _llm_response(tool_calls=[_tool_call("get_state")])
        agent._stop_event.set()
        return _llm_response("done")

    agent._llm.chat.side_effect = chat

    agent.run()

    assert "Reminder from the player" in calls[1][-1]["content"]
    history_text = "\n".join(str(message.get("content")) for message in agent._history)
    assert "Reminder from the player" not in history_text
    assert "move LEFT" not in history_text
    assert client.set_speed.call_args_list[0].args == ("paused",)
    assert client.set_speed.call_args_list[-1].args == ("1x",)


def test_loop_reminder_reports_repeated_failed_direction() -> None:
    agent = _make_agent()
    pos = {"map_id": 38, "x": 1, "y": 6}
    failed_move = {
        "tool": "move",
        "result": {
            "direction": "LEFT",
            "before": pos,
            "after": pos,
            "moved": False,
        },
    }
    agent._record_turn_outcome(start_pos=pos, end_pos=pos, actions=[failed_move])
    agent._record_turn_outcome(start_pos=pos, end_pos=pos, actions=[failed_move])

    reminder = agent._loop_reminder_for(pos)

    assert reminder is not None
    assert "move LEFT did not change position twice" in reminder
