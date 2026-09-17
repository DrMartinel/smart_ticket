"""
Factory tests. These are about failure modes at startup, not about which
provider is "right" — the point is that a misconfiguration is loud.
"""

from __future__ import annotations

import pytest

from ai_engine.core.config import settings
from ai_engine.core.llm.models import (
    ANTHROPIC_COST_PER_1K_TOKENS,
    OLLAMA_COST_PER_1K_TOKENS,
    AnthropicChatModelFactory,
    GeminiChatModelFactory,
    OllamaChatModelFactory,
    OpenAIChatModelFactory,
)
from ai_engine.core.providers import factory as factory_mod
from ai_engine.core.db.client import SqlAlchemySessionSource
from ai_engine.core.providers.embeddings import OllamaEmbedder, StubEmbedder
from ai_engine.core.providers.factory import build_providers
from ai_engine.core.providers.reranker import CrossEncoderReranker, LexicalReranker


def _stub_cross_encoder(monkeypatch):
    """Make the cross-encoder constructible without the multi-GB checkpoint,
    which CI runners don't have.
    """

    monkeypatch.setattr(factory_mod, "_load_cross_encoder", object)


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


def test_default_reranker_is_lexical_and_switching_needs_only_the_env_var():
    """Pins the shipped default, and that `RERANKER_PROVIDER=cross_encoder`
    plus a restart reaches the cross-encoder without a rebuild.

    Does NOT assert calibration: `retrieval.floor` is a cross-encoder
    number (ADR-0005) — see docs/TODO.md item 4.
    """

    assert settings.reranker_provider == "lexical"
    assert isinstance(build_providers().reranker, LexicalReranker)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(settings, "reranker_provider", "cross_encoder")
        monkey.setattr(factory_mod, "_load_cross_encoder", object)
        assert isinstance(build_providers().reranker, CrossEncoderReranker)
    finally:
        monkey.undo()


def test_build_providers_opens_no_connections(monkeypatch):
    """main.py calls build_providers() at import time, and test_build.py
    imports main.py with no database. A constructor that opens a socket
    breaks both. Loading reranker weights is the one exception: a local
    read, not a connection.
    """

    monkeypatch.setattr(settings, "reranker_provider", "lexical")
    providers = build_providers()

    assert isinstance(providers.reranker, LexicalReranker)
    assert isinstance(providers.db, SqlAlchemySessionSource)  # constructed, not connected


def test_cross_encoder_selection_loads_the_model_at_startup(monkeypatch):
    """Selecting the cross-encoder loads its weights in build_providers(),
    not on the first score().

    Per-request loading would cost seconds per cold request and let
    concurrent requests build their own copies. The image bakes the
    weights (HF_HUB_OFFLINE=1), so this is a local read; a broken cache
    fails the boot, intended since lexical is no correct fallback
    (ADR-0005).
    """

    loaded = []
    sentinel = object()

    monkeypatch.setattr(factory_mod, "_load_cross_encoder", lambda: (loaded.append(1), sentinel)[1])
    monkeypatch.setattr(settings, "reranker_provider", "cross_encoder")

    providers = build_providers()

    assert isinstance(providers.reranker, CrossEncoderReranker)
    assert loaded == [1]  # before any request, not on first score()
    assert providers.reranker._model is sentinel


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("stub", StubEmbedder), ("ollama", OllamaEmbedder)],
)
def test_embedding_provider_selection(provider, expected, monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", provider)
    assert isinstance(build_providers().embedder, expected)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("lexical", LexicalReranker), ("cross_encoder", CrossEncoderReranker)],
)
def test_reranker_provider_selection(provider, expected, monkeypatch):
    _stub_cross_encoder(monkeypatch)
    monkeypatch.setattr(settings, "reranker_provider", provider)
    assert isinstance(build_providers().reranker, expected)


# --- LLM chain wiring (ADR-0007) -------------------------------------------
#
# Provider selection for the LLM moved out of DefaultLLMClient (which re-read
# settings on every call) into build_providers(), so these are startup tests
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


def test_no_cloud_configured_gives_ollama_primary_and_no_fallback(monkeypatch, lexical_reranker):
    """The default in this environment. There is no second link to fall back
    to, so the chain is Ollama plus its retry."""

    _unconfigure_cloud(monkeypatch)
    llm = build_providers().llm

    assert isinstance(llm._primary, OllamaChatModelFactory)
    assert llm._fallback is None


@pytest.mark.parametrize(
    ("provider", "base_url", "expected"),
    [
        ("openai", "https://cloud.example", OpenAIChatModelFactory),
        ("anthropic", None, AnthropicChatModelFactory),
        ("gemini", None, GeminiChatModelFactory),
    ],
)
def test_each_cloud_provider_becomes_primary_with_ollama_behind_it(
    provider, base_url, expected, monkeypatch, lexical_reranker
):
    """Whichever cloud provider is selected, Ollama stays the fallback link —
    spec §10.3. A cloud primary with nothing behind it would turn a provider
    outage into an all_llm_down degrade for every ticket."""

    monkeypatch.setattr(settings, "cloud_provider", provider)
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", base_url)

    llm = build_providers().llm

    assert isinstance(llm._primary, expected)
    assert isinstance(llm._fallback, OllamaChatModelFactory)


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

    assert isinstance(build_providers().llm._primary, AnthropicChatModelFactory)


def test_base_url_without_an_api_key_is_fatal_rather_than_silently_ollama_only(
    monkeypatch, lexical_reranker
):
    """An endpoint without a key must fail the boot, not silently run
    Ollama-only while the operator believes a cloud primary is in place.
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
    llm._primary(30.0)
    llm._fallback(30.0)

    assert opened == []


@pytest.mark.parametrize(
    ("factory", "attr", "expected"),
    [
        (
            lambda: OllamaChatModelFactory(
                model="qwen3.5:9b", base_url="http://localhost:11434", connect_timeout=3.0
            ),
            "format",
            "json",
        ),
        (
            lambda: GeminiChatModelFactory(
                model="gemini-2.5-pro", api_key="k", max_output_tokens=4096
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

    assert getattr(factory()(30.0), attr) == expected


def test_no_cloud_sdk_retries_on_top_of_ours(lexical_reranker):
    """Both first-party SDKs retry internally (2 for Anthropic, 6 for
    Gemini). Left on, one complete() could send a dozen requests, blow the
    latency budget and register a single breaker failure. Retry lives only
    in client.py.
    """

    anthropic = AnthropicChatModelFactory(
        model="claude-sonnet-5", api_key="k", max_output_tokens=4096, base_url=None
    )(30.0)
    gemini = GeminiChatModelFactory(model="gemini-2.5-pro", api_key="k", max_output_tokens=4096)(
        30.0
    )

    assert anthropic.max_retries == 0
    assert gemini.max_retries == 0


def test_flat_timeout_providers_still_bound_the_call(lexical_reranker):
    """The first-party SDKs can't express the connect/read split (ADR-0007)
    but must still carry the per-attempt read budget; unset, a hung
    request outlives the ticket.
    """

    anthropic = AnthropicChatModelFactory(
        model="claude-sonnet-5", api_key="k", max_output_tokens=4096, base_url=None
    )(45.0)
    gemini = GeminiChatModelFactory(model="gemini-2.5-pro", api_key="k", max_output_tokens=4096)(
        45.0
    )

    assert anthropic.default_request_timeout == 45.0
    assert gemini.timeout == 45.0


def test_chat_models_are_cached_per_timeout_bucket(lexical_reranker):
    """Construction costs ~260ms, which is why models are cached rather than
    built per attempt. Buckets floor to whole seconds so a bucket can never
    exceed the budget it came from."""

    factory = OllamaChatModelFactory(
        model="qwen3.5:9b", base_url="http://localhost:11434", connect_timeout=3.0
    )

    assert factory(30.0) is factory(30.4), "same bucket must reuse the model"
    assert factory(30.0) is not factory(31.0), "a different budget needs its own client"


def test_factory_attributes_are_resolved_at_construction(lexical_reranker):
    """`model_name` and `cost_per_1k_tokens` are resolved in __init__, not
    lazily. They feed `ai_runs.model_used` / `cost_usd` whether or not the
    call succeeds, and reading them must not build a chat model — which
    keeps `build_providers()` socket-free.
    """

    ollama = OllamaChatModelFactory(
        model="qwen3.5:9b", base_url="http://localhost:11434", connect_timeout=3.0
    )
    anthropic = AnthropicChatModelFactory(
        model="claude-sonnet-5", api_key="k", max_output_tokens=4096, base_url=None
    )

    assert ollama.model_name == "ollama/qwen3.5:9b"
    assert ollama.cost_per_1k_tokens == OLLAMA_COST_PER_1K_TOKENS
    assert anthropic.model_name == "claude-sonnet-5"
    assert anthropic.cost_per_1k_tokens == ANTHROPIC_COST_PER_1K_TOKENS
    assert ollama._cache == {} and anthropic._cache == {}, (
        "reading an attribute must not build a model"
    )


def test_cloud_factory_is_none_without_an_api_key(monkeypatch, lexical_reranker):
    """No API key means no cloud link, so build_providers makes a single-link
    chain rather than a fallback that can never fire.
    """

    monkeypatch.setattr(settings, "cloud_api_key", None)
    monkeypatch.setattr(settings, "cloud_base_url", None)

    assert factory_mod._build_cloud_factory() is None
