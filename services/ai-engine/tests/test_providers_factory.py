"""
Factory tests. These are about failure modes at startup, not about which
provider is "right" — the point is that a misconfiguration is loud.
"""

from __future__ import annotations

import pytest

from ai_engine.config import settings
from ai_engine.providers.embeddings import OllamaEmbedder, StubEmbedder
from ai_engine.providers.factory import build_providers
from ai_engine.providers.reranker import CrossEncoderReranker, LexicalReranker


def test_unknown_reranker_provider_raises_rather_than_falling_back_to_lexical(monkeypatch):
    """A typo'd RERANKER_PROVIDER used to degrade silently to the lexical
    scorer. Lexical and cross-encoder scores are separate calibrations, and
    `retrieval.floor` is fitted against the cross-encoder distribution
    (ADR-0005) — so the refuse-before-LLM rate would be wrong while every
    log line and every test stayed green.
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


def test_build_providers_opens_no_connections_and_loads_no_models(monkeypatch):
    """main.py calls this at uvicorn import time, and test_build.py imports
    main.py with no database and no environment. If any
    constructor here starts doing I/O, both break — the first as a container
    that won't boot, the second as a test that needs Postgres.
    """

    import sys

    monkeypatch.setattr(settings, "reranker_provider", "cross_encoder")
    providers = build_providers()

    assert "sentence_transformers" not in sys.modules
    assert isinstance(providers.reranker, CrossEncoderReranker)


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
    monkeypatch.setattr(settings, "reranker_provider", provider)
    assert isinstance(build_providers().reranker, expected)
