"""
LLM client — circuit breaker, budget, retry and cloud→Ollama fallback (spec
§10.1/§10.3). The ONLY place ai-engine calls an LLM, so the §10.3 failure
table is implemented once. LangChain supplies transport only (ADR-0007).
"""

from __future__ import annotations

import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from ai_engine.core.llm.circuit_breaker import CIRCUIT, CircuitOpenError
from ai_engine.core.llm.models import ChatModelFactory, content_as_text
from ai_engine.core.llm.base import LLMClient

logger = logging.getLogger(__name__)


class AllLLMDownError(Exception):
    """Every provider failed. Callers map this to
    degraded_reason="all_llm_down" → HITL, never to an empty proposal.
    """


class LLMResult(BaseModel):
    """Validated on construction, so a malformed reply (e.g. null content)
    fails inside the client, where it is retried, instead of reaching
    infer as `text=None` and being blamed on the model.
    """

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

    LangChain normalises the wire formats, so the cost rate is the only
    provider-specific detail left here.
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
    """The `LLMClient` behind the infer node.

    `primary` / `fallback` are resolved once in `providers/factory.py`;
    `fallback` is None without a cloud provider, leaving Ollama with
    retries. Uses the module-level `CIRCUIT` — one breaker per process
    (spec §10.1). Otherwise stateless, so safe to share across FastAPI's
    threadpool.
    """

    def __init__(
        self,
        *,
        primary: ChatModelFactory,
        fallback: ChatModelFactory | None,
        default_timeout: float,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._default_timeout = default_timeout

    def complete(
        self, system_prompt: str, user_prompt: str, *, timeout: float | None = None
    ) -> LLMResult:
        """Retry ×2 on the primary → fall back to Ollama → raise
        AllLLMDownError (spec §10.3).

        Exhaustion RAISES, never returns empty text: infer maps each
        exception to its own degraded_reason, and the HITL dashboard
        is built on that enum.
        """

        if timeout is None:
            timeout = self._default_timeout

        if not CIRCUIT.allow_request():
            raise CircuitOpenError("circuit is open — failing fast, not calling any LLM")

        last_error: Exception | None = None
        for attempt in range(2):  # "retry backoff x2"
            try:
                result = _invoke(self._primary, system_prompt, user_prompt, timeout)
                CIRCUIT.record(success=True)
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

        CIRCUIT.record(success=False)

        if self._fallback is not None:
            # Fall back to Ollama — a quality degradation, not a failure.
            try:
                result = _invoke(self._fallback, system_prompt, user_prompt, timeout)
                return result.model_copy(update={"degraded_reason": "cloud_fallback_to_ollama"})
            except Exception as e:
                last_error = e
                logger.error("Ollama fallback also failed: %s", e)

        raise AllLLMDownError(str(last_error))
