"""
Chat-model construction for the LLM client (ADR-0007). LangChain owns
transport only; retry, fallback, the breaker and every `degraded_reason` stay
in `client.py`.

Factories rather than models because the per-attempt timeout (derived from the
ticket's remaining latency budget) must become a real socket timeout with the
connect/read split intact: 3s to call a provider unreachable, the rest for a
model that may take 15-20s to warm up. Chat models only accept a timeout at
construction (`ChatOllama` silently drops `.bind(timeout=...)`), and
construction costs ~260ms, so models are built once per timeout and cached.
Mutating a shared client's timeout instead would leak one ticket's budget into
another across the threadpool.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx
import httpx2
from langchain_core.language_models import BaseChatModel

# The response_format that makes an OpenAI-compatible provider emit a bare
# JSON object. infer.py does `json.loads(result.text)`, so losing this does
# not fail loudly — it just raises the HITL rate as prose stops parsing.
_JSON_OBJECT = {"type": "json_object"}

# Rough $/1K tokens. Ollama is local compute, treated as free. The cloud rates
# are ILLUSTRATIVE — replace each with the provider's real rate card before
# trusting cost_per_ticket dashboards. They live per-factory rather than as one
# shared constant because the three cloud providers do not bill alike, and a
# single blended number would make the dashboard confidently wrong.
OLLAMA_COST_PER_1K_TOKENS = 0.0
OPENAI_COST_PER_1K_TOKENS = 0.003
ANTHROPIC_COST_PER_1K_TOKENS = 0.003
GEMINI_COST_PER_1K_TOKENS = 0.001


class ChatModelFactory(ABC):
    """Builds a chat model bound to one per-attempt timeout.

    `model_name`, `cost_per_1k_tokens` and `_kwargs` are resolved in
    `__init__` as plain attributes, so misconfiguration fails at startup;
    `_build` only applies the timeout. Construction opens no socket:
    `build_providers()` runs at import time and must boot with providers
    unreachable.
    """

    def __init__(self, *, model_name: str, cost_per_1k_tokens: float) -> None:
        # What goes into `LLMResult.model`, and from there into
        # `ai_runs.model_used`. From config rather than from the response, so
        # it reads the same whether the call succeeded or not.
        self.model_name = model_name
        # Billing rate for this provider. Passed in by each subclass rather
        # than looked up here, so adding a provider cannot silently inherit
        # another one's rate.
        self.cost_per_1k_tokens = cost_per_1k_tokens
        # Bounded by construction: the caller buckets timeouts to whole
        # seconds, and infer.py clamps them to
        # [min_attempt_timeout_sec, model_timeout_sec] — ~116 entries worst
        # case, one cheap HTTP client each.
        self._cache: dict[int, BaseChatModel] = {}

    def __call__(self, timeout: float) -> BaseChatModel:
        # Floor rather than round: a bucket must never exceed the budget it
        # was derived from.
        bucket = max(1, int(timeout))
        model = self._cache.get(bucket)
        if model is None:
            # Deliberately unlocked, unlike CrossEncoderReranker's model load.
            # The loser of a race discards a ~260ms HTTP client, not a
            # multi-GB model, so a lock would cost more than the duplicate.
            model = self._build(float(bucket))
            self._cache[bucket] = model
        return model

    @abstractmethod
    def _build(self, timeout: float) -> BaseChatModel:
        """Apply the per-attempt timeout to the kwargs `__init__` resolved."""


class OllamaChatModelFactory(ChatModelFactory):
    def __init__(self, *, model: str, base_url: str, connect_timeout: float) -> None:
        super().__init__(model_name=f"ollama/{model}", cost_per_1k_tokens=OLLAMA_COST_PER_1K_TOKENS)
        self._connect_timeout = connect_timeout
        self._kwargs: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            # Reproduces the old payload's `"format": "json"`.
            "format": "json",
            # Reproduces the old payload's `"think": False`. Hybrid-thinking
            # models (qwen3.5) otherwise emit a long reasoning trace that both
            # blows the latency budget (spec §10.2) and means `content` is not
            # itself the JSON object we asked for.
            "reasoning": False,
        }

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            **self._kwargs,
            # `ollama` builds its httpx client with this verbatim, so the
            # connect/read split survives.
            client_kwargs={"timeout": httpx.Timeout(timeout, connect=self._connect_timeout)},
        )


class OpenAIChatModelFactory(ChatModelFactory):
    """An OpenAI-compatible endpoint (`/v1/chat/completions` with a bearer
    token).
    """

    def __init__(self, *, model: str, base_url: str, api_key: str, connect_timeout: float) -> None:
        super().__init__(model_name=model, cost_per_1k_tokens=OPENAI_COST_PER_1K_TOKENS)
        self._connect_timeout = connect_timeout
        self._kwargs: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "model_kwargs": {"response_format": _JSON_OBJECT},
        }

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            **self._kwargs,
            # `openai` vendors httpx2, a DIFFERENT package from the httpx the
            # ollama client uses — hence the second import. Passing an
            # httpx.Timeout here would not be understood.
            timeout=httpx2.Timeout(timeout, connect=self._connect_timeout),
            # The openai SDK retries twice on its own by default. Left on, a
            # single `complete()` could issue six requests and silently
            # overrun the per-ticket latency budget. Retry policy lives in
            # client.py and nowhere else.
            max_retries=0,
        )


class _FlatTimeoutCloudFactory(ChatModelFactory):
    """Shared base for the first-party Anthropic and Gemini SDKs.

    These get a FLAT timeout: both take it as a pydantic `float` and
    expose no injectable HTTP client, and reaching into the library's
    cached client would break silently on upgrade. Acceptable because the
    connect/read split targets a blackholed local Ollama; a hosted API
    that is down usually refuses the connection or fails DNS immediately.

    Both SDKs retry internally by default (2 for Anthropic, 6 for Gemini).
    Subclasses pass `max_retries=0` so retry policy stays in client.py and
    the breaker sees every failure.
    """


class AnthropicChatModelFactory(_FlatTimeoutCloudFactory):
    """Claude via the first-party Anthropic API.

    Has NO JSON output mode; only the system prompt keeps replies
    parseable. Unparseable output goes to HITL, so this is a HITL-rate
    risk rather than a correctness hole — watch the eval gate when
    switching to it.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        max_output_tokens: int,
        base_url: str | None,
    ) -> None:
        super().__init__(model_name=model, cost_per_1k_tokens=ANTHROPIC_COST_PER_1K_TOKENS)
        self._kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            # Defaults to 128000. That is a ceiling, not a reservation, but an
            # unbounded one lets a runaway generation consume the whole
            # per-ticket latency budget — a triage proposal is a small object.
            "max_tokens": max_output_tokens,
            "max_retries": 0,
        }
        # Omitted rather than passed as None: the SDK falls back to its own
        # default endpoint only when the argument is absent.
        if base_url:
            self._kwargs["base_url"] = base_url

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(**self._kwargs, timeout=timeout)


class GeminiChatModelFactory(_FlatTimeoutCloudFactory):
    """Gemini via the first-party Google Generative AI API."""

    def __init__(self, *, model: str, api_key: str, max_output_tokens: int) -> None:
        super().__init__(model_name=model, cost_per_1k_tokens=GEMINI_COST_PER_1K_TOKENS)
        self._kwargs: dict[str, Any] = {
            "model": model,
            "google_api_key": api_key,
            # Gemini's equivalent of the other providers' JSON mode.
            "response_mime_type": "application/json",
            "max_output_tokens": max_output_tokens,
            "max_retries": 0,
        }

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        # langchain converts this to google-genai's milliseconds for us — it is
        # seconds on this side of the boundary, like every other timeout here.
        return ChatGoogleGenerativeAI(**self._kwargs, timeout=timeout)


def content_as_text(content: Any) -> str:
    """The text of an `AIMessage`, RAISING on blank or block-structured
    content.

    Returned as-is, such content would reach infer as a schema failure
    blamed on the model, when it is a transport problem that should retry,
    fall back and land in HITL as `all_llm_down`.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"LLM returned unusable content: {content!r}")
    return content
