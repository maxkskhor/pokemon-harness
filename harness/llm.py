"""Reusable LLM client helpers for harness authors.

The client is intentionally small: provider adapters do the API-specific call,
while LLMClient owns retry/backoff and common response extraction.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import openai


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 4
    initial_delay_s: float = 2.0
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0
    jitter_s: float = 0.25


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    base_url: str | None
    api_key_env: str
    default_model: str


PROVIDER_PRESETS: dict[str, LLMProviderConfig] = {
    "openrouter": LLMProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="qwen/qwen3.6-flash",
    ),
    "openai": LLMProviderConfig(
        name="openai",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4.1-mini",
    ),
    # Gemini exposes an OpenAI-compatible endpoint. If that drifts, callers can
    # pass their own LLMProviderConfig without changing LLMClient.
    "gemini": LLMProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
    ),
}


class LLMProvider(Protocol):
    name: str
    default_model: str

    def complete(self, *, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """Return the provider SDK's raw chat completion response."""
        ...


@dataclass
class LLMResponse:
    provider: str
    model: str
    content: str
    reasoning: str | None
    usage: dict[str, int | None]
    latency_ms: int
    attempts: int
    raw_response: Any


class LLMCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str,
        attempts: int,
        retryable: bool,
        status_code: int | None = None,
        raw: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.attempts = attempts
        self.retryable = retryable
        self.status_code = status_code
        self.raw = raw

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "attempts": self.attempts,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "message": str(self),
            "raw": self.raw,
        }


class OpenAIChatProvider:
    """Provider adapter for OpenAI-compatible chat completions APIs."""

    def __init__(
        self,
        *,
        name: str,
        default_model: str,
        api_key: str,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.name = name
        self.default_model = default_model
        if client is not None:
            self._client = client
        else:
            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.OpenAI(**kwargs)

    @classmethod
    def from_env(cls, config: LLMProviderConfig) -> OpenAIChatProvider:
        import os

        return cls(
            name=config.name,
            default_model=config.default_model,
            api_key=os.environ[config.api_key_env],
            base_url=config.base_url,
        )

    def complete(self, *, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        create: Any = self._client.chat.completions.create
        return create(model=model, messages=messages, **kwargs)


def provider_from_env(name: str = "openrouter") -> OpenAIChatProvider:
    try:
        config = PROVIDER_PRESETS[name]
    except KeyError as exc:
        known = ", ".join(sorted(PROVIDER_PRESETS))
        raise ValueError(f"Unknown provider preset {name!r}. Known presets: {known}") from exc
    return OpenAIChatProvider.from_env(config)


class LLMClient:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.provider = provider
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        selected_model = model or self.provider.default_model
        attempts = 0
        started_at = self._monotonic()
        last_exc: BaseException | None = None

        while attempts <= self.retry_policy.max_retries:
            attempts += 1
            try:
                raw_response = self.provider.complete(model=selected_model, messages=messages, **kwargs)
                latency_ms = int((self._monotonic() - started_at) * 1000)
                return LLMResponse(
                    provider=self.provider.name,
                    model=selected_model,
                    content=extract_text(raw_response),
                    reasoning=extract_reasoning(raw_response),
                    usage=usage_payload(raw_response),
                    latency_ms=latency_ms,
                    attempts=attempts,
                    raw_response=raw_response,
                )
            except Exception as exc:
                last_exc = exc
                retryable = is_retryable_exception(exc)
                if not retryable or attempts > self.retry_policy.max_retries:
                    raise self._call_error(exc, selected_model, attempts, retryable) from exc
                self._sleep(self._delay_for(attempts))

        # The loop always returns or raises. This keeps type checkers honest.
        assert last_exc is not None
        raise self._call_error(last_exc, selected_model, attempts, is_retryable_exception(last_exc))

    def _delay_for(self, attempt: int) -> float:
        policy = self.retry_policy
        delay = policy.initial_delay_s * (policy.backoff_factor ** max(attempt - 1, 0))
        delay = min(delay, policy.max_delay_s)
        if policy.jitter_s > 0:
            delay += random.uniform(0, policy.jitter_s)
        return delay

    def _call_error(self, exc: BaseException, model: str, attempts: int, retryable: bool) -> LLMCallError:
        status_code = status_code_from_exception(exc)
        raw = raw_error_from_exception(exc)
        message = f"{self.provider.name} LLM call failed after {attempts} attempt(s)"
        if status_code is not None:
            message += f" with HTTP {status_code}"
        message += f": {exc}"
        return LLMCallError(
            message,
            provider=self.provider.name,
            model=model,
            attempts=attempts,
            retryable=retryable,
            status_code=status_code,
            raw=raw,
        )


def extract_reasoning(response: Any) -> str | None:
    msg = response.choices[0].message
    reasoning = getattr(msg, "reasoning", None)
    if not reasoning and hasattr(msg, "model_extra") and msg.model_extra:
        reasoning = msg.model_extra.get("reasoning")
    if reasoning:
        return str(reasoning).strip()
    content = msg.content or ""
    match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_text(response: Any) -> str:
    return (response.choices[0].message.content or "").strip()


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def usage_payload(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def is_retryable_exception(exc: BaseException) -> bool:
    status_code = status_code_from_exception(exc)
    if status_code == 429 or (status_code is not None and 500 <= status_code <= 599):
        return True
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "connection" in name


def status_code_from_exception(exc: BaseException) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    match = re.search(r"\b(?:error code|status code):\s*(\d{3})\b", str(exc), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def raw_error_from_exception(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            data = response.json()
            raw = data.get("error", {}).get("metadata", {}).get("raw")
            if raw:
                return str(raw)
        except Exception:
            pass
        text = getattr(response, "text", None)
        if text:
            return str(text)
    return None
