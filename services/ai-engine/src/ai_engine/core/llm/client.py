"""
LLM client — circuit breaker + budget + retry + cloud→Ollama fallback,
spec §10.1/§10.3. This is the ONLY place in ai-engine that calls out to an
LLM; every caller (infer.py) goes through here so the failure-mode table
in spec §10.3 is implemented once, not scattered across nodes.

LangChain supplies the transport (see `models.py` and ADR-0007); everything
below the `_invoke` call is unchanged policy.
"""

from __future__ import annotations

import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from ai_engine.core.llm.circuit_breaker import CIRCUIT, CircuitBreaker, CircuitOpenError
from ai_engine.core.llm.models import ChatModelFactory, content_as_text
from ai_engine.core.providers.base import LLMClient

logger = logging.getLogger(__name__)


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


def _invoke(
    factory: ChatModelFactory,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
) -> LLMResult:
    """One attempt against one provider. Raises on anything unusable.

    Replaces the hand-written `_call_ollama` / `_call_cloud` pair and their
    per-provider response schemas: LangChain normalises both wire formats
    into an `AIMessage`, so the only provider-specific knowledge left here is
    the cost rate.
    """
    model = factory(timeout)
    message = model.invoke([SystemMessage(system_prompt), HumanMessage(user_prompt)])

    text = content_as_text(message.content)

    # Absent usage metadata means 0, matching the old behaviour for an Ollama
    # reply that omits `prompt_eval_count` on a cached prompt. NOTE: the old
    # code could tell an ABSENT count from an explicit null and rejected the
    # latter as malformed; langchain-core normalises both to None, so that
    # distinction is gone. Worst case is undercounting against the token
    # budget rather than a loud failure — recorded in ADR-0007.
    usage = message.usage_metadata or {}
    tokens_in = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)

    return LLMResult(
        text=text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        # From config, not from the response: `ai_runs.model_used` must read
        # the same whether the provider echoed a model name or not.
        model=factory.model_name,
        cost_usd=(tokens_in + tokens_out) / 1000 * factory.cost_per_1k_tokens,
    )


class DefaultLLMClient(LLMClient):
    """The `LLMClient` implementation backing the infer node.

    `primary` / `fallback` are resolved ONCE, in `providers/factory.py`, and
    injected. This client no longer re-reads `settings` per call: provider
    selection is a startup decision there, like every other provider choice,
    and a half-configured cloud is fatal at boot rather than invisibly
    degrading to Ollama-only.

    `fallback` is None when no cloud provider is configured — the common case
    in this environment — and then the chain is simply Ollama with retries.

    `circuit` defaults to the module singleton on purpose: spec §10.1 says
    one breaker per PROCESS, shared across every request and every client
    instance. The parameter exists so a test can supply an isolated
    breaker — not so production can run several.

    Stateless apart from the breaker it delegates to, so one instance is
    safe to share across FastAPI's threadpool.
    """

    def __init__(
        self,
        *,
        primary: ChatModelFactory,
        fallback: ChatModelFactory | None = None,
        default_timeout: float,
        circuit: CircuitBreaker = CIRCUIT,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._default_timeout = default_timeout
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
            timeout = self._default_timeout

        if not circuit.allow_request():
            raise CircuitOpenError("circuit is open — failing fast, not calling any LLM")

        last_error: Exception | None = None
        for attempt in range(2):  # "retry backoff x2"
            try:
                result = _invoke(self._primary, system_prompt, user_prompt, timeout)
                circuit.record(success=True)
                return result
            # Deliberately broad. The four providers raise from DISJOINT
            # exception hierarchies — ollama surfaces raw `httpx` errors, the
            # openai and anthropic SDKs raise their own over vendored `httpx2`
            # (and `httpx.HTTPError is not httpx2.HTTPError`), google-genai
            # adds a third — on top of whatever langchain-core raises parsing
            # a reply. An enumerated tuple silently rots into a 500 with no
            # TrustSignals the first time a dependency adds an exception type;
            # the failure this protects is a ticket that should have degraded
            # to HITL.
            except Exception as e:
                last_error = e
                logger.warning("primary LLM call failed (attempt %d/2): %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.5 * (attempt + 1))

        circuit.record(success=False)

        if self._fallback is not None:
            # Fall back to Ollama — a quality degradation, not a failure.
            try:
                result = _invoke(self._fallback, system_prompt, user_prompt, timeout)
                return result.model_copy(update={"degraded_reason": "cloud_fallback_to_ollama"})
            except Exception as e:
                last_error = e
                logger.error("Ollama fallback also failed: %s", e)

        raise AllLLMDownError(str(last_error))
