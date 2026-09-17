"""
LLM client — circuit breaker, retry and cloud→self-hosted fallback (spec
§10.1/§10.3). `LLMClient.complete()` is the ONLY place ai-engine calls an LLM,
so the §10.3 failure table is implemented once. LangChain supplies transport
only (ADR-0007).

`LLMClient` is the layer that talks to a model. It serves up to three
capabilities — chat (`complete`, via `_build`), `embed` and `rerank` — and a
provider implements whichever its API supports. Nodes never see a client
directly for embeddings or reranking: `Embedder` and `Reranker` take one and
own their own contracts.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from ai_engine.core.providers.llm.circuit_breaker import CIRCUIT, CircuitOpenError

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


class LLMClient:
    """One model provider, optionally with a chat fallback behind it.

    `complete()` owns the breaker, the retry and the fallback; a chat provider
    implements only `_build()`. `embed` and `rerank` have no breaker, retry or
    fallback: they RAISE on any failure, because a fallback there would change
    the vector space or the score scale mid-run (ADR-0005). Construction opens no socket:
    `build_providers()` runs at import time and must boot with providers
    unreachable. Uses the module-level `CIRCUIT` — one breaker per process
    (spec §10.1). Otherwise stateless, so safe to share across FastAPI's
    threadpool.

    Chat models are built per timeout rather than once, because the
    per-attempt timeout (derived from the ticket's remaining latency budget)
    must become a real socket timeout with the connect/read split intact, and
    chat models only accept a timeout at construction. Construction costs ~260ms, so they are
    cached. Mutating a shared client's timeout instead would leak one
    ticket's budget into another across the threadpool.
    """

    def __init__(
        self, *, model_name: str, cost_per_1k_tokens: float, fallback: LLMClient | None
    ) -> None:
        # What goes into `LLMResult.model`, and from there into
        # `ai_runs.model_used`. From config rather than from the response, so
        # it reads the same whether the call succeeded or not.
        self.model_name = model_name
        # Passed in by each subclass rather than looked up here, so adding a
        # provider cannot silently inherit another one's rate.
        self.cost_per_1k_tokens = cost_per_1k_tokens
        # None without a cloud provider, leaving vLLM with its retry only.
        self._fallback = fallback
        # Bounded by construction: timeouts are bucketed to whole seconds, and
        # infer.py clamps them to [min_attempt_timeout_sec, model_timeout_sec]
        # — ~116 entries worst case, one cheap HTTP client each.
        self._cache: dict[int, BaseChatModel] = {}

    def supports(self, capability: str) -> bool:
        """Whether this provider implements `capability` ("chat", "embed" or
        "rerank"). Checked at construction by whatever consumes the client, so
        a provider that cannot do the job fails the boot, not a ticket."""

        method = {"chat": "_build", "embed": "embed", "rerank": "rerank"}[capability]
        return getattr(type(self), method) is not getattr(LLMClient, method)

    def _build(self, timeout: float) -> BaseChatModel:
        """Construct this provider's chat model bound to `timeout`. Must not
        retry internally: retry policy lives in `complete()` only."""
        raise NotImplementedError(f"{type(self).__name__} does not serve chat")

    def embed(self, text: str) -> list[float]:
        """One dense vector for `text`. RAISES on any failure."""
        raise NotImplementedError(f"{type(self).__name__} does not serve embeddings")

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """One relevance score per passage, in input order. RAISES on any
        failure."""
        raise NotImplementedError(f"{type(self).__name__} does not serve reranking")

    def complete(self, system_prompt: str, user_prompt: str, *, timeout: float) -> LLMResult:
        """Retry ×2 on this provider → fall back → raise AllLLMDownError
        (spec §10.3).

        Exhaustion RAISES, never returns empty text: infer maps each
        exception to its own degraded_reason, and the HITL dashboard is
        built on that enum.
        """

        if not CIRCUIT.allow_request():
            raise CircuitOpenError("circuit is open — failing fast, not calling any LLM")

        last_error: Exception | None = None
        for attempt in range(2):  # "retry backoff x2"
            try:
                result = self._attempt(system_prompt, user_prompt, timeout)
                CIRCUIT.record(success=True)
                return result
            # Deliberately broad. The four providers raise from DISJOINT
            # exception hierarchies — the openai SDK (used for vLLM too) and the
            # anthropic SDK raise their own over vendored `httpx2` (and
            # `httpx.HTTPError is not httpx2.HTTPError`), google-genai adds a
            # third — on top of whatever langchain-core raises parsing
            # a reply. An enumerated tuple silently rots into a 500 with no
            # TrustSignals the first time a dependency adds an exception type;
            # the failure this protects is a ticket that should have degraded
            # to HITL.
            except Exception as e:
                last_error = e
                logger.warning("LLM call failed (attempt %d/2): %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.5 * (attempt + 1))

        CIRCUIT.record(success=False)

        if self._fallback is not None:
            # Fall back to the self-hosted LLM — a quality degradation, not a
            # failure. Rows written before ADR-0009 carry the old
            # "cloud_fallback_to_ollama" value.
            try:
                result = self._fallback._attempt(system_prompt, user_prompt, timeout)
                return result.model_copy(update={"degraded_reason": "cloud_fallback_to_self_host"})
            except Exception as e:
                last_error = e
                logger.error("self-hosted fallback also failed: %s", e)

        raise AllLLMDownError(str(last_error))

    def _chat_model(self, timeout: float) -> BaseChatModel:
        # Floor rather than round: a bucket must never exceed the budget it
        # was derived from.
        bucket = max(1, int(timeout))
        model = self._cache.get(bucket)
        if model is None:
            # Deliberately unlocked: the loser of a race discards a ~260ms
            # HTTP client, so a lock would cost more than the duplicate.
            model = self._build(float(bucket))
            self._cache[bucket] = model
        return model

    def _attempt(self, system_prompt: str, user_prompt: str, timeout: float) -> LLMResult:
        """One call to this provider. Raises on anything unusable."""

        message = self._chat_model(timeout).invoke(
            [SystemMessage(system_prompt), HumanMessage(user_prompt)]
        )
        text = _content_as_text(message.content)

        # Absent usage metadata means 0: a provider may omit token counts. langchain-core normalises an explicit null to None as
        # well, so a provider emitting nulls undercounts against the token
        # budget rather than failing loudly — recorded in ADR-0007.
        usage = message.usage_metadata or {}
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)

        return LLMResult(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=self.model_name,
            cost_usd=(tokens_in + tokens_out) / 1000 * self.cost_per_1k_tokens,
        )


def _content_as_text(content: Any) -> str:
    """The text of an `AIMessage`, RAISING on blank or block-structured
    content.

    Returned as-is, such content would reach infer as a schema failure
    blamed on the model, when it is a transport problem that should retry,
    fall back and land in HITL as `all_llm_down`.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"LLM returned unusable content: {content!r}")
    return content
