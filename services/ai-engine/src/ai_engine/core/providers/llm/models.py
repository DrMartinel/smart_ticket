"""
The LLM client layer (spec §10.1/§10.3, ADR-0007): the `LLMClient` base class
and the providers that subclass it.

`LLMClient` only abstracts communication with a model server: chat through
`complete()`, which owns the circuit breaker and retry so the §10.3 failure
table is implemented once, and raw JSON requests
through `request()`. It knows nothing about embeddings or reranking —
`LexicalEmbedder` and `CrossEncoderReranker` build those requests and parse the replies
themselves. LangChain supplies chat transport only.

Each provider implements `_build()` (its chat model, bound to one per-attempt
timeout) and, where its API allows, `request()`. Every provider disables its
SDK's own retries (`max_retries=0`): left on, one `complete()` could send a
dozen requests, silently overrun the per-ticket latency budget and register as
a single breaker failure.

The bottom of this module builds every client from config, once, when it is
imported: `chat`, `embed` and `rerank`.
"""

from __future__ import annotations

import logging
import time
from functools import cached_property
from typing import Any

import httpx
import httpx2
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from ai_engine.core.config import settings
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


class LLMClient:
    """One model provider.

    `complete()` owns the breaker and the retry; a chat provider
    implements only `_build()`. `request()` has no breaker or retry:
    it RAISES on any failure, because its callers (embeddings, reranking) must
    never switch model mid-run (ADR-0005). Construction opens no socket:
    the clients are built at import time and must boot with providers
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

    def __init__(self, *, model_name: str, cost_per_1k_tokens: float) -> None:
        self.model_name = model_name
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self._cache: dict[int, BaseChatModel] = {}

    def _build(self, timeout: float) -> BaseChatModel:
        """Construct this provider's chat model bound to `timeout`. Must not
        retry internally: retry policy lives in `complete()` only."""
        raise NotImplementedError(f"{type(self).__name__} does not serve chat")

    def request(self, path: str, payload: dict[str, Any]) -> Any:
        """POST `payload` as JSON to `path` on this provider's server and
        return the decoded reply. RAISES on transport errors, non-2xx
        statuses and non-JSON bodies."""
        raise NotImplementedError(f"{type(self).__name__} does not send raw requests")

    def complete(self, system_prompt: str, user_prompt: str, *, timeout: float) -> LLMResult:
        """Retry ×2 on this provider → raise AllLLMDownError
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
            except Exception as e:
                last_error = e
                logger.warning("LLM call failed (attempt %d/2): %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.5)

        CIRCUIT.record(success=False)

        raise AllLLMDownError(str(last_error))

    def _chat_model(self, timeout: float) -> BaseChatModel:
        bucket = max(1, int(timeout))
        model = self._cache.get(bucket)
        if model is None:
            model = self._build(float(bucket))
            self._cache[bucket] = model
        return model

    def _attempt(self, system_prompt: str, user_prompt: str, timeout: float) -> LLMResult:
        """One call to this provider. Raises on anything unusable."""

        message = self._chat_model(timeout).invoke(
            [SystemMessage(system_prompt), HumanMessage(user_prompt)]
        )
        text = _content_as_text(message.content)

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


def _cloud_api_key(client: str) -> str:
    """`cloud_api_key`, raising at construction when it is unset: a client
    built without one would boot and fail every ticket."""
    if not settings.cloud_api_key:
        raise ValueError(f"{client} requires CLOUD_API_KEY")
    return settings.cloud_api_key


class VLLMLLM(LLMClient):
    """A self-hosted vLLM server (ADR-0009): chat through `complete()`,
    `/embeddings` and `/rerank` through `request()`. vLLM runs one model per
    server, so there is one instance per server.

    Self-hosted, so it is billed as free, and its model name is prefixed so
    `ai_runs.model_used` tells it apart from a cloud model.
    """

    def __init__(self, *, model: str, base_url: str) -> None:
        super().__init__(model_name=f"vllm/{model}", cost_per_1k_tokens=VLLM_COST_PER_1K_TOKENS)
        self._base_url = base_url
        self._connect_timeout = settings.model_connect_timeout_sec
        self._read_timeout = settings.model_timeout_sec
        self._kwargs: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            "api_key": "EMPTY",
            "model_kwargs": {"response_format": _JSON_OBJECT},
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            **self._kwargs,
            timeout=httpx2.Timeout(timeout, connect=self._connect_timeout),
            max_retries=0,
        )

    def request(self, path: str, payload: dict[str, Any]) -> Any:
        response = self._http.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    @cached_property
    def _http(self) -> httpx.Client:
        # Built on first use and opens no socket until a request. Separate
        # connect and read timeouts: an unreachable server is knowable in
        # seconds, a cold model load takes 15-20s. Collapsing them is the
        # "submit hangs ~120s" bug.
        return httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._read_timeout, connect=self._connect_timeout),
        )


class OpenAILLM(LLMClient):
    """OpenAI's cloud API, for chat only. Reads `cloud_model`, `cloud_api_key`
    and the optional `cloud_base_url` (a proxy) from settings.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name=settings.cloud_model, cost_per_1k_tokens=OPENAI_COST_PER_1K_TOKENS
        )
        self._connect_timeout = settings.model_connect_timeout_sec
        self._kwargs: dict[str, Any] = {
            "model": settings.cloud_model,
            "api_key": _cloud_api_key("OpenAILLM"),
            "model_kwargs": {"response_format": _JSON_OBJECT},
        }
        if settings.cloud_base_url:
            self._kwargs["base_url"] = settings.cloud_base_url

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            **self._kwargs,
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

    def __init__(self) -> None:
        super().__init__(
            model_name=settings.cloud_model,
            cost_per_1k_tokens=ANTHROPIC_COST_PER_1K_TOKENS,
        )
        self._kwargs: dict[str, Any] = {
            "model": settings.cloud_model,
            "api_key": _cloud_api_key("AnthropicLLM"),
            # Defaults to 128000. That is a ceiling, not a reservation, but an
            # unbounded one lets a runaway generation consume the whole
            # per-ticket latency budget — a triage proposal is a small object.
            "max_tokens": settings.cloud_max_output_tokens,
            "max_retries": 0,
        }
        # Omitted rather than passed as None: the SDK falls back to its own
        # default endpoint only when the argument is absent.
        if settings.cloud_base_url:
            self._kwargs["base_url"] = settings.cloud_base_url

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(**self._kwargs, timeout=timeout)


class GeminiLLM(LLMClient):
    """Gemini via the first-party Google Generative AI API. Flat timeout; see
    `AnthropicLLM`."""

    def __init__(self) -> None:
        if settings.cloud_base_url:
            raise ValueError(
                "GeminiLLM does not support a base URL — the Google client has no endpoint "
                "override. Unset CLOUD_BASE_URL, or use 'openai' to reach Gemini through a "
                "compatible gateway."
            )
        super().__init__(
            model_name=settings.cloud_model,
            cost_per_1k_tokens=GEMINI_COST_PER_1K_TOKENS,
        )
        self._kwargs: dict[str, Any] = {
            "model": settings.cloud_model,
            "google_api_key": _cloud_api_key("GeminiLLM"),
            "response_mime_type": "application/json",
            "max_output_tokens": settings.cloud_max_output_tokens,
            "max_retries": 0,
        }

    def _build(self, timeout: float) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(**self._kwargs, timeout=timeout)


# --- Clients ----

embed = VLLMLLM(model=settings.embed_model, base_url=settings.embed_base_url)
rerank = VLLMLLM(model=settings.reranker_model, base_url=settings.rerank_base_url)

match settings.chat_client_provider:
    case "anthropic":
        chat: LLMClient = AnthropicLLM()
    case "gemini":
        chat = GeminiLLM()
    case "openai":
        chat = OpenAILLM()
    case "vllm":
        chat = VLLMLLM(model=settings.chat_model, base_url=settings.chat_base_url)
