"""
Provider tests. `LexicalEmbedder` and `CrossEncoderReranker` own their tasks — building the
request, parsing the reply, checking the result — and send the request through
`models.embed` / `models.rerank`. Selection at import time is
pinned in test_provider_selection.py.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.embeddings import EMBED_DIM, LexicalEmbedder, StubEmbedder
from ai_engine.core.providers.llm import models
from ai_engine.core.providers.llm.models import LLMClient
from ai_engine.core.providers.llm.models import VLLMLLM
from ai_engine.core.providers.reranker import LexicalReranker, CrossEncoderReranker


class _ScriptedClient(LLMClient):
    """Answers every request with one canned body and records what was sent.
    Swapped in for `models.embed` / `models.rerank`, so the
    task logic in LexicalEmbedder / CrossEncoderReranker is tested without a server."""

    def __init__(self, body):
        super().__init__(model_name="scripted", cost_per_1k_tokens=0.0)
        self._body = body
        self.sent: list[tuple[str, dict]] = []

    def request(self, path, payload):
        self.sent.append((path, payload))
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def serve_embeddings(monkeypatch):
    def install(body):
        client = _ScriptedClient(body)
        monkeypatch.setattr(models, "embed", client)
        return client

    return install


@pytest.fixture
def serve_rerank(monkeypatch):
    def install(body):
        client = _ScriptedClient(body)
        monkeypatch.setattr(models, "rerank", client)
        return client

    return install


def _embeddings_reply(vector):
    return {"data": [{"embedding": vector}]}


def _rerank_reply(pairs):
    return {"results": [{"index": i, "relevance_score": s} for i, s in pairs]}


# --- LexicalEmbedder ----------------------------------------------------------------


def test_embedder_sends_its_own_request_and_returns_the_vector(serve_embeddings):
    client = serve_embeddings(_embeddings_reply([0.2] * EMBED_DIM))

    vector = LexicalEmbedder().embed("may in bi ket")

    assert vector == [0.2] * EMBED_DIM
    assert client.sent == [
        ("/embeddings", {"model": settings.embed_model, "input": "may in bi ket"})
    ]


@pytest.mark.parametrize("returned_dim", [0, 768, EMBED_DIM - 1])
def test_embedder_rejects_a_wrong_width_vector(returned_dim, serve_embeddings):
    """EMBED_DIM is the pgvector column width, which no server knows about.
    A wrong-width vector fails far away as a pgvector error or — if empty —
    as an ordinary refuse-before-LLM, reporting a provider outage as a
    finding about the KB."""

    serve_embeddings(_embeddings_reply([0.1] * returned_dim))
    with pytest.raises(ValueError, match=f"expected {EMBED_DIM}"):
        LexicalEmbedder().embed("không đăng nhập được")


_UNUSABLE_EMBEDDINGS = {
    "no data": {"data": []},
    "error body": {"error": "model not loaded"},
    "no embedding key": {"data": [{}]},
    "null embedding": {"data": [{"embedding": None}]},
}


@pytest.mark.parametrize("body", _UNUSABLE_EMBEDDINGS.values(), ids=_UNUSABLE_EMBEDDINGS.keys())
def test_embedder_raises_on_an_unusable_reply(body, serve_embeddings):
    """Never a zero or empty vector: that reads as "the KB has nothing
    relevant" instead of "the embedder is down"."""

    serve_embeddings(body)
    with pytest.raises(ValueError):
        LexicalEmbedder().embed("...")


def test_stub_embedder_is_deterministic_and_unit_norm():
    """The eval suite runs with EMBEDDING_PROVIDER=stub and compares retrieval
    results across runs; a non-deterministic stub would make every retrieval
    metric noise."""

    embedder = StubEmbedder()
    first = embedder.embed("không đăng nhập được")

    assert first == embedder.embed("không đăng nhập được")
    assert len(first) == EMBED_DIM
    assert abs(sum(x * x for x in first) ** 0.5 - 1.0) < 1e-9
    assert first != embedder.embed("a different ticket")


# --- CrossEncoderReranker ----------------------------------------------------------------


def test_reranker_returns_scores_in_input_order_not_rank_order(serve_rerank):
    """Servers sort results by score. The rerank node zips scores against its
    candidates positionally, so they must come back in INPUT order."""

    client = serve_rerank(_rerank_reply([(2, 0.9), (0, 0.4), (1, 0.1)]))

    scores = CrossEncoderReranker().score("vpn down", ["a", "b", "c"])

    assert scores == [0.4, 0.1, 0.9]
    assert client.sent == [
        (
            "/rerank",
            {"model": settings.reranker_model, "query": "vpn down", "documents": ["a", "b", "c"]},
        )
    ]


def test_reranker_empty_passages_sends_no_request(serve_rerank):
    """Refuse-before-LLM and budget paths can reach the reranker with nothing
    to score; they must get `[]` without a model call."""

    client = serve_rerank(_rerank_reply([]))
    assert CrossEncoderReranker().score("q", []) == []
    assert client.sent == []


_UNUSABLE_RERANK_REPLIES = {
    "too few": _rerank_reply([(0, 0.5)]),
    "too many": _rerank_reply([(0, 0.5), (1, 0.4), (2, 0.3)]),
    "duplicate index": _rerank_reply([(0, 0.5), (0, 0.4)]),
    "index out of range": _rerank_reply([(0, 0.5), (2, 0.4)]),
    "missing score": {"results": [{"index": 0}, {"index": 1}]},
    "no results": {"data": []},
}


@pytest.mark.parametrize(
    "body", _UNUSABLE_RERANK_REPLIES.values(), ids=_UNUSABLE_RERANK_REPLIES.keys()
)
def test_reranker_raises_on_an_unusable_reply(body, serve_rerank):
    """A short, padded or misindexed result list would attach relevance to the
    wrong chunk while the ranking still looks plausible, and the top-1 score
    is what `retrieval_floor` is compared against (ADR-0005)."""

    serve_rerank(body)
    with pytest.raises(ValueError):
        CrossEncoderReranker().score("q", ["a", "b"])


def test_lexical_reranker_scores_one_per_passage_in_input_order():
    passages = ["đăng nhập thất bại", "máy in hỏng", "vpn chậm"]
    scores = LexicalReranker().score("không đăng nhập được", passages)

    assert len(scores) == len(passages)
    assert scores[0] == max(scores)


# --- VLLMLLM.request ---------------------------------------------------------


def _vllm(handler) -> VLLMLLM:
    client = VLLMLLM(model="m", base_url="http://vllm:8000/v1")
    client.__dict__["_http"] = httpx.Client(
        base_url="http://vllm:8000/v1", transport=httpx.MockTransport(handler)
    )
    return client


def test_vllm_request_posts_json_under_the_base_url():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    assert _vllm(handler).request("/rerank", {"query": "q"}) == {"ok": True}
    assert seen == [("/v1/rerank", {"query": "q"})]


def test_vllm_request_raises_on_a_server_error():
    """No fallback: the ticket degrades to HITL instead."""

    with pytest.raises(httpx.HTTPStatusError):
        _vllm(lambda request: httpx.Response(503)).request("/rerank", {})


def test_vllm_client_opens_no_socket_until_a_request(monkeypatch):
    """models.py constructs these at uvicorn import time, with no
    vLLM server reachable."""

    import socket

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    client = VLLMLLM(model="m", base_url="http://vllm:8000/v1")
    _ = client._http
    assert opened == []


@pytest.mark.parametrize(
    ("embedding_provider", "reranker_provider"),
    [("stub", "lexical"), ("vllm", "vllm")],
)
def test_every_built_provider_is_the_shared_type(
    embedding_provider, reranker_provider, monkeypatch, reload_embeddings, reload_reranker
):
    """Whatever the config, the modules must build something the nodes can
    call: an embedder, a reranker and an `LLMClient`."""

    monkeypatch.setattr(settings, "embedding_provider", embedding_provider)
    monkeypatch.setattr(settings, "reranker_provider", reranker_provider)
    e = reload_embeddings()
    r = reload_reranker()

    assert isinstance(e.embedder, e.Embedder)
    assert isinstance(r.reranker, r.Reranker)
    assert isinstance(models.chat, LLMClient)
