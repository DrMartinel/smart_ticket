"""
Provider-class tests. Loading through build_providers is pinned in
test_providers_factory.py.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.base import Embedder, Reranker
from ai_engine.core.providers.llm.client import LLMClient
from ai_engine.core.providers.embeddings import (
    EMBED_DIM,
    StubEmbedder,
    VLLMEmbedder,
)
from ai_engine.core.providers.reranker import (
    LexicalReranker,
    VLLMReranker,
)


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
def test_vllm_embedder_rejects_a_wrong_width_vector(returned_dim, monkeypatch):
    """EMBED_DIM is the pgvector column width, which neither langchain client
    knows anything about, so the check lives on our side.

    A wrong-width vector fails far away as a pgvector error or — if empty
    — as an ordinary refuse-before-LLM, reporting a provider outage as a
    finding about the KB.
    """

    class _WrongWidthClient:
        def embed_query(self, _text):
            return [0.1] * returned_dim

    embedder = VLLMEmbedder()
    monkeypatch.setattr(embedder, "_embeddings", _WrongWidthClient())

    with pytest.raises(ValueError, match=f"expected {EMBED_DIM}"):
        embedder.embed("không đăng nhập được")


def test_vllm_embedder_construction_opens_no_socket(monkeypatch):
    """build_providers() constructs this at uvicorn import time and in tests
    with no vLLM server reachable."""

    import socket

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    VLLMEmbedder()
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
    """A provider with a misnamed method (`rerank` instead of `score`) must
    fail at construction — a container that won't boot — not on the first
    ticket.
    """

    class Misnamed(seam):
        def misnamed(self):
            return None

    with pytest.raises(TypeError, match="abstract"):
        Misnamed()


@pytest.mark.parametrize(
    ("embedding_provider", "reranker_provider"),
    [("stub", "lexical"), ("vllm", "vllm")],
)
def test_every_built_provider_subclasses_its_seam(
    embedding_provider, reranker_provider, monkeypatch
):
    """Only a subclass gets the construction-time check above; a provider
    added without inheriting from its seam would silently opt out of it."""

    from ai_engine.core.providers.factory import build_providers

    monkeypatch.setattr(settings, "embedding_provider", embedding_provider)
    monkeypatch.setattr(settings, "reranker_provider", reranker_provider)
    providers = build_providers()

    assert isinstance(providers.embedder, Embedder)
    assert isinstance(providers.reranker, Reranker)
    assert isinstance(providers.llm, LLMClient)


def _vllm_reranker(handler) -> VLLMReranker:
    reranker = VLLMReranker()
    reranker._client = httpx.Client(
        base_url=settings.vllm_rerank_base_url, transport=httpx.MockTransport(handler)
    )
    return reranker


def _rerank_reply(pairs):
    return {"results": [{"index": i, "relevance_score": s} for i, s in pairs]}


def test_vllm_reranker_returns_scores_in_input_order_not_rank_order():
    """vLLM sorts results by score. The rerank node zips scores against its
    candidates positionally, so they must come back in INPUT order."""

    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=_rerank_reply([(2, 0.9), (0, 0.4), (1, 0.1)]))

    scores = _vllm_reranker(handler).score("vpn down", ["a", "b", "c"])

    assert scores == [0.4, 0.1, 0.9]
    [(path, body)] = sent
    assert path == "/v1/rerank"
    assert body == {
        "model": settings.reranker_model,
        "query": "vpn down",
        "documents": ["a", "b", "c"],
    }


def test_vllm_reranker_empty_passages_sends_no_request():
    def handler(request):
        raise AssertionError("no request expected")

    assert _vllm_reranker(handler).score("q", []) == []


_UNUSABLE_RERANK_REPLIES = {
    "too few": _rerank_reply([(0, 0.5)]),
    "duplicate index": _rerank_reply([(0, 0.5), (0, 0.4)]),
    "index out of range": _rerank_reply([(0, 0.5), (2, 0.4)]),
    "missing score": {"results": [{"index": 0}, {"index": 1}]},
    "no results": {"data": []},
}


@pytest.mark.parametrize(
    "body", _UNUSABLE_RERANK_REPLIES.values(), ids=_UNUSABLE_RERANK_REPLIES.keys()
)
def test_vllm_reranker_raises_on_an_unusable_reply(body):
    """A short or misindexed result list would attach relevance to the wrong
    chunk while the ranking still looks plausible."""

    reranker = _vllm_reranker(lambda request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        reranker.score("q", ["a", "b"])


def test_vllm_reranker_raises_on_a_server_error():
    """No fallback to lexical: a different calibration (ADR-0005). The ticket
    degrades to HITL instead."""

    reranker = _vllm_reranker(lambda request: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        reranker.score("q", ["a"])
