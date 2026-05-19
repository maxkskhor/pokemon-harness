"""Tests for first_agent.py — conversation history and event emission."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.examples.first_agent import (
    MAX_HISTORY_TURNS,
    SYSTEM_PROMPT,
    USER_TURN_TEXT,
    FirstAgent,
    _strip_image_data,
)
from harness.llm import LLMCallError, LLMResponse


# ── helpers ──────────────────────────────────────────────────────────────────

def _llm_response(
    content: str,
    *,
    reasoning: str | None = None,
    usage: dict[str, int | None] | None = None,
    attempts: int = 1,
) -> LLMResponse:
    return LLMResponse(
        provider="fake",
        model="fake-model",
        content=content,
        reasoning=reasoning,
        usage=usage or {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        latency_ms=12,
        attempts=attempts,
        raw_response=SimpleNamespace(),
    )


def _make_agent() -> FirstAgent:
    client = MagicMock()
    client.get_state.return_value = {"frame": 1, "pokemon": {"map_id": 38, "x": 3, "y": 6}}
    client.client = MagicMock()
    client.client.get.return_value = MagicMock(content=b"\x89PNG\r\n", status_code=200)
    client.emit.return_value = {}
    client.press_button.return_value = {}
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        agent = FirstAgent(load_state=None, client_factory=lambda _: client)
    agent._llm = MagicMock()
    return agent


def _stub_response(agent: FirstAgent, button: str, reasoning: str | None = None) -> None:
    agent._llm.chat.return_value = _llm_response(button, reasoning=reasoning)


# ── _strip_image_data ─────────────────────────────────────────────────────────

def test_strip_image_data_replaces_inline_base64():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
                {"type": "text", "text": "next?"},
            ],
        }
    ]

    stripped = _strip_image_data(messages)

    assert stripped[0]["content"][0]["image_url"]["url"] == "<image omitted: see frame thumbnail>"
    assert messages[0]["content"][0]["image_url"]["url"] == "data:image/png;base64,abc123"


# ── conversation history ──────────────────────────────────────────────────────

def test_history_starts_with_system_message():
    agent = _make_agent()
    agent._stop_event.set()
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
        return _llm_response("UP")

    agent._llm.chat.side_effect = side_effect
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
        return _llm_response("UP")

    agent._llm.chat.side_effect = side_effect
    agent.run()

    # 1 system + MAX_HISTORY_TURNS * 2 pairs
    assert len(agent._history) == 1 + MAX_HISTORY_TURNS * 2
    assert agent._history[0]["role"] == "system"


def test_history_passes_all_messages_to_llm():
    agent = _make_agent()
    call_count = 0
    calls: list[list[dict]] = []

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        calls.append(list(args[0]))
        if call_count >= 2:
            agent._stop_event.set()
        return _llm_response("DOWN")

    agent._llm.chat.side_effect = side_effect
    agent.run()

    # Second call should include system + user1 + assistant1 + user2
    assert len(calls[1]) == 4
    assert calls[1][0]["role"] == "system"
    assert calls[1][1]["role"] == "user"
    assert calls[1][2]["role"] == "assistant"
    assert calls[1][3]["role"] == "user"


# ── event emission ────────────────────────────────────────────────────────────

def test_reasoning_included_in_emit():
    agent = _make_agent()

    def side_effect(*args, **kwargs):
        agent._stop_event.set()
        return _llm_response("UP", reasoning="I think I should go north")

    agent._llm.chat.side_effect = side_effect
    agent.run()

    emitted = agent._client.emit.call_args_list
    decision_calls = [c for c in emitted if c.args[0] == "decision"]
    assert decision_calls, "no decision event emitted"
    payload = decision_calls[0].args[1]
    assert payload["reasoning"] == "I think I should go north"
    assert payload["action"] == "UP"


def test_llm_call_event_includes_sanitized_messages_and_latency():
    agent = _make_agent()

    def side_effect(*args, **kwargs):
        agent._stop_event.set()
        return _llm_response(
            "UP",
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        )

    agent._llm.chat.side_effect = side_effect
    agent.run()

    emitted = agent._client.emit.call_args_list
    llm_calls = [c for c in emitted if c.args[0] == "llm_call"]
    assert llm_calls, "no llm_call event emitted"
    payload = llm_calls[0].args[1]
    user_content = payload["messages"][1]["content"]
    assert user_content[0]["image_url"]["url"] == "<image omitted: see frame thumbnail>"
    assert payload["response"] == "UP"
    assert payload["usage"]["prompt_tokens"] == 10
    assert isinstance(payload["usage"]["latency_ms"], int)


def test_llm_call_emit_includes_provider_and_retry_attempts():
    agent = _make_agent()

    def side_effect(*args, **kwargs):
        agent._stop_event.set()
        return _llm_response(
            "RIGHT",
            usage={"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13},
            attempts=3,
        )

    agent._llm.chat.side_effect = side_effect
    agent.run()

    llm_call = next(c for c in agent._client.emit.call_args_list if c.args[0] == "llm_call")
    payload = llm_call.args[1]
    assert payload["provider"] == "fake"
    assert payload["model"] == "fake-model"
    assert payload["usage"]["attempts"] == 3


def test_llm_error_emitted_before_raising():
    agent = _make_agent()
    error = LLMCallError(
        "fake failed",
        provider="fake",
        model="fake-model",
        attempts=3,
        retryable=True,
        status_code=429,
        raw="rate limited upstream",
    )
    agent._llm.chat.side_effect = error

    with pytest.raises(LLMCallError):
        agent.run()

    llm_error = next(c for c in agent._client.emit.call_args_list if c.args[0] == "llm_error")
    payload = llm_error.args[1]
    assert payload["status_code"] == 429
    assert payload["raw"] == "rate limited upstream"


def test_user_turn_message_format():
    agent = _make_agent()

    def side_effect(*args, **kwargs):
        agent._stop_event.set()
        return _llm_response("RIGHT")

    agent._llm.chat.side_effect = side_effect
    agent.run()

    user_msg = agent._history[1]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    types = [c["type"] for c in content]
    assert "image_url" in types
    assert "text" in types
    text_item = next(c for c in content if c["type"] == "text")
    assert text_item["text"] == USER_TURN_TEXT
