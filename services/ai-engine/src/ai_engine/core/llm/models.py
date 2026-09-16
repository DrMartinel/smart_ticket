"""
Chat-model construction for the LLM client (ADR-0007).

LangChain owns TRANSPORT here and nothing else: these factories build a
configured `BaseChatModel` and stop. Retry, fallback, the circuit breaker and
every `degraded_reason` stay in `client.py` — see the ADR for why they are not
`.with_retry()` / `.with_fallbacks()`.

## Why these are factories-of-models rather than models

A factory resolves everything it can from config in `__init__` — the model
name, the billing rate and the full constructor kwargs — and defers exactly
one thing, the per-attempt timeout:

`complete(timeout=...)` gets a PER-ATTEMPT budget computed from the ticket's
remaining latency (infer.py), and that budget has to become a real socket
timeout with the connect/read split intact: 3s to decide the provider is
unreachable, the rest to wait on a model that may legitimately take 15-20s to
warm up. Collapsing the two is the documented "submit hangs ~120s" bug.

Neither chat model accepts a per-invoke timeout — measured, not assumed:
`ChatOllama._chat_params` never forwards one, so `.bind(timeout=...)` is
silently dropped. The timeout is only configurable on the underlying HTTP
client, i.e. at construction. Construction costs ~260ms, far too much to pay
on every attempt, so models are built once per distinct timeout and cached.

Mutating the live client's timeout instead would be cheaper and wrong: `analyze`
is a sync def, so FastAPI runs it in a threadpool, and one ticket's short budget
would silently become another's.
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

    Everything derivable from config is resolved HERE, in `__init__`:
    `model_name`, `cost_per_1k_tokens` and each subclass's `_kwargs` (the
    whole chat-model constructor call except the timeout). They are plain
    attributes rather than properties so a misconfiguration shows up as a
    startup error next to every other one, not on the first ticket that
    happens to read the attribute. `_build` is left with exactly the one
    thing that cannot be known until call time — the per-attempt timeout.

    Construction must still open no socket: `build_providers()` runs at
    uvicorn import time and in tests with no network (test_build.py).
    Verified by test_providers_factory.py.
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
    """An OpenAI-compatible endpoint — which is how the cloud link was already
    being called (`/v1/chat/completions` with a bearer token), so this is the
    same wire protocol, not a new provider."""

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
    """Shared base for the two first-party cloud SDKs.

    ## Why these cannot honour the connect/read split

    Ollama and the OpenAI-compatible link both let us hand the transport a
    real `httpx.Timeout`, so an unreachable provider is knowable in ~3s while
    a slow one still gets the full read budget. Neither of these two does:
    `ChatAnthropic.default_request_timeout` and `ChatGoogleGenerativeAI.timeout`
    are pydantic `float` fields (a `Timeout` object fails validation), and
    neither class exposes an injectable HTTP client. Reaching past that into
    the library's `cached_property` client would work today and break silently
    on upgrade — the exact failure shape this module exists to prevent.

    So these get a FLAT timeout, and that is a real if bounded difference.
    It is tolerable because the split was calibrated for the failure the
    gotchas table actually documents — "containers can't reach Ollama", a
    blackholed connection to a host on the local network. A hosted API that is
    down generally refuses the connection or fails DNS, both of which return
    immediately regardless of the connect budget. Ollama, the case that
    motivated the split, keeps it.

    Both SDKs also retry internally by default (2 for Anthropic, 6 for
    Gemini). Left on, a single `complete()` could issue a dozen requests and
    blow the per-ticket latency budget while the circuit breaker saw one
    failure. Retry policy lives in client.py and nowhere else, so subclasses
    pass `max_retries=0`.
    """


class AnthropicChatModelFactory(_FlatTimeoutCloudFactory):
    """Claude via the first-party Anthropic API.

    NOTE: unlike the other three providers this one has NO JSON output mode —
    Anthropic exposes no `response_format`/`format` equivalent, so the only
    thing keeping the reply parseable is the instruction in the system prompt.
    infer.py already routes unparseable output to HITL rather than a 500
    (commit e2c1247), so this is a HITL-rate risk, not a correctness hole —
    but it means a prompt change is likelier to hurt here than on the others.
    Watch the eval gate when switching to this provider.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        max_output_tokens: int,
        base_url: str | None = None,
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
    """The one value we take from an `AIMessage`, with the contract
    `base.py` states for it: exhaustion is signalled by RAISING, never by
    returning empty text.

    A blank or block-structured `content` reaching infer.py would be parsed as
    a schema failure and blamed on the MODEL (`proposal=None`, no
    degraded_reason) when the truth is a transport-level problem that should
    retry, fall back, and land in HITL as `all_llm_down`. This is the
    replacement for the hand-written response models that used to catch the
    same class of bad reply.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"LLM returned unusable content: {content!r}")
    return content
