"""
LLM client — circuit breaker + budget + retry + cloud→Ollama fallback,
spec §10.1/§10.3. This is the ONLY place in ai-engine that calls out to an
LLM; every caller (infer.py) goes through here so the failure-mode table
in spec §10.3 is implemented once, not scattered across nodes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from ai_engine.config import settings
from ai_engine.llm.circuit_breaker import CIRCUIT, CircuitBreaker, CircuitOpenError

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


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    cost_usd: float
    degraded_reason: str | None = None


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
    data = resp.json()
    tokens_in = data.get("prompt_eval_count", 0)
    tokens_out = data.get("eval_count", 0)
    return LLMResult(
        text=data.get("response", ""),
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
    data = resp.json()
    usage = data.get("usage", {})
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)
    text = data["choices"][0]["message"]["content"]
    return LLMResult(
        text=text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=settings.cloud_model,
        cost_usd=(tokens_in + tokens_out) / 1000 * CLOUD_COST_PER_1K_TOKENS,
    )


def _has_cloud() -> bool:
    return bool(settings.cloud_api_key and settings.cloud_base_url)


class DefaultLLMClient:
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

        return _chat_complete(
            system_prompt, user_prompt, timeout=timeout, circuit=self._circuit
        )


def chat_complete(
    system_prompt: str, user_prompt: str, *, timeout: float | None = None
) -> LLMResult:
    """Migration facade over DefaultLLMClient — removed once the infer node
    takes an `LLMClient` through its constructor."""

    return _chat_complete(system_prompt, user_prompt, timeout=timeout, circuit=CIRCUIT)


def _chat_complete(
    system_prompt: str,
    user_prompt: str,
    *,
    timeout: float | None,
    circuit: CircuitBreaker,
) -> LLMResult:
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
        except (httpx.HTTPError, RuntimeError) as e:
            last_error = e
            logger.warning("primary LLM call failed (attempt %d/2): %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(0.5 * (attempt + 1))

    circuit.record(success=False)

    if primary_is_cloud:
        # Fall back to Ollama — a quality degradation, not a failure.
        try:
            result = _call_ollama(system_prompt, user_prompt, timeout)
            result.degraded_reason = "cloud_fallback_to_ollama"
            return result
        except httpx.HTTPError as e:
            last_error = e
            logger.error("Ollama fallback also failed: %s", e)

    raise AllLLMDownError(str(last_error))
