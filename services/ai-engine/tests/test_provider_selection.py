"""
Provider selection tests. These are about failure modes at startup, not about which
provider is "right" — the point is that a misconfiguration is loud.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_engine.core.config import Settings, settings
from ai_engine.core.providers.llm.models import (
    ANTHROPIC_COST_PER_1K_TOKENS,
    VLLM_COST_PER_1K_TOKENS,
    AnthropicLLM,
    GeminiLLM,
    OpenAILLM,
    VLLMLLM,
)
from ai_engine.core.db import client as db_client
from ai_engine.core.db.client import SqlAlchemySessionSource


def test_unknown_reranker_provider_raises_rather_than_falling_back_to_lexical(
    monkeypatch, reload_reranker
):
    """A typo'd RERANKER_PROVIDER must not fall back to lexical — a different
    calibration from the one `retrieval.floor` is fitted against
    (ADR-0005). The refuse-before-LLM rate would be wrong with everything
    green.
    """

    monkeypatch.setattr(settings, "reranker_provider", "cross-encoder")
    with pytest.raises(ValueError, match="unknown reranker_provider"):
        reload_reranker()


def test_unknown_embedding_provider_raises(monkeypatch, reload_embeddings):
    """Same failure shape as above: silently embedding with the wrong
    provider produces plausible-looking vectors and quietly bad recall."""

    monkeypatch.setattr(settings, "embedding_provider", "stubb")
    with pytest.raises(ValueError, match="unknown embedding_provider"):
        reload_embeddings()


def test_default_reranker_is_the_vllm_cross_encoder(reload_reranker):
    """Pins the shipped default: the cross-encoder `retrieval.floor` is
    specified against (ADR-0005), served by vLLM (ADR-0009). `lexical` is for
    CI and must be selected explicitly.

    Does NOT assert calibration — see docs/TODO.md item 4.
    """

    assert settings.reranker_provider == "vllm"
    m = reload_reranker()
    assert type(m.reranker) is m.CrossEncoderReranker


def test_building_providers_opens_no_connections(monkeypatch, reload_reranker):
    """main.py imports the modules that build the providers, and test_build.py
    imports main.py with no database. A constructor that opens a socket breaks
    both.
    """

    monkeypatch.setattr(settings, "reranker_provider", "lexical")
    m = reload_reranker()

    assert isinstance(m.reranker, m.LexicalReranker)
    assert isinstance(db_client.db, SqlAlchemySessionSource)  # constructed, not connected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("stub", "StubEmbedder"), ("vllm", "LexicalEmbedder")],
)
def test_embedding_provider_selection(provider, expected, monkeypatch, reload_embeddings):
    monkeypatch.setattr(settings, "embedding_provider", provider)
    m = reload_embeddings()
    assert type(m.embedder) is getattr(m, expected)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("lexical", "LexicalReranker"), ("vllm", "CrossEncoderReranker")],
)
def test_reranker_provider_selection(provider, expected, monkeypatch, reload_reranker):
    monkeypatch.setattr(settings, "reranker_provider", provider)
    m = reload_reranker()
    assert type(m.reranker) is getattr(m, expected)


def test_each_vllm_client_is_built_from_config_for_its_own_server(monkeypatch, reload_models):
    """vLLM serves one model per server, so chat, embeddings and reranking
    each have their own client — built from config, pointing at their own
    base URL."""

    m = reload_models()
    built = {"chat": m.chat, "embed": m.embed, "rerank": m.rerank}
    assert {name: c._base_url for name, c in built.items()} == {
        "chat": settings.chat_base_url,
        "embed": settings.embed_base_url,
        "rerank": settings.rerank_base_url,
    }
    assert {name: c._kwargs["model"] for name, c in built.items()} == {
        "chat": settings.chat_model,
        "embed": settings.embed_model,
        "rerank": settings.reranker_model,
    }


# --- LLM chain wiring (ADR-0007) -------------------------------------------
#
# Provider selection for the LLM happens once, when models.py is imported, so
# these are startup tests like the ones above: the point is that a
# misconfiguration is loud.


@pytest.fixture
def cloud_key(monkeypatch):
    """First-party providers read their key from settings, and their SDKs
    refuse to build a chat model without one."""

    monkeypatch.setattr(settings, "cloud_api_key", "k")
    monkeypatch.setattr(settings, "cloud_base_url", None)


def _chat_on(monkeypatch, provider, cloud_base_url=None):
    monkeypatch.setattr(settings, "chat_client_provider", provider)
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", cloud_base_url)


def test_default_chat_runs_on_vllm(reload_models):
    m = reload_models()
    assert isinstance(m.chat, m.VLLMLLM)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("vllm", "VLLMLLM"),
        ("openai", "OpenAILLM"),
        ("anthropic", "AnthropicLLM"),
        ("gemini", "GeminiLLM"),
    ],
)
def test_chat_client_provider_selects_the_chat_class(
    provider, expected, monkeypatch, reload_models
):
    _chat_on(monkeypatch, provider)
    m = reload_models()

    assert type(m.chat) is getattr(m, expected)


def test_unknown_chat_provider_is_rejected_by_settings():
    """A typo must fail the boot, not quietly select some default."""

    with pytest.raises(ValidationError):
        Settings(chat_client_provider="vLLM")


def test_gemini_with_a_base_url_is_fatal_rather_than_silently_ignoring_it(
    monkeypatch, reload_models
):
    """ChatGoogleGenerativeAI has no endpoint override, so a CLOUD_BASE_URL
    set alongside it would be dropped on the floor while the operator believed
    traffic was being routed through their gateway."""

    _chat_on(monkeypatch, "gemini", "https://proxy.example")
    with pytest.raises(ValueError, match="does not support a base URL"):
        reload_models()


def test_anthropic_accepts_an_optional_base_url(monkeypatch, reload_models):
    """Unlike gemini, the Anthropic client does take an endpoint override, so
    a base_url here is a proxy setting rather than a misconfiguration."""

    _chat_on(monkeypatch, "anthropic", "https://proxy.example")
    m = reload_models()

    assert isinstance(m.chat, m.AnthropicLLM)


def test_first_party_chat_without_an_api_key_is_fatal(monkeypatch, reload_models):
    """No key must fail the boot, not every ticket."""

    _chat_on(monkeypatch, "anthropic")
    monkeypatch.setattr(settings, "cloud_api_key", None)

    with pytest.raises(ValueError, match="requires CLOUD_API_KEY"):
        reload_models()


@pytest.mark.parametrize(
    "provider",
    ["openai", "anthropic", "gemini"],
)
def test_building_chat_models_opens_no_connections(provider, monkeypatch, reload_models):
    """models.py builds its clients at import time, so constructing a chat
    model must configure an HTTP client, not use one. Pinned per provider
    because the first-party SDKs build their transports eagerly.
    """

    import socket

    _chat_on(monkeypatch, provider)

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    chat = reload_models().chat
    # Force the lazily-built model into existence too — the cache means
    # construction is deferred until the first call with a given timeout.
    chat._chat_model(30.0)

    assert opened == []


@pytest.mark.parametrize(
    ("factory", "attr", "expected"),
    [
        (
            lambda: GeminiLLM(),
            "response_mime_type",
            "application/json",
        ),
    ],
)
def test_providers_with_a_json_mode_actually_set_it(factory, attr, expected, cloud_key):
    """infer.py does `json.loads(result.text)`. A lost JSON flag fails
    quietly: the model wraps its object in prose and every ticket degrades
    to HITL as if it were the model's fault. Anthropic has no JSON mode
    (ADR-0007).
    """

    assert getattr(factory()._chat_model(30.0), attr) == expected


def test_no_cloud_sdk_retries_on_top_of_ours(cloud_key):
    """Both first-party SDKs retry internally (2 for Anthropic, 6 for
    Gemini). Left on, one complete() could send a dozen requests, blow the
    latency budget and register a single breaker failure. Retry lives only
    in `LLMClient.complete()`.
    """

    anthropic = AnthropicLLM()._chat_model(30.0)
    gemini = GeminiLLM()._chat_model(30.0)

    assert anthropic.max_retries == 0
    assert gemini.max_retries == 0


def test_flat_timeout_providers_still_bound_the_call(cloud_key):
    """The first-party SDKs can't express the connect/read split (ADR-0007)
    but must still carry the per-attempt read budget; unset, a hung
    request outlives the ticket.
    """

    anthropic = AnthropicLLM()._chat_model(45.0)
    gemini = GeminiLLM()._chat_model(45.0)

    assert anthropic.default_request_timeout == 45.0
    assert gemini.timeout == 45.0


def test_chat_models_are_cached_per_timeout_bucket():
    """Construction costs ~260ms, which is why models are cached rather than
    built per attempt. Buckets floor to whole seconds so a bucket can never
    exceed the budget it came from."""

    llm = VLLMLLM(model="Qwen/Qwen3-8B-AWQ", base_url="http://localhost:8100/v1")

    assert llm._chat_model(30.0) is llm._chat_model(30.4), "same bucket must reuse the model"
    assert llm._chat_model(30.0) is not llm._chat_model(31.0), (
        "a different budget needs its own client"
    )


def test_provider_attributes_are_resolved_at_construction(cloud_key):
    """`model_name` and `cost_per_1k_tokens` are resolved in __init__, not
    lazily. They feed `ai_runs.model_used` / `cost_usd` whether or not the
    call succeeds, and reading them must not build a chat model — which
    keeps importing models.py socket-free.
    """

    vllm = VLLMLLM(model="Qwen/Qwen3-8B-AWQ", base_url="http://localhost:8100/v1")
    anthropic = AnthropicLLM()

    assert vllm.model_name == "vllm/Qwen/Qwen3-8B-AWQ"
    assert vllm.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS
    assert anthropic.model_name == "claude-sonnet-5"
    assert anthropic.cost_per_1k_tokens == ANTHROPIC_COST_PER_1K_TOKENS
    assert vllm._cache == {} and anthropic._cache == {}, (
        "reading an attribute must not build a model"
    )


# --- Self-hosted LLM (ADR-0009) --------------------------------------------


def test_vllm_llm_asks_for_json_without_thinking_or_sdk_retries():
    """JSON mode keeps `json.loads` in infer.py working; a thinking trace
    would blow the latency budget; SDK retries would stack on ours. Self-hosted,
    so billed as free and named apart from cloud models."""

    llm = VLLMLLM(model="Qwen/Qwen3-8B-AWQ", base_url="http://localhost:8100/v1")
    chat = llm._chat_model(30.0)

    assert chat.model_kwargs["response_format"] == {"type": "json_object"}
    assert chat.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert chat.max_retries == 0
    assert llm.model_name == "vllm/Qwen/Qwen3-8B-AWQ"
    assert llm.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS


def test_all_vllm_providers_open_no_connections(monkeypatch, reload_models):
    """models.py builds its clients at import time, so pointing every capability at
    a vLLM server that is not running must still boot."""

    import socket

    monkeypatch.setattr(settings, "embedding_provider", "vllm")
    monkeypatch.setattr(settings, "reranker_provider", "vllm")

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    reload_models().chat._chat_model(30.0)

    assert opened == []


# --- OpenAILLM ---------------------------------------------------------------


def test_openai_client_authenticates_with_its_api_key(monkeypatch):
    monkeypatch.setattr(settings, "cloud_api_key", "secret")
    monkeypatch.setattr(settings, "cloud_base_url", None)
    chat = OpenAILLM()._chat_model(30.0)
    assert chat.openai_api_key.get_secret_value() == "secret"
