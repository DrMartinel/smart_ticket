"""
Provider tests: `Embedder` and `Reranker` own their contracts and delegate the
model work to any `LLMClient` that serves it. Loading through build_providers
is pinned in test_providers_factory.py.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.embeddings import EMBED_DIM, Embedder
from ai_engine.core.providers.llm.client import LLMClient
from ai_engine.core.providers.llm.local import LexicalClient, StubClient
from ai_engine.core.providers.llm.models import VLLMLLM
from ai_engine.core.providers.reranker import Reranker


class _ScriptedClient(LLMClient):
    """Serves embed and rerank with canned replies, so the contract checks in
    Embedder / Reranker are tested without any provider."""

    def __init__(self, vector=None, scores=None):
        super().__init__(model_name="scripted", cost_per_1k_tokens=0.0, fallback=None)
        self._vector = vector
        self._scores = scores
        self.rerank_calls = 0

    def embed(self, text):
        return self._vector

    def rerank(self, query, passages):
        self.rerank_calls += 1
        return self._scores


def _vllm(base_url="http://vllm:8000/v1", model="BAAI/bge-reranker-v2-m3") -> VLLMLLM:
    return VLLMLLM(
        model=model, base_url=base_url, connect_timeout=3.0, read_timeout=120.0, fallback=None
    )


# --- Embedder / Reranker contracts -------------------------------------------


def test_a_client_that_cannot_do_the_job_fails_at_construction():
    """A misconfigured provider must fail the boot — a container that won't
    start — not the first ticket."""

    with pytest.raises(TypeError, match="does not serve embeddings"):
        Embedder(client=LexicalClient())
    with pytest.raises(TypeError, match="does not serve reranking"):
        Reranker(client=StubClient())


@pytest.mark.parametrize("returned_dim", [0, 768, EMBED_DIM - 1])
def test_embedder_rejects_a_wrong_width_vector(returned_dim):
    """EMBED_DIM is the pgvector column width, which no client knows about.
    A wrong-width vector fails far away as a pgvector error or — if empty —
    as an ordinary refuse-before-LLM, reporting a provider outage as a
    finding about the KB."""

    embedder = Embedder(client=_ScriptedClient(vector=[0.1] * returned_dim))
    with pytest.raises(ValueError, match=f"expected {EMBED_DIM}"):
        embedder.embed("không đăng nhập được")


@pytest.mark.parametrize("returned", [[0.5], [0.5, 0.5, 0.5]], ids=["short", "padded"])
def test_reranker_rejects_a_score_count_that_does_not_match(returned):
    """The rerank node zips scores against its candidates positionally — a
    short or padded list mislabels which chunk got which score, and the top-1
    score is what `retrieval_floor` is compared against (ADR-0005)."""

    reranker = Reranker(client=_ScriptedClient(scores=returned))
    with pytest.raises(ValueError, match="scores for 2 passages"):
        reranker.score("q", ["a", "b"])


def test_reranker_empty_passages_calls_no_client():
    """Refuse-before-LLM and budget paths can reach the reranker with nothing
    to score; they must get `[]` without a model call."""

    client = _ScriptedClient(scores=[])
    assert Reranker(client=client).score("q", []) == []
    assert client.rerank_calls == 0


def test_supports_reflects_what_a_client_implements():
    assert _vllm().supports("chat") and _vllm().supports("embed") and _vllm().supports("rerank")
    assert StubClient().supports("embed") and not StubClient().supports("chat")
    assert LexicalClient().supports("rerank") and not LexicalClient().supports("embed")


# --- local clients -----------------------------------------------------------


def test_stub_client_is_deterministic_and_unit_norm():
    """The eval suite runs with EMBEDDING_PROVIDER=stub and compares retrieval
    results across runs; a non-deterministic stub would make every retrieval
    metric noise."""

    embedder = Embedder(client=StubClient())
    first = embedder.embed("không đăng nhập được")

    assert first == embedder.embed("không đăng nhập được")
    assert len(first) == EMBED_DIM
    assert abs(sum(x * x for x in first) ** 0.5 - 1.0) < 1e-9
    assert first != embedder.embed("a different ticket")


def test_lexical_client_scores_one_per_passage_in_input_order():
    passages = ["đăng nhập thất bại", "máy in hỏng", "vpn chậm"]
    scores = Reranker(client=LexicalClient()).score("không đăng nhập được", passages)

    assert len(scores) == len(passages)
    assert scores[0] == max(scores)


# --- VLLMLLM embed / rerank --------------------------------------------------


def test_vllm_client_construction_opens_no_socket(monkeypatch):
    """build_providers() constructs these at uvicorn import time, with no
    vLLM server reachable."""

    import socket

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    client = _vllm()
    Embedder(client=client)
    Reranker(client=client)
    _ = client._embeddings  # built on first use; building must not connect either
    _ = client._rerank_http
    assert opened == []


def test_vllm_embed_returns_the_models_vector():
    class _Embeddings:
        def embed_query(self, text):
            return [0.2] * EMBED_DIM

    client = _vllm(model="BAAI/bge-m3")
    client.__dict__["_embeddings"] = _Embeddings()

    assert Embedder(client=client).embed("q") == [0.2] * EMBED_DIM


def _vllm_reranker(handler) -> Reranker:
    client = _vllm(base_url=settings.vllm_rerank_base_url, model=settings.reranker_model)
    client.__dict__["_rerank_http"] = httpx.Client(
        base_url=settings.vllm_rerank_base_url, transport=httpx.MockTransport(handler)
    )
    return Reranker(client=client)


def _rerank_reply(pairs):
    return {"results": [{"index": i, "relevance_score": s} for i, s in pairs]}


def test_vllm_rerank_returns_scores_in_input_order_not_rank_order():
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
def test_vllm_rerank_raises_on_an_unusable_reply(body):
    """A short or misindexed result list would attach relevance to the wrong
    chunk while the ranking still looks plausible."""

    reranker = _vllm_reranker(lambda request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        reranker.score("q", ["a", "b"])


def test_vllm_rerank_raises_on_a_server_error():
    """No fallback to lexical: a different calibration (ADR-0005). The ticket
    degrades to HITL instead."""

    reranker = _vllm_reranker(lambda request: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        reranker.score("q", ["a"])


@pytest.mark.parametrize(
    ("embedding_provider", "reranker_provider"),
    [("stub", "lexical"), ("vllm", "vllm")],
)
def test_every_built_provider_is_the_shared_class(
    embedding_provider, reranker_provider, monkeypatch
):
    """Nodes depend on Embedder / Reranker / LLMClient; whatever the config,
    build_providers must hand them those types."""

    from ai_engine.core.providers.factory import build_providers

    monkeypatch.setattr(settings, "embedding_provider", embedding_provider)
    monkeypatch.setattr(settings, "reranker_provider", reranker_provider)
    providers = build_providers()

    assert isinstance(providers.embedder, Embedder)
    assert isinstance(providers.reranker, Reranker)
    assert isinstance(providers.llm, LLMClient)
