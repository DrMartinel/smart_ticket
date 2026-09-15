"""
Provider-class tests. That constructing the cross-encoder imports nothing
is pinned in test_providers_factory.py, through build_providers.
"""

from __future__ import annotations

import threading

import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers import ConnectionSource, Embedder, LLMClient, Reranker
from ai_engine.providers.embeddings import EMBED_DIM, StubEmbedder
from ai_engine.providers.reranker import CrossEncoderReranker, LexicalReranker


def test_cross_encoder_model_is_built_once_under_concurrent_first_calls():
    """`analyze` in main.py is a sync def, so FastAPI serves concurrent
    requests from a threadpool against one shared reranker instance. Without
    the load lock each racing thread builds its own CrossEncoder, multiplying
    peak RAM by the number of cold requests for a multi-GB model.
    """

    loads: list[str] = []

    def slow_loader(model_name: str):
        loads.append(model_name)

        class _Model:
            def predict(self, pairs):
                return [0.0] * len(pairs)

        return _Model()

    reranker = CrossEncoderReranker(loader=slow_loader)
    barrier = threading.Barrier(8)

    def race():
        barrier.wait()
        reranker.score("q", ["p"])

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert loads == [settings.reranker_model]


def test_cross_encoder_empty_passages_loads_no_model():
    """Refuse-before-LLM and budget paths can reach the reranker with nothing
    to score. That must not pay a multi-second model load."""

    def exploding_loader(model_name: str):
        raise AssertionError("model must not be loaded for an empty passage list")

    reranker = CrossEncoderReranker(loader=exploding_loader)
    assert reranker.score("q", []) == []


def test_stub_embedder_is_deterministic_and_unit_norm():
    """The eval suite runs with EMBEDDING_PROVIDER=stub and compares
    retrieval results across runs; a non-deterministic stub would make every
    retrieval metric noise."""

    embedder = StubEmbedder()
    first = embedder.embed("không đăng nhập được")
    second = embedder.embed("không đăng nhập được")

    assert first == second
    assert len(first) == EMBED_DIM
    assert abs(sum(x * x for x in first) ** 0.5 - 1.0) < 1e-9
    assert first != embedder.embed("a different ticket")


def test_lexical_reranker_returns_one_score_per_passage_in_input_order():
    """The rerank node zips these scores against its candidate list
    positionally — a reordered or short return silently mislabels which
    chunk got which score, and the top-1 score is what `retrieval_floor`
    is compared against (ADR-0005)."""

    passages = ["đăng nhập thất bại", "máy in hỏng", "vpn chậm"]
    scores = LexicalReranker().score("không đăng nhập được", passages)

    assert len(scores) == len(passages)
    assert scores[0] == max(scores)


def test_lexical_reranker_empty_passages_returns_empty():
    assert LexicalReranker().score("q", []) == []


@pytest.mark.parametrize("seam", [Embedder, Reranker, LLMClient, ConnectionSource])
def test_provider_missing_its_method_cannot_be_constructed(seam):
    """The seams are ABCs because nothing type-checks this repo. A provider
    whose method is misnamed (say `rerank` instead of `score`) must fail when
    build_providers() constructs it at import time — a container that won't
    boot — not with an AttributeError on the first ticket that reaches it.
    """

    class Misnamed(seam):
        def misnamed(self):
            return None

    with pytest.raises(TypeError, match="abstract"):
        Misnamed()


@pytest.mark.parametrize(
    ("embedding_provider", "reranker_provider"),
    [("stub", "lexical"), ("ollama", "cross_encoder")],
)
def test_every_built_provider_subclasses_its_seam(
    embedding_provider, reranker_provider, monkeypatch
):
    """Only a subclass gets the construction-time check above; a provider
    added without inheriting from its seam would silently opt out of it."""

    from ai_engine.providers.factory import build_providers

    monkeypatch.setattr(settings, "embedding_provider", embedding_provider)
    monkeypatch.setattr(settings, "reranker_provider", reranker_provider)
    providers = build_providers()

    assert isinstance(providers.embedder, Embedder)
    assert isinstance(providers.reranker, Reranker)
    assert isinstance(providers.llm, LLMClient)
    assert isinstance(providers.db, ConnectionSource)
