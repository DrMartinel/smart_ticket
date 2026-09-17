"""
The LLM providers (ADR-0007). Each subclasses `LLMClient` and implements
`_build()`: the chat model, bound to one per-attempt timeout. Retry, fallback,
the breaker and every `degraded_reason` stay in `client.py`.

Every provider disables its SDK's own retries (`max_retries=0`). Left on, one
`complete()` could send a dozen requests, silently overrun the per-ticket
latency budget and register as a single breaker failure.
"""

from __future__ import annotations

from typing import Any

import httpx2
from langchain_core.language_models import BaseChatModel

from ai_engine.core.providers.llm.client import LLMClient

# The response_format that makes an OpenAI-compatible provider emit a bare
# JSON object. infer.py does `json.loads(result.text)`, so losing this does
# not fail loudly — it just raises the HITL rate as prose stops parsing.
_JSON_OBJECT = {"type": "json_object"}

# Rough $/1K tokens. Self-hosted vLLM is local compute, treated as free. The cloud rates
# are ILLUSTRATIVE — replace each with the provider's real rate card before
# trusting cost_per_ticket dashboards. They live per provider rather than as
# one shared constant because the three cloud providers do not bill alike, and
# a single blended number would make the dashboard confidently wrong.
VLLM_COST_PER_1K_TOKENS = 0.0
OPENAI_COST_PER_1K_TOKENS = 0.003
ANTHROPIC_COST_PER_1K_TOKENS = 0.003
GEMINI_COST_PER_1K_TOKENS = 0.001


class VLLMLLM(LLMClient):
    """A self-hosted vLLM server over its OpenAI-compatible API (ADR-0009).

    Self-hosted, so it is billed as free, and its model name is prefixed so `ai_runs.model_used` tells it apart from a cloud model.
    """

    def __init__(
        self, *, model: str, base_url: str, connect_timeout: float, fallback: LLMClient | None
    ) -> None:
        super().__init__(
            model_name=f"vllm/{model}",
            cost_per_1k_tokens=VLLM_COST_PER_1K_TOKENS,
            fallback=fallback,
        )
        self._connect_timeout = connect_timeout
        self._kwargs: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            # vLLM needs no key, but the openai SDK refuses to build without one.
            "api_key": "EMPTY",
            "model_kwargs": {"response_format": _JSON_OBJECT},
            # Hybrid-thinking models (Qwen3) otherwise emit a long reasoning
            # trace that both blows the latency budget (spec §10.2) and means
            # `content` is not itself the JSON object we asked for.
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            **self._kwargs,
            timeout=httpx2.Timeout(timeout, connect=self._connect_timeout),
            max_retries=0,
        )


class OpenAILLM(LLMClient):
    """An OpenAI-compatible endpoint (`/v1/chat/completions` with a bearer
    token).
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        connect_timeout: float,
        fallback: LLMClient | None,
    ) -> None:
        super().__init__(
            model_name=model, cost_per_1k_tokens=OPENAI_COST_PER_1K_TOKENS, fallback=fallback
        )
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
            # `openai` vendors httpx2, a DIFFERENT package from httpx. Passing
            # an httpx.Timeout here would not be understood.
            timeout=httpx2.Timeout(timeout, connect=self._connect_timeout),
            max_retries=0,
        )


class AnthropicLLM(LLMClient):
    """Claude via the first-party Anthropic API.

    Has NO JSON output mode; only the system prompt keeps replies
    parseable. Unparseable output goes to HITL, so this is a HITL-rate
    risk rather than a correctness hole — watch the eval gate when
    switching to it.

    Takes a FLAT timeout, like `GeminiLLM`: both SDKs take it as a float and
    expose no injectable HTTP client. Acceptable because the connect/read
    split targets a blackholed self-hosted server; a hosted API that is down usually
    refuses the connection or fails DNS immediately.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        max_output_tokens: int,
        base_url: str | None,
        fallback: LLMClient | None,
    ) -> None:
        super().__init__(
            model_name=model, cost_per_1k_tokens=ANTHROPIC_COST_PER_1K_TOKENS, fallback=fallback
        )
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


class GeminiLLM(LLMClient):
    """Gemini via the first-party Google Generative AI API. Flat timeout; see
    `AnthropicLLM`."""

    def __init__(
        self, *, model: str, api_key: str, max_output_tokens: int, fallback: LLMClient | None
    ) -> None:
        super().__init__(
            model_name=model, cost_per_1k_tokens=GEMINI_COST_PER_1K_TOKENS, fallback=fallback
        )
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
