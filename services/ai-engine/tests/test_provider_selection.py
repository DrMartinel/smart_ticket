"""
Provider selection tests. These are about failure modes at startup, not about which
provider is "right" — the point is that a misconfiguration is loud.
"""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from ai_engine.core.config import Settings, settings
from ai_engine.core.providers.clients import (
    OPENAI_COST_PER_1K_TOKENS,
    VLLM_COST_PER_1K_TOKENS,
    openai_chat,
    vllm_chat,
)
from ai_engine.core.db import client as db_client
from ai_engine.core.db.client import SqlAlchemySessionSource


def test_unknown_reranker_provider_raises_rather_than_falling_back_to_lexical(
    monkeypatch, reload_shortlister
):
    """A typo'd SHORTLIST_PROVIDER must not fall back to lexical — a different
    calibration from the one `retrieval.floor` is fitted against
    (ADR-0005). The refuse-before-LLM rate would be wrong with everything
    green.
    """

    monkeypatch.setattr(settings, "shortlist_provider", "cross-encoder")
    with pytest.raises(ValueError, match="unknown shortlist_provider"):
        reload_shortlister()


def test_unknown_embedding_provider_raises(monkeypatch, reload_embeddings):
    """Same failure shape as above: silently embedding with the wrong
    provider produces plausible-looking vectors and quietly bad recall."""

    monkeypatch.setattr(settings, "embedding_provider", "stubb")
    with pytest.raises(ValueError, match="unknown embedding_provider"):
        reload_embeddings()


def test_default_reranker_is_the_vllm_cross_encoder(env_template, monkeypatch, reload_shortlister):
    """Pins the shipped default: the cross-encoder `retrieval.floor` is
    specified against (ADR-0005), served by vLLM (ADR-0009). `lexical` is for
    CI and must be selected explicitly.

    Reads the template, `.env.example`, not the `settings` instance: CI
    exports SHORTLIST_PROVIDER=lexical, so the instance reflects the job's
    env.

    Does NOT assert calibration — see docs/TODO.md item 4.
    """

    default = env_template["SHORTLIST_PROVIDER"]
    assert default == "vllm"
    monkeypatch.setattr(settings, "shortlist_provider", default)
    m = reload_shortlister()
    assert type(m.shortlister) is m.CrossEncoderShortlister


def test_building_providers_opens_no_connections(monkeypatch, reload_shortlister):
    """graph/build.py imports the modules that build the providers, and
    test_build.py imports it with no database. A constructor that opens a socket breaks
    both.
    """

    monkeypatch.setattr(settings, "shortlist_provider", "lexical")
    m = reload_shortlister()

    assert isinstance(m.shortlister, m.LexicalShortlister)
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
    [("lexical", "LexicalShortlister"), ("vllm", "CrossEncoderShortlister")],
)
def test_reranker_provider_selection(provider, expected, monkeypatch, reload_shortlister):
    monkeypatch.setattr(settings, "shortlist_provider", provider)
    m = reload_shortlister()
    assert type(m.shortlister) is getattr(m, expected)


def test_each_vllm_client_is_built_from_config_for_its_own_server(monkeypatch, reload_clients):
    """vLLM serves one model per server, so chat, embeddings and reranking
    each have their own client — built from config, pointing at their own
    base URL."""

    monkeypatch.setattr(settings, "chat_client_provider", "vllm")
    m = reload_clients()

    assert m.embed.base_url == settings.embed_base_url
    assert m.rerank.base_url == settings.rerank_base_url
    assert str(m.chat.chat_model.root_client.base_url).rstrip("/") == (
        settings.chat_base_url.rstrip("/")
    )
    assert m.chat.model == settings.chat_model


# --- LLM chain wiring (ADR-0007) -------------------------------------------
#
# Provider selection for the LLM happens once, when clients.py is imported, so
# these are startup tests like the ones above: the point is that a
# misconfiguration is loud.


@pytest.fixture
def cloud_key(monkeypatch):
    """openai_chat refuses to build without a key and a model."""

    monkeypatch.setattr(settings, "cloud_api_key", "k")
    monkeypatch.setattr(settings, "cloud_model", "test-model")
    monkeypatch.setattr(settings, "cloud_base_url", None)


def _chat_on(monkeypatch, provider, cloud_base_url=None):
    monkeypatch.setattr(settings, "chat_client_provider", provider)
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_model", "test-model")
    monkeypatch.setattr(settings, "cloud_base_url", cloud_base_url)


def test_default_chat_runs_on_vllm(env_template, monkeypatch, reload_clients):
    """Reads the template, not the `settings` instance, which reflects the
    job's env."""
    default = env_template["CHAT_CLIENT_PROVIDER"]
    assert default == "vllm"
    _chat_on(monkeypatch, default)
    m = reload_clients()
    assert m.chat.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS


@pytest.mark.parametrize(
    ("provider", "model", "cost"),
    [
        ("vllm", lambda: settings.chat_model, VLLM_COST_PER_1K_TOKENS),
        ("openai", lambda: "test-model", OPENAI_COST_PER_1K_TOKENS),
    ],
)
def test_chat_client_provider_selects_the_chat_model(
    provider, model, cost, monkeypatch, reload_clients
):
    _chat_on(monkeypatch, provider)
    m = reload_clients()

    assert (m.chat.model, m.chat.cost_per_1k_tokens) == (model(), cost)


@pytest.mark.parametrize("removed", ["anthropic", "gemini", "vLLM"])
def test_unknown_chat_provider_is_rejected_by_settings(removed):
    """A typo — or a provider that no longer exists — must fail the boot,
    not quietly select some default."""

    with pytest.raises(ValidationError):
        Settings(chat_client_provider=removed)


def test_openai_accepts_an_optional_base_url(monkeypatch, reload_clients):
    """CLOUD_BASE_URL is a proxy setting, and it must actually be used."""

    _chat_on(monkeypatch, "openai", "https://proxy.example")
    m = reload_clients()

    assert str(m.chat.chat_model.root_client.base_url).startswith("https://proxy.example")


@pytest.mark.parametrize("missing", ["cloud_api_key", "cloud_model"])
def test_openai_without_its_key_or_model_is_fatal(missing, monkeypatch, reload_clients):
    """Either one missing must fail the boot, not every ticket."""

    _chat_on(monkeypatch, "openai")
    monkeypatch.setattr(settings, missing, None)

    with pytest.raises(ValueError, match=f"requires {missing.upper()}"):
        reload_clients()


def test_building_the_openai_chat_model_opens_no_connections(monkeypatch, reload_clients):
    """clients.py builds its clients at import time, so constructing a chat
    model must configure an HTTP client, not use one."""

    import socket

    _chat_on(monkeypatch, "openai")

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    reload_clients()

    assert opened == []


def test_openai_asks_for_json_without_sdk_retries_and_capped_output(cloud_key):
    """infer.py does `json.loads(result.text)`: a lost JSON flag fails quietly,
    as every ticket degrading to HITL. The SDK retries internally unless told
    not to, and this system does not retry. The output cap stops a runaway
    generation from running until the read timeout."""

    chat = openai_chat().chat_model
    assert isinstance(chat, ChatOpenAI)

    assert chat.model_kwargs["response_format"] == {"type": "json_object"}
    assert chat.max_retries == 0
    assert chat.max_tokens == settings.cloud_max_output_tokens


def test_provider_attributes_are_resolved_at_construction(cloud_key):
    """`model` and `cost_per_1k_tokens` are resolved in __init__, not
    lazily. They feed `ai_runs.model_used` / `cost_usd` whether or not the
    call succeeds.
    """

    vllm = vllm_chat(model="Qwen/Qwen3-8B-AWQ", base_url="http://localhost:8100/v1")
    openai = openai_chat()

    assert vllm.model == "Qwen/Qwen3-8B-AWQ"
    assert vllm.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS
    assert openai.model == "test-model"
    assert openai.cost_per_1k_tokens == OPENAI_COST_PER_1K_TOKENS


# --- Self-hosted LLM (ADR-0009) --------------------------------------------


def test_vllm_llm_asks_for_json_without_thinking_or_sdk_retries():
    """JSON mode keeps `json.loads` in infer.py working; a thinking trace
    would add minutes of latency; SDK retries would silently retry. Self-hosted,
    so billed as free."""

    llm = vllm_chat(model="Qwen/Qwen3-8B-AWQ", base_url="http://localhost:8100/v1")
    chat = llm.chat_model
    assert isinstance(chat, ChatOpenAI)

    assert chat.model_kwargs["response_format"] == {"type": "json_object"}
    assert chat.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert chat.max_retries == 0
    assert llm.model == "Qwen/Qwen3-8B-AWQ"
    assert llm.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS


def test_all_vllm_providers_open_no_connections(monkeypatch, reload_clients):
    """clients.py builds its clients at import time, so pointing every capability at
    a vLLM server that is not running must still boot."""

    import socket

    monkeypatch.setattr(settings, "embedding_provider", "vllm")
    monkeypatch.setattr(settings, "shortlist_provider", "vllm")

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    reload_clients()

    assert opened == []


# --- openai_chat ---------------------------------------------------------------


def test_openai_client_authenticates_with_its_api_key(cloud_key, monkeypatch):
    monkeypatch.setattr(settings, "cloud_api_key", "secret")
    chat = openai_chat().chat_model
    assert isinstance(chat, ChatOpenAI)
    assert isinstance(chat.openai_api_key, SecretStr)
    assert chat.openai_api_key.get_secret_value() == "secret"
