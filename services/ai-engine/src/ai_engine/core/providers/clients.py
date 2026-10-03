"""
Model clients (ADR-0007, ADR-0009, ADR-0015). Each client owns its server's
protocol: the request format and the validated reply shape (`dtos.py`).
The providers that call them own the task's rules (vector width, PII-safe
errors, ordering).

- `VLLMClient` (on `HttpClient`, httpx): one self-hosted vLLM server, with
  `embed()`, `rerank()` and `complete_json()`. `embed`, `rerank` and `ner`.
- `JevClient` (on `HttpClient`): TypeSafe's hosted Jev, `ask()`. `jev`.
- `ChatClient`: the triage chat model through LangChain (whose OpenAI SDK
  runs on httpx2), for `chat`. `vllm_chat` / `openai_chat` build it.

No retries anywhere, SDK ones included (`max_retries=0`): a failed call goes
straight to HITL. Every client is built at import and opens no socket until
its first call.
"""

from __future__ import annotations

import json
import logging
from functools import cached_property
from typing import Any

import httpx
import httpx2
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from ai_engine.core.config import settings
from ai_engine.core.providers.dtos import (
    ChatReply,
    ChatRequest,
    EmbeddingsReply,
    EmbeddingsRequest,
    JevReply,
    JevRequest,
    JsonSchema,
    Message,
    RerankReply,
    RerankRequest,
    ResponseFormat,
)

logger = logging.getLogger(__name__)


class AllLLMDownError(Exception):
    """The chat call failed, for any reason → HITL as `all_llm_down`."""


class LLMResult(BaseModel):
    """Validated, so a malformed reply fails in the client, not in infer."""

    model_config = ConfigDict(frozen=True)

    text: str
    tokens_in: int
    tokens_out: int
    model: str
    cost_usd: float


# The response_format that makes an OpenAI-compatible provider emit a bare
# JSON object. infer.py does `json.loads(result.text)`, so losing this does
# not fail loudly — it just raises the HITL rate as prose stops parsing.
_JSON_OBJECT = {"type": "json_object"}

VLLM_COST_PER_1K_TOKENS = 0.0
OPENAI_COST_PER_1K_TOKENS = 0.003


def _split_timeout(http_module: Any) -> Any:
    """Short connect, long read: an unreachable server fails fast, a cold
    model load still gets time. Takes the module because the OpenAI SDK runs
    on httpx2, whose Timeout is its own class."""
    return http_module.Timeout(
        settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
    )


class HttpClient:
    """JSON POSTs to one server, the transport under `VLLMClient` and
    `JevClient`. `api_key`, when set, goes as a bearer token. The connection
    opens on the first request and is reused after."""

    def __init__(self, *, base_url: str, api_key: SecretStr | None = None) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def request(self, path: str, payload: BaseModel) -> Any:
        """POST `payload` as JSON to `path`; raises on any failure, a 429
        included."""
        response = self._http.post(path, json=payload.model_dump(by_alias=True))
        response.raise_for_status()
        return response.json()

    @cached_property
    def _http(self) -> httpx.Client:
        headers = {}
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=_split_timeout(httpx))


class VLLMClient(HttpClient):
    """One self-hosted vLLM server serving `model`, and the request and
    reply format of each endpoint vLLM serves. Every reply is validated
    here; a malformed one raises `ValueError`, never a default."""

    def __init__(self, *, base_url: str, model: str) -> None:
        super().__init__(base_url=base_url)
        self.model = model

    def embed(self, text: str) -> list[float]:
        """`/embeddings`: one vector for one input."""
        body = self.request("/embeddings", EmbeddingsRequest(model=self.model, input=text))
        try:
            return EmbeddingsReply.model_validate(body).data[0].embedding
        except ValidationError as e:
            raise ValueError(f"unusable embeddings reply: {body!r}") from e

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """`/rerank` (Cohere-style): one score per document, in INPUT order.
        No request for no documents."""
        if not documents:
            return []
        body = self.request(
            "/rerank", RerankRequest(model=self.model, query=query, documents=documents)
        )
        try:
            results = RerankReply.model_validate(body).results
        except ValidationError as e:
            raise ValueError(f"unusable rerank reply: {body!r}") from e
        by_index = {r.index: r.relevance_score for r in results}
        expected = len(documents)
        if len(results) != expected or sorted(by_index) != list(range(expected)):
            raise ValueError(
                f"rerank returned indices {sorted(by_index)}, expected 0..{expected - 1}"
            )
        return [by_index[i] for i in range(expected)]

    def complete_json(
        self, system_prompt: str, user_prompt: str, *, schema_name: str, schema: dict[str, Any]
    ) -> Any:
        """`/chat/completions` constrained to a JSON Schema; returns the
        parsed JSON. Errors never quote the reply: for PII NER, the reply
        IS the PII."""
        payload = ChatRequest(
            model=self.model,
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ],
            response_format=ResponseFormat(json_schema=JsonSchema(name=schema_name, schema=schema)),
        )
        body = self.request("/chat/completions", payload)
        try:
            content = ChatReply.model_validate(body).choices[0].message.content
            return json.loads(content)
        except (ValidationError, ValueError):
            raise ValueError("unusable chat reply") from None


class JevClient(HttpClient):
    """TypeSafe's hosted System One API, where Jev runs (ADR-0015). It
    leaves the deployment: only masked ticket text and KB text may go
    through it."""

    def __init__(self, *, base_url: str, api_key: SecretStr | None, model: str) -> None:
        super().__init__(base_url=base_url, api_key=api_key)
        self.model = model

    def ask(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, float]:
        body = self.request(
            "/systemone", JevRequest(model=self.model, state=state, questions=questions)
        )
        try:
            reply = JevReply.model_validate(body)
        except ValidationError as e:
            raise ValueError(f"unusable Jev reply: {body!r}") from e
        if reply.model != self.model:
            raise ValueError(f"Jev answered as {reply.model!r}, expected {self.model!r}")
        if set(reply.answers) != set(questions):
            raise ValueError(f"unusable Jev reply: {body!r}")
        return {qid: answer.noul for qid, answer in reply.answers.items()}


class ChatClient:
    """The triage chat model (InferNode), on whichever provider
    `chat_client_provider` selects: see `vllm_chat` and `openai_chat`."""

    def __init__(self, *, model: str, chat_model: BaseChatModel, cost_per_1k_tokens: float) -> None:
        self.model = model
        self.chat_model = chat_model
        self.cost_per_1k_tokens = cost_per_1k_tokens

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """One call, no retry. Any failure raises `AllLLMDownError`."""
        try:
            message = self.chat_model.invoke(
                [SystemMessage(system_prompt), HumanMessage(user_prompt)]
            )
            text = message.content
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"LLM returned unusable content: {text!r}")

            usage = message.usage_metadata
            tokens_in = usage["input_tokens"] if usage else 0
            tokens_out = usage["output_tokens"] if usage else 0

            return LLMResult(
                text=text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=self.model,
                cost_usd=(tokens_in + tokens_out) / 1000 * self.cost_per_1k_tokens,
            )
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            raise AllLLMDownError(str(e)) from e


def vllm_chat(*, model: str, base_url: str) -> ChatClient:
    """Chat on a self-hosted vLLM server: JSON replies, Qwen's thinking off,
    SDK retries off, billed as free."""
    from langchain_openai import ChatOpenAI

    return ChatClient(
        model=model,
        chat_model=ChatOpenAI(
            model=model,
            api_key=SecretStr("EMPTY"),
            base_url=base_url,
            model_kwargs={"response_format": _JSON_OBJECT},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            timeout=_split_timeout(httpx2),
            max_retries=0,
        ),
        cost_per_1k_tokens=VLLM_COST_PER_1K_TOKENS,
    )


def openai_chat() -> ChatClient:
    """Chat on OpenAI's cloud API: JSON replies, SDK retries off, output
    capped. A missing key or model fails the boot."""
    from langchain_openai import ChatOpenAI

    if not settings.cloud_api_key:
        raise ValueError("openai chat requires CLOUD_API_KEY")
    if not settings.cloud_model:
        raise ValueError("openai chat requires CLOUD_MODEL")
    return ChatClient(
        model=settings.cloud_model,
        chat_model=ChatOpenAI(
            model=settings.cloud_model,
            api_key=SecretStr(settings.cloud_api_key),
            base_url=settings.cloud_base_url,
            model_kwargs={"response_format": _JSON_OBJECT},
            max_completion_tokens=settings.cloud_max_output_tokens,
            timeout=_split_timeout(httpx2),
            max_retries=0,
        ),
        cost_per_1k_tokens=OPENAI_COST_PER_1K_TOKENS,
    )


# --- Clients, built at import (no I/O) ----------------------------------------

embed = VLLMClient(base_url=settings.embed_base_url, model=settings.embed_model)
rerank = VLLMClient(base_url=settings.rerank_base_url, model=settings.reranker_model)
ner = VLLMClient(base_url=settings.chat_base_url, model=settings.chat_model)
jev = JevClient(
    base_url=settings.jev_base_url, api_key=settings.jev_api_key, model=settings.jev_model
)

match settings.chat_client_provider:
    case "openai":
        chat = openai_chat()
    case "vllm":
        chat = vllm_chat(model=settings.chat_model, base_url=settings.chat_base_url)
