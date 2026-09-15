"""
LLM client — circuit breaker + budget + retry + cloud→Ollama fallback,
spec §10.1/§10.3. This is the ONLY place in ai-engine that calls out to an
LLM; every caller (infer.py) goes through here so the failure-mode table
in spec §10.3 is implemented once, not scattered across nodes.
"""

from __future__ import annotations

import logging
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_engine.core.config import settings
from ai_engine.core.llm.circuit_breaker import CIRCUIT, CircuitBreaker, CircuitOpenError
from ai_engine.core.providers.base import LLMClient

logger = logging.getLogger(__name__)

# Rough $/1K tokens for cost tracking. Ollama is treated as free (local
# compute); cloud pricing is illustrative — replace with the real
# provider's rate card before trusting cost_per_ticket dashboards.
OLLAMA_COST_PER_1K_TOKENS = 0.0
CLOUD_COST_PER_1K_TOKENS = 0.003


class AllLLMDownError(Exception):
    """Both cloud (if configured) and Ollama failed. Callers must treat
    this as degraded_reason="all_llm_down" -> HITL, never as empty output
    treated like a valid (if boring) proposal."""


class LLMResult(BaseModel):
    """Validated on construction, so a malformed provider response (say a
    null `response`/`content`) fails inside the client, where it is retried
    and falls back, instead of reaching the infer node as `text=None` and
    being blamed on the model as a schema failure."""

    model_config = ConfigDict(frozen=True)

    text: str
    tokens_in: int
    tokens_out: int
    model: str
    cost_usd: float
    degraded_reason: str | None = None


# Provider response bodies, parsed with `model_validate_json` so that EVERY
# malformed reply — not JSON, a missing or null field, an empty `choices` —
# raises ValidationError, which `complete()` retries and falls back on like a
# transport failure. Indexing into `resp.json()` by hand let KeyError,
# IndexError, TypeError and JSONDecodeError escape the client as a 500.
# Token counts default to 0 only when ABSENT (Ollama omits
# `prompt_eval_count` for a cached prompt); a null count is malformed, not
# zero — silently undercounting would loosen the per-ticket token budget.


class _OllamaGenerateResponse(BaseModel):
    response: str
    prompt_eval_count: int = 0
    eval_count: int = 0


class _ChatMessage(BaseModel):
    content: str


class _ChatChoice(BaseModel):
    message: _ChatMessage


class _ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _ChatCompletionResponse(BaseModel):
    choices: list[_ChatChoice] = Field(min_length=1)
    usage: _ChatUsage = _ChatUsage()


def _budget(read_timeout: float) -> httpx.Timeout:
    """Long read budget, short connect budget. An unreachable provider is
    knowable in seconds and should fall through to the next link in the
    fallback chain immediately rather than consuming the whole per-ticket
    latency budget on a connection that will never open."""
    return httpx.Timeout(read_timeout, connect=settings.model_connect_timeout_sec)


def _call_ollama(system_prompt: str, user_prompt: str, timeout: float) -> LLMResult:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    payload = {
        "model": settings.ollama_infer_model,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "format": "json",
        # Hybrid-thinking models (e.g. qwen3.5) default to emitting a long
        # reasoning trace before the final answer, which both blows past
        # reasonable per-ticket latency budgets (spec §10.2) and produces
        # `response` text that isn't itself the JSON object we asked for.
        # Ignored harmlessly by models that don't support the flag.
        "think": False,
    }
    resp = httpx.post(url, json=payload, timeout=_budget(timeout))
    resp.raise_for_status()
    body = _OllamaGenerateResponse.model_validate_json(resp.content)
    tokens_in, tokens_out = body.prompt_eval_count, body.eval_count
    return LLMResult(
        text=body.response,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=f"ollama/{settings.ollama_infer_model}",
        cost_usd=(tokens_in + tokens_out) / 1000 * OLLAMA_COST_PER_1K_TOKENS,
    )


def _call_cloud(system_prompt: str, user_prompt: str, timeout: float) -> LLMResult:
    if not settings.cloud_api_key or not settings.cloud_base_url:
        raise RuntimeError("cloud provider not configured")

    resp = httpx.post(
        f"{settings.cloud_base_url.rstrip('/')}/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.cloud_api_key}"},
        json={
            "model": settings.cloud_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=_budget(timeout),
    )
    resp.raise_for_status()
    body = _ChatCompletionResponse.model_validate_json(resp.content)
    tokens_in, tokens_out = body.usage.prompt_tokens, body.usage.completion_tokens
    return LLMResult(
        text=body.choices[0].message.content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=settings.cloud_model,
        cost_usd=(tokens_in + tokens_out) / 1000 * CLOUD_COST_PER_1K_TOKENS,
    )


def _has_cloud() -> bool:
    return bool(settings.cloud_api_key and settings.cloud_base_url)


class DefaultLLMClient(LLMClient):
    """The `LLMClient` implementation backing the infer node.

    `circuit` defaults to the module singleton on purpose: spec §10.1 says
    one breaker per PROCESS, shared across every request and every client
    instance. The parameter exists so a test can supply an isolated
    breaker — not so production can run several.

    Stateless apart from the breaker it delegates to, so one instance is
    safe to share across FastAPI's threadpool.
    """

    def __init__(self, *, circuit: CircuitBreaker = CIRCUIT) -> None:
        self._circuit = circuit

    def complete(
        self, system_prompt: str, user_prompt: str, *, timeout: float | None = None
    ) -> LLMResult:
        """Retry backoff ×2 on the primary provider → fall back to Ollama →
        raise AllLLMDownError (spec §10.3 failure table, row 1-2).

        Exhaustion is signalled by RAISING, never by returning empty text:
        the infer node maps these two exception types to specific
        degraded_reason codes, and the HITL dashboard is built on that enum.
        """

        circuit = self._circuit

        if timeout is None:
            timeout = settings.model_timeout_sec

        if not circuit.allow_request():
            raise CircuitOpenError("circuit is open — failing fast, not calling any LLM")

        primary_is_cloud = _has_cloud()
        primary_call = _call_cloud if primary_is_cloud else _call_ollama

        last_error: Exception | None = None
        for attempt in range(2):  # "retry backoff x2"
            try:
                result = primary_call(system_prompt, user_prompt, timeout)
                circuit.record(success=True)
                return result
            # ValidationError: the provider answered, but not with a usable
            # result. Same treatment as a transport failure — it must reach
            # AllLLMDownError -> HITL, never escape as a 500.
            except (httpx.HTTPError, RuntimeError, ValidationError) as e:
                last_error = e
                logger.warning("primary LLM call failed (attempt %d/2): %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.5 * (attempt + 1))

        circuit.record(success=False)

        if primary_is_cloud:
            # Fall back to Ollama — a quality degradation, not a failure.
            try:
                result = _call_ollama(system_prompt, user_prompt, timeout)
                return result.model_copy(update={"degraded_reason": "cloud_fallback_to_ollama"})
            except (httpx.HTTPError, ValidationError) as e:
                last_error = e
                logger.error("Ollama fallback also failed: %s", e)

        raise AllLLMDownError(str(last_error))
