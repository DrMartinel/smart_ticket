"""
Provider-class tests. That constructing the cross-encoder imports nothing
is pinned in test_providers_factory.py, through build_providers.
"""

from __future__ import annotations

import threading

import pytest

from ai_engine.core.config import settings
from ai_engine.core.llm.base import LLMClient
from ai_engine.core.providers.base import Embedder, Reranker
from ai_engine.core.providers.embeddings import EMBED_DIM, OllamaEmbedder, StubEmbedder
from ai_engine.core.providers.reranker import CrossEncoderReranker, LexicalReranker


def _fake_model():
    class _Model:
        def predict(self, pairs):
            return [0.0] * len(pairs)

    return _Model()


def test_cross_encoder_builds_its_model_exactly_once_at_construction():
    """The model loads in __init__, so scoring — concurrently or not — must
    never build another one.

    This used to be a lazy load guarded by a lock, because `analyze` in
    main.py is a sync def and FastAPI serves concurrent requests from a
    threadpool against one shared reranker: each racing cold request built
    its own multi-GB CrossEncoder, multiplying peak RAM into an OOM kill.
    Constructing eagerly removes the race by construction rather than by
    locking. The threads below are kept so that reintroducing a lazy load
    without a lock fails here instead of in production.
    """

    model = _fake_model()
    reranker = CrossEncoderReranker(model=model)
    assert reranker._model is model  # handed in built; nothing to load, ever

    barrier = threading.Barrier(8)

    def race():
        barrier.wait()
        reranker.score("q", ["p"])

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert reranker._model is model


def test_cross_encoder_empty_passages_scores_nothing():
    """Refuse-before-LLM and budget-exhausted paths reach the reranker with
    nothing to score, and must get an empty list rather than an error or a
    call into the model.

    This test previously also asserted that an empty passage list paid no
    model load. That is no longer meaningful — the load happens in __init__,
    deliberately (see CrossEncoderReranker's docstring) — but the empty-input
    contract it also covered is still worth pinning.
    """

    class _ExplodingModel:
        def predict(self, pairs):
            raise AssertionError("predict must not be called for an empty passage list")

    reranker = CrossEncoderReranker(model=_ExplodingModel())
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


@pytest.mark.parametrize("returned_dim", [0, 768, EMBED_DIM - 1])
def test_ollama_embedder_rejects_a_wrong_width_vector(returned_dim, monkeypatch):
    """EMBED_DIM is the pgvector column width, and langchain-ollama has no
    opinion about it — so this check has to live on our side of the seam.

    A short vector does not fail where it is produced. It travels into
    retrieval and surfaces either as a pgvector dimension error far from the
    cause, or (worse, with a zero-length result) as an ordinary "the KB has
    nothing relevant" refuse-before-LLM. That reports a provider outage to the
    reviewer as a confident finding about the knowledge base.
    """

    class _WrongWidthClient:
        def embed_query(self, _text):
            return [0.1] * returned_dim

    embedder = OllamaEmbedder()
    monkeypatch.setattr(embedder, "_embeddings", _WrongWidthClient())

    with pytest.raises(ValueError, match=f"expected {EMBED_DIM}"):
        embedder.embed("không đăng nhập được")


def test_ollama_embedder_construction_opens_no_socket(monkeypatch):
    """build_providers() constructs this at uvicorn import time and in tests
    with no Ollama reachable. langchain-ollama would do a round trip here if
    `validate_model_on_init` were ever turned on."""

    import socket

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    OllamaEmbedder()
    assert opened == []


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


@pytest.mark.parametrize("seam", [Embedder, Reranker, LLMClient])
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

    from ai_engine.core.providers import factory as factory_mod
    from ai_engine.core.providers.factory import build_providers

    # CI has the dependency but not the ~2.3GB checkpoint, and
    # CrossEncoderReranker loads its model in __init__. This test is about the
    # seam check, not about model loading, so it stubs the loader — the loading
    # behaviour itself is pinned in test_providers_factory.py.
    monkeypatch.setattr(factory_mod, "_load_cross_encoder", object)
    monkeypatch.setattr(settings, "embedding_provider", embedding_provider)
    monkeypatch.setattr(settings, "reranker_provider", reranker_provider)
    providers = build_providers()

    assert isinstance(providers.embedder, Embedder)
    assert isinstance(providers.reranker, Reranker)
    assert isinstance(providers.llm, LLMClient)
