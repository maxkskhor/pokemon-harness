from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from harness.llm import LLMCallError, LLMClient, LLMProviderConfig, OpenAIChatProvider, RetryPolicy


class FakeProvider:
    name = "fake"
    default_model = "fake-model"

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class StatusError(RuntimeError):
    def __init__(self, status_code: int, message: str = "provider error") -> None:
        super().__init__(message)
        self.status_code = status_code


def _response(content: str = "UP") -> Any:
    msg = SimpleNamespace(content=content, model_extra={})
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=1, total_tokens=11)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def _retry_policy() -> RetryPolicy:
    return RetryPolicy(max_retries=2, initial_delay_s=1, max_delay_s=5, jitter_s=0)


def test_llm_client_retries_rate_limit_then_returns_response() -> None:
    provider = FakeProvider([StatusError(429), _response("DOWN")])
    sleeps: list[float] = []
    client = LLMClient(provider, retry_policy=_retry_policy(), sleep_fn=sleeps.append)

    response = client.chat([{"role": "user", "content": "next?"}])

    assert response.provider == "fake"
    assert response.model == "fake-model"
    assert response.content == "DOWN"
    assert response.attempts == 2
    assert response.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 1,
        "total_tokens": 11,
        "cached_tokens": None,
    }
    assert sleeps == [1]
    assert len(provider.calls) == 2


def test_llm_client_raises_payload_after_retry_exhaustion() -> None:
    provider = FakeProvider([StatusError(429), StatusError(429), StatusError(429)])
    client = LLMClient(provider, retry_policy=_retry_policy(), sleep_fn=lambda _: None)

    with pytest.raises(LLMCallError) as raised:
        client.chat([{"role": "user", "content": "next?"}], model="chosen-model")

    err = raised.value
    assert err.provider == "fake"
    assert err.model == "chosen-model"
    assert err.attempts == 3
    assert err.retryable is True
    assert err.status_code == 429
    assert err.to_payload()["status_code"] == 429


def test_llm_client_does_not_retry_non_retryable_error() -> None:
    provider = FakeProvider([StatusError(400)])
    client = LLMClient(provider, retry_policy=_retry_policy(), sleep_fn=lambda _: None)

    with pytest.raises(LLMCallError) as raised:
        client.chat([{"role": "user", "content": "next?"}])

    assert raised.value.attempts == 1
    assert raised.value.retryable is False
    assert len(provider.calls) == 1


def test_openai_provider_uses_env_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("harness.llm.openai.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("POKEMON_LLM_TIMEOUT_S", "12.5")

    OpenAIChatProvider.from_env(
        LLMProviderConfig(
            name="openrouter",
            base_url="https://example.test/api",
            api_key_env="OPENROUTER_API_KEY",
            default_model="test-model",
        )
    )

    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://example.test/api"
    assert captured["timeout"] == 12.5
