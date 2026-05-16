"""Tests for my_agent.py — reasoning extraction and conversation history."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.examples.my_agent import (
    MAX_HISTORY_TURNS,
    SYSTEM_PROMPT,
    USER_TURN_TEXT,
    MyAgent,
    _extract_reasoning,
    _strip_think_tags,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fake_message(content: str, reasoning: str | None = None, model_extra: dict | None = None):
    msg = MagicMock()
    msg.content = content
    # Simulate direct attribute
    if reasoning is not None:
        msg.reasoning = reasoning
        msg.model_extra = None
    else:
        # No direct attribute
        del msg.reasoning  # MagicMock: remove so getattr returns default
        msg.model_extra = model_extra or {}
    return msg


def _fake_response(content: str, reasoning: str | None = None, model_extra: dict | None = None):
    msg = _fake_message(content, reasoning=reasoning, model_extra=model_extra)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


# ── _extract_reasoning ────────────────────────────────────────────────────────

def test_extract_reasoning_direct_attribute():
    response = _fake_response("UP", reasoning="I should go north.")
    assert _extract_reasoning(response) == "I should go north."


def test_extract_reasoning_model_extra():
    response = _fake_response("UP", model_extra={"reasoning": "heading north"})
    assert _extract_reasoning(response) == "heading north"


def test_extract_reasoning_think_tags():
    content = "<think>player is in bedroom, should go up</think>\nUP"
    response = _fake_response(content, model_extra={})
    assert _extract_reasoning(response) == "player is in bedroom, should go up"


def test_extract_reasoning_none_when_absent():
    response = _fake_response("UP", model_extra={})
    assert _extract_reasoning(response) is None


def test_extract_reasoning_empty_string_treated_as_absent():
    response = _fake_response("UP", reasoning="")
    # empty string is falsy — falls through to think-tag search, finds nothing
    assert _extract_reasoning(response) is None


# ── _strip_think_tags ─────────────────────────────────────────────────────────

def test_strip_think_tags_removes_block():
    assert _strip_think_tags("<think>internal</think>UP") == "UP"


def test_strip_think_tags_multiline():
    text = "<think>\nline1\nline2\n</think>\nDOWN"
    assert _strip_think_tags(text) == "DOWN"


def test_strip_think_tags_no_tags():
    assert _strip_think_tags("LEFT") == "LEFT"


# ── conversation history ──────────────────────────────────────────────────────

def _make_agent() -> MyAgent:
    """Return a MyAgent with all external dependencies mocked out."""
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        agent = MyAgent(load_state=None)
    # Replace internal client and LLM with mocks
    agent._client = MagicMock()
    agent._client.get_state.return_value = {"frame": 1, "pokemon": {"map_id": 38, "x": 3, "y": 6}}
    agent._client.client = MagicMock()
    agent._client.client.get.return_value = MagicMock(content=b"\x89PNG\r\n", status_code=200)
    agent._client.emit.return_value = {}
    agent._client.press_button.return_value = {}
    agent._llm = MagicMock()
    return agent


def _stub_response(agent: MyAgent, button: str, reasoning: str | None = None) -> None:
    """Make agent._llm.chat.completions.create return a stub response."""
    msg = MagicMock()
    msg.content = button
    if reasoning is not None:
        msg.reasoning = reasoning
        msg.model_extra = None
    else:
        del msg.reasoning
        msg.model_extra = {}
    choice = SimpleNamespace(message=msg)
    agent._llm.chat.completions.create.return_value = SimpleNamespace(choices=[choice])


def test_history_starts_with_system_message():
    agent = _make_agent()
    agent._stop_event.set()  # stop after first loop check
    _stub_response(agent, "UP")

    agent.run()

    assert agent._history[0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_history_grows_with_turns():
    agent = _make_agent()
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            agent._stop_event.set()
        msg = MagicMock()
        msg.content = "UP"
        del msg.reasoning
        msg.model_extra = {}
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    agent._llm.chat.completions.create.side_effect = side_effect
    agent.run()

    # system + 3 user + 3 assistant = 7
    assert len(agent._history) == 7
    assert agent._history[0]["role"] == "system"
    assert agent._history[1]["role"] == "user"
    assert agent._history[2]["role"] == "assistant"


def test_history_capped_at_max_turns():
    agent = _make_agent()
    turns = MAX_HISTORY_TURNS + 3
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= turns:
            agent._stop_event.set()
        msg = MagicMock()
        msg.content = "UP"
        del msg.reasoning
        msg.model_extra = {}
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    agent._llm.chat.completions.create.side_effect = side_effect
    agent.run()

    # 1 system + MAX_HISTORY_TURNS * 2 pairs
    expected = 1 + MAX_HISTORY_TURNS * 2
    assert len(agent._history) == expected
    assert agent._history[0]["role"] == "system"


def test_history_passes_all_messages_to_llm():
    agent = _make_agent()
    call_count = 0
    calls: list[list[dict]] = []

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        calls.append(list(kwargs.get("messages", args[0] if args else [])))
        if call_count >= 2:
            agent._stop_event.set()
        msg = MagicMock()
        msg.content = "DOWN"
        del msg.reasoning
        msg.model_extra = {}
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    agent._llm.chat.completions.create.side_effect = side_effect
    agent.run()

    # Second call should include system + user1 + assistant1 + user2
    assert len(calls[1]) == 4
    assert calls[1][0]["role"] == "system"
    assert calls[1][1]["role"] == "user"
    assert calls[1][2]["role"] == "assistant"
    assert calls[1][3]["role"] == "user"


def test_reasoning_included_in_emit():
    agent = _make_agent()

    def side_effect(*args, **kwargs):
        agent._stop_event.set()
        msg = MagicMock()
        msg.content = "UP"
        msg.reasoning = "I think I should go north"
        msg.model_extra = None
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    agent._llm.chat.completions.create.side_effect = side_effect
    agent.run()

    emitted = agent._client.emit.call_args_list
    decision_calls = [c for c in emitted if c.args[0] == "decision"]
    assert decision_calls, "no decision event emitted"
    payload = decision_calls[0].args[1]
    assert payload["reasoning"] == "I think I should go north"
    assert payload["action"] == "UP"
    assert "map_id" not in payload
    assert "x" not in payload
    assert "y" not in payload


def test_user_turn_message_format():
    agent = _make_agent()

    def side_effect(*args, **kwargs):
        agent._stop_event.set()
        msg = MagicMock()
        msg.content = "RIGHT"
        del msg.reasoning
        msg.model_extra = {}
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    agent._llm.chat.completions.create.side_effect = side_effect
    agent.run()

    # The user message content should have image_url and text
    user_msg = agent._history[1]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    types = [c["type"] for c in content]
    assert "image_url" in types
    assert "text" in types
    text_item = next(c for c in content if c["type"] == "text")
    assert text_item["text"] == USER_TURN_TEXT
