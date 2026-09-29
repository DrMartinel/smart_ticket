"""
LLM clients (ADR-0007, ADR-0009): `LLMClient` for chat, one subclass per
provider. No retries anywhere, SDK ones included (`max_retries=0`): a failed
call goes straight to HITL. `chat`, `embed`, `rerank` and `ner` are built at
import.
"""

from __future__ import annotations

import logging
from functools import cached_property
from typing import Any

import httpx
import httpx2
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, SecretStr

from ai_engine.core.config import settings

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


class LLMClient:
    """One model provider; subclasses implement `_build()`. `client` is built
    at construction so bad config fails the boot, and opens no socket."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None,
        cost_per_1k_tokens: float,
    ) -> None:
        self.model = model
        self.api_key = SecretStr(api_key)
        self.base_url = base_url
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self.client: BaseChatModel = self._build()

    def _build(self) -> BaseChatModel:
        """This provider's chat model, with SDK retries off."""
        raise NotImplementedError(f"{type(self).__name__} does not serve chat")

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """One call, no retry. Any failure raises `AllLLMDownError`."""
        try:
            message = self.client.invoke([SystemMessage(system_prompt), HumanMessage(user_prompt)])
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


# The response_format that makes an OpenAI-compatible provider emit a bare
# JSON object. infer.py does `json.loads(result.text)`, so losing this does
# not fail loudly — it just raises the HITL rate as prose stops parsing.
_JSON_OBJECT = {"type": "json_object"}

VLLM_COST_PER_1K_TOKENS = 0.0
OPENAI_COST_PER_1K_TOKENS = 0.003


def _split_timeout(http_module: Any) -> Any:
    """Short connect, long read: an unreachable server fails fast, a cold
    model load still gets time."""
    return http_module.Timeout(
        settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
    )


class VLLMLLM(LLMClient):
    """One self-hosted vLLM server: chat, or `/embeddings` / `/rerank`
    through `request()`."""

    base_url: str

    def __init__(self, *, model: str, base_url: str) -> None:
        super().__init__(
            model=model,
            api_key="EMPTY",
            base_url=base_url,
            cost_per_1k_tokens=VLLM_COST_PER_1K_TOKENS,
        )

    def _build(self) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            model_kwargs={"response_format": _JSON_OBJECT},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            timeout=_split_timeout(httpx2),
            max_retries=0,
        )

    def request(self, path: str, payload: dict[str, Any]) -> Any:
        """POST JSON to `path`; raises on any failure (ADR-0005)."""
        response = self._http.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    @cached_property
    def _http(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=_split_timeout(httpx),
        )


class OpenAILLM(LLMClient):
    """OpenAI's cloud API, for chat only."""

    def __init__(self) -> None:
        if not settings.cloud_api_key:
            raise ValueError("OpenAILLM requires CLOUD_API_KEY")
        if not settings.cloud_model:
            raise ValueError("OpenAILLM requires CLOUD_MODEL")
        super().__init__(
            model=settings.cloud_model,
            api_key=settings.cloud_api_key,
            base_url=settings.cloud_base_url,
            cost_per_1k_tokens=OPENAI_COST_PER_1K_TOKENS,
        )

    def _build(self) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            model_kwargs={"response_format": _JSON_OBJECT},
            max_completion_tokens=settings.cloud_max_output_tokens,
            timeout=_split_timeout(httpx2),
            max_retries=0,
        )


# --- Clients ----

embed = VLLMLLM(model=settings.embed_model, base_url=settings.embed_base_url)
rerank = VLLMLLM(model=settings.reranker_model, base_url=settings.rerank_base_url)
# PII NER sees RAW ticket text (ADR-0012), so it has its own client on the
# self-hosted chat server and never goes through `chat`, which may be a
# cloud provider. Raw PII must not leave the deployment.
ner = VLLMLLM(model=settings.chat_model, base_url=settings.chat_base_url)

match settings.chat_client_provider:
    case "openai":
        chat: LLMClient = OpenAILLM()
    case "vllm":
        chat = VLLMLLM(model=settings.chat_model, base_url=settings.chat_base_url)
