"""
Factory tests. These are about failure modes at startup, not about which
provider is "right" — the point is that a misconfiguration is loud.
"""

from __future__ import annotations

import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.llm.models import (
    ANTHROPIC_COST_PER_1K_TOKENS,
    VLLM_COST_PER_1K_TOKENS,
    AnthropicLLM,
    GeminiLLM,
    OpenAILLM,
    VLLMLLM,
)
from ai_engine.core.providers import factory as factory_mod
from ai_engine.core.db.client import SqlAlchemySessionSource
from ai_engine.core.providers.embeddings import StubEmbedder, VLLMEmbedder
from ai_engine.core.providers.factory import build_providers
from ai_engine.core.providers.reranker import (
    LexicalReranker,
    VLLMReranker,
)


def test_unknown_reranker_provider_raises_rather_than_falling_back_to_lexical(monkeypatch):
    """A typo'd RERANKER_PROVIDER must not fall back to lexical — a different
    calibration from the one `retrieval.floor` is fitted against
    (ADR-0005). The refuse-before-LLM rate would be wrong with everything
    green.
    """

    monkeypatch.setattr(settings, "reranker_provider", "cross-encoder")
    with pytest.raises(ValueError, match="unknown reranker_provider"):
        build_providers()


def test_unknown_embedding_provider_raises(monkeypatch):
    """Same failure shape as above: silently embedding with the wrong
    provider produces plausible-looking vectors and quietly bad recall."""

    monkeypatch.setattr(settings, "embedding_provider", "stubb")
    with pytest.raises(ValueError, match="unknown embedding_provider"):
        build_providers()


def test_default_reranker_is_the_vllm_cross_encoder():
    """Pins the shipped default: the cross-encoder `retrieval.floor` is
    specified against (ADR-0005), served by vLLM (ADR-0009). `lexical` is for
    CI and must be selected explicitly.

    Does NOT assert calibration — see docs/TODO.md item 4.
    """

    assert settings.reranker_provider == "vllm"
    assert isinstance(build_providers().reranker, VLLMReranker)


def test_build_providers_opens_no_connections(monkeypatch):
    """main.py calls build_providers() at import time, and test_build.py
    imports main.py with no database. A constructor that opens a socket
    breaks both.
    """

    monkeypatch.setattr(settings, "reranker_provider", "lexical")
    providers = build_providers()

    assert isinstance(providers.reranker, LexicalReranker)
    assert isinstance(providers.db, SqlAlchemySessionSource)  # constructed, not connected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("stub", StubEmbedder), ("vllm", VLLMEmbedder)],
)
def test_embedding_provider_selection(provider, expected, monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", provider)
    assert isinstance(build_providers().embedder, expected)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("lexical", LexicalReranker), ("vllm", VLLMReranker)],
)
def test_reranker_provider_selection(provider, expected, monkeypatch):
    monkeypatch.setattr(settings, "reranker_provider", provider)
    assert isinstance(build_providers().reranker, expected)


# --- LLM chain wiring (ADR-0007) -------------------------------------------
#
# Provider selection for the LLM happens once, in build_providers(), so these are startup tests
# like the ones above: the point is that a misconfiguration is loud.


@pytest.fixture
def lexical_reranker(monkeypatch):
    """Pin the reranker to lexical for LLM-chain tests that go through
    `build_providers()`, so they don't load a model they never use.

    Not autouse: that would change what the default-configuration test
    asserts.
    """

    monkeypatch.setattr(settings, "reranker_provider", "lexical")


def _unconfigure_cloud(monkeypatch):
    monkeypatch.setattr(settings, "cloud_api_key", None)
    monkeypatch.setattr(settings, "cloud_base_url", None)


def test_no_cloud_configured_gives_vllm_primary_and_no_fallback(monkeypatch, lexical_reranker):
    """The default in this environment. There is no second link to fall back
    to, so the chain is self-hosted vLLM plus its retry."""

    _unconfigure_cloud(monkeypatch)
    llm = build_providers().llm

    assert isinstance(llm, VLLMLLM)
    assert llm._fallback is None


@pytest.mark.parametrize(
    ("provider", "base_url", "expected"),
    [
        ("openai", "https://cloud.example", OpenAILLM),
        ("anthropic", None, AnthropicLLM),
        ("gemini", None, GeminiLLM),
    ],
)
def test_each_cloud_provider_becomes_primary_with_vllm_behind_it(
    provider, base_url, expected, monkeypatch, lexical_reranker
):
    """Whichever cloud provider is selected, self-hosted vLLM stays the
    fallback link —
    spec §10.3. A cloud primary with nothing behind it would turn a provider
    outage into an all_llm_down degrade for every ticket."""

    monkeypatch.setattr(settings, "cloud_provider", provider)
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", base_url)

    llm = build_providers().llm

    assert isinstance(llm, expected)
    assert isinstance(llm._fallback, VLLMLLM)
    assert llm._fallback._fallback is None


def test_unknown_cloud_provider_raises(monkeypatch, lexical_reranker):
    """Same failure shape as the embedding/reranker provider settings above:
    a typo must not quietly select some default."""

    monkeypatch.setattr(settings, "cloud_provider", "claude")
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    with pytest.raises(ValueError, match="unknown cloud_provider"):
        build_providers()


def test_openai_provider_without_base_url_is_fatal(monkeypatch, lexical_reranker):
    """'openai' means "some OpenAI-compatible gateway" and has no default
    address, unlike the two first-party APIs."""

    monkeypatch.setattr(settings, "cloud_provider", "openai")
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", None)
    with pytest.raises(ValueError, match="requires CLOUD_BASE_URL"):
        build_providers()


def test_gemini_with_a_base_url_is_fatal_rather_than_silently_ignoring_it(
    monkeypatch, lexical_reranker
):
    """ChatGoogleGenerativeAI has no endpoint override, so a CLOUD_BASE_URL
    set alongside it would be dropped on the floor while the operator believed
    traffic was being routed through their gateway."""

    monkeypatch.setattr(settings, "cloud_provider", "gemini")
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", "https://proxy.example")
    with pytest.raises(ValueError, match="does not support CLOUD_BASE_URL"):
        build_providers()


def test_anthropic_accepts_an_optional_base_url(monkeypatch, lexical_reranker):
    """Unlike gemini, the Anthropic client does take an endpoint override, so
    a base_url here is a proxy setting rather than a misconfiguration."""

    monkeypatch.setattr(settings, "cloud_provider", "anthropic")
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", "https://proxy.example")

    assert isinstance(build_providers().llm, AnthropicLLM)


def test_base_url_without_an_api_key_is_fatal_rather_than_silently_self_hosted_only(
    monkeypatch, lexical_reranker
):
    """An endpoint without a key must fail the boot, not silently run
    self-hosted only while the operator believes a cloud primary is in place.
    """

    monkeypatch.setattr(settings, "cloud_api_key", None)
    monkeypatch.setattr(settings, "cloud_base_url", "https://cloud.example")

    with pytest.raises(ValueError, match="CLOUD_API_KEY"):
        build_providers()


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [("openai", "https://cloud.example"), ("anthropic", None), ("gemini", None)],
)
def test_building_chat_models_opens_no_connections(
    provider, base_url, monkeypatch, lexical_reranker
):
    """build_providers() runs at import time, so constructing a chat model
    must configure an HTTP client, not use one. Pinned per provider
    because the first-party SDKs build their transports eagerly.
    """

    import socket

    monkeypatch.setattr(settings, "cloud_provider", provider)
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", base_url)

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    llm = build_providers().llm
    # Force the lazily-built models into existence too — the cache means
    # construction is deferred until the first call with a given timeout.
    llm._chat_model(30.0)
    llm._fallback._chat_model(30.0)

    assert opened == []


@pytest.mark.parametrize(
    ("factory", "attr", "expected"),
    [
        (
            lambda: GeminiLLM(
                model="gemini-2.5-pro", api_key="k", max_output_tokens=4096, fallback=None
            ),
            "response_mime_type",
            "application/json",
        ),
    ],
)
def test_providers_with_a_json_mode_actually_set_it(factory, attr, expected, lexical_reranker):
    """infer.py does `json.loads(result.text)`. A lost JSON flag fails
    quietly: the model wraps its object in prose and every ticket degrades
    to HITL as if it were the model's fault. Anthropic has no JSON mode
    (ADR-0007).
    """

    assert getattr(factory()._chat_model(30.0), attr) == expected


def test_no_cloud_sdk_retries_on_top_of_ours(lexical_reranker):
    """Both first-party SDKs retry internally (2 for Anthropic, 6 for
    Gemini). Left on, one complete() could send a dozen requests, blow the
    latency budget and register a single breaker failure. Retry lives only
    in client.py.
    """

    anthropic = AnthropicLLM(
        model="claude-sonnet-5", api_key="k", max_output_tokens=4096, base_url=None, fallback=None
    )._chat_model(30.0)
    gemini = GeminiLLM(
        model="gemini-2.5-pro", api_key="k", max_output_tokens=4096, fallback=None
    )._chat_model(30.0)

    assert anthropic.max_retries == 0
    assert gemini.max_retries == 0


def test_flat_timeout_providers_still_bound_the_call(lexical_reranker):
    """The first-party SDKs can't express the connect/read split (ADR-0007)
    but must still carry the per-attempt read budget; unset, a hung
    request outlives the ticket.
    """

    anthropic = AnthropicLLM(
        model="claude-sonnet-5", api_key="k", max_output_tokens=4096, base_url=None, fallback=None
    )._chat_model(45.0)
    gemini = GeminiLLM(
        model="gemini-2.5-pro", api_key="k", max_output_tokens=4096, fallback=None
    )._chat_model(45.0)

    assert anthropic.default_request_timeout == 45.0
    assert gemini.timeout == 45.0


def test_chat_models_are_cached_per_timeout_bucket(lexical_reranker):
    """Construction costs ~260ms, which is why models are cached rather than
    built per attempt. Buckets floor to whole seconds so a bucket can never
    exceed the budget it came from."""

    llm = VLLMLLM(
        model="Qwen/Qwen3-8B-AWQ",
        base_url="http://localhost:8100/v1",
        connect_timeout=3.0,
        fallback=None,
    )

    assert llm._chat_model(30.0) is llm._chat_model(30.4), "same bucket must reuse the model"
    assert llm._chat_model(30.0) is not llm._chat_model(31.0), (
        "a different budget needs its own client"
    )


def test_provider_attributes_are_resolved_at_construction(lexical_reranker):
    """`model_name` and `cost_per_1k_tokens` are resolved in __init__, not
    lazily. They feed `ai_runs.model_used` / `cost_usd` whether or not the
    call succeeds, and reading them must not build a chat model — which
    keeps `build_providers()` socket-free.
    """

    vllm = VLLMLLM(
        model="Qwen/Qwen3-8B-AWQ",
        base_url="http://localhost:8100/v1",
        connect_timeout=3.0,
        fallback=None,
    )
    anthropic = AnthropicLLM(
        model="claude-sonnet-5", api_key="k", max_output_tokens=4096, base_url=None, fallback=None
    )

    assert vllm.model_name == "vllm/Qwen/Qwen3-8B-AWQ"
    assert vllm.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS
    assert anthropic.model_name == "claude-sonnet-5"
    assert anthropic.cost_per_1k_tokens == ANTHROPIC_COST_PER_1K_TOKENS
    assert vllm._cache == {} and anthropic._cache == {}, (
        "reading an attribute must not build a model"
    )


def test_cloud_llm_is_none_without_an_api_key(monkeypatch, lexical_reranker):
    """No API key means no cloud link, so build_providers makes a single-link
    chain rather than a fallback that can never fire.
    """

    monkeypatch.setattr(settings, "cloud_api_key", None)
    monkeypatch.setattr(settings, "cloud_base_url", None)

    assert factory_mod._build_cloud_llm(fallback=None) is None


# --- Self-hosted LLM (ADR-0009) --------------------------------------------


def test_vllm_llm_asks_for_json_without_thinking_or_sdk_retries(lexical_reranker):
    """JSON mode keeps `json.loads` in infer.py working; a thinking trace
    would blow the latency budget; SDK retries would stack on ours. Self-hosted,
    so billed as free and named apart from cloud models."""

    llm = VLLMLLM(
        model="Qwen/Qwen3-8B-AWQ",
        base_url="http://localhost:8100/v1",
        connect_timeout=3.0,
        fallback=None,
    )
    chat = llm._chat_model(30.0)

    assert chat.model_kwargs["response_format"] == {"type": "json_object"}
    assert chat.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert chat.max_retries == 0
    assert llm.model_name == "vllm/Qwen/Qwen3-8B-AWQ"
    assert llm.cost_per_1k_tokens == VLLM_COST_PER_1K_TOKENS


def test_all_vllm_providers_open_no_connections(monkeypatch, lexical_reranker):
    """build_providers() runs at import time, so pointing every capability at
    a vLLM server that is not running must still boot."""

    import socket

    _unconfigure_cloud(monkeypatch)
    monkeypatch.setattr(settings, "embedding_provider", "vllm")
    monkeypatch.setattr(settings, "reranker_provider", "vllm")

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    providers = build_providers()
    providers.llm._chat_model(30.0)

    assert opened == []
