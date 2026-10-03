"""
Provider and client tests. Each runs a provider through the real client
(`clients.embed`, `clients.rerank`, `clients.jev`) against a scripted server
(conftest's `serve`), so the request building and reply validation are both
under test. Selection at import time is pinned in test_provider_selection.py.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from ai_engine.core.config import settings
from ai_engine.core.providers.embeddings import EMBED_DIM, LexicalEmbedder, StubEmbedder
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import ChatClient, HttpClient
from ai_engine.core.providers.dtos import JevRequest, RerankRequest
from ai_engine.graph.nodes.candidate_pool.shortlister import (
    CrossEncoderShortlister,
    LexicalShortlister,
)
from ai_engine.graph.nodes.rerank.reranker import JevReranker, Passage


@pytest.fixture
def serve_embeddings(serve):
    return lambda body: serve("embed", body)


@pytest.fixture
def serve_rerank(serve):
    return lambda body: serve("rerank", body)


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


# --- CrossEncoderShortlister ----------------------------------------------------------------


def test_reranker_returns_scores_in_input_order_not_rank_order(serve_rerank):
    """Servers sort results by score. The rerank node zips scores against its
    candidates positionally, so they must come back in INPUT order."""

    client = serve_rerank(_rerank_reply([(2, 0.9), (0, 0.4), (1, 0.1)]))

    scores = CrossEncoderShortlister().score("vpn down", ["a", "b", "c"])

    assert scores == [0.4, 0.1, 0.9]
    assert client.sent == [
        (
            "/rerank",
            {"model": settings.reranker_model, "query": "vpn down", "documents": ["a", "b", "c"]},
        )
    ]


def test_reranker_empty_passages_sends_no_request(serve_rerank):
    """Refuse-before-LLM paths can reach the shortlister with nothing
    to score; they must get `[]` without a model call."""

    client = serve_rerank(_rerank_reply([]))
    assert CrossEncoderShortlister().score("q", []) == []
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
        CrossEncoderShortlister().score("q", ["a", "b"])


def test_lexical_reranker_scores_one_per_passage_in_input_order():
    passages = ["đăng nhập thất bại", "máy in hỏng", "vpn chậm"]
    scores = LexicalShortlister().score("không đăng nhập được", passages)

    assert len(scores) == len(passages)
    assert scores[0] == max(scores)


# --- HttpClient.request ---------------------------------------------------------


def _vllm(handler) -> HttpClient:
    client = HttpClient(base_url="http://vllm:8000/v1")
    client.__dict__["_http"] = httpx.Client(
        base_url="http://vllm:8000/v1", transport=httpx.MockTransport(handler)
    )
    return client


def test_vllm_request_posts_json_under_the_base_url():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    payload = RerankRequest(model="m", query="q", documents=["a"])
    assert _vllm(handler).request("/rerank", payload) == {"ok": True}
    assert seen == [("/v1/rerank", {"model": "m", "query": "q", "documents": ["a"]})]


def test_vllm_request_raises_on_a_server_error():
    """No fallback: the ticket degrades to HITL instead."""

    with pytest.raises(httpx.HTTPStatusError):
        _vllm(lambda request: httpx.Response(503)).request(
            "/rerank", RerankRequest(model="m", query="q", documents=["a"])
        )


def test_vllm_client_opens_no_socket_until_a_request(monkeypatch):
    """clients.py constructs these at uvicorn import time, with no
    vLLM server reachable."""

    import socket

    opened = []
    real_connect = socket.socket.connect
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, addr, *a: (opened.append(addr), real_connect(self, addr, *a))[1],
    )

    client = HttpClient(base_url="http://vllm:8000/v1")
    _ = client._http
    assert opened == []


# --- Jev (ADR-0015) --------------------------------------------------------------


def _jev(handler) -> HttpClient:
    client = HttpClient(base_url="https://jev.test/v1", api_key=SecretStr("k"))
    client.__dict__["_http"] = httpx.Client(
        base_url="https://jev.test/v1", transport=httpx.MockTransport(handler)
    )
    return client


def test_jev_client_raises_on_a_rate_limit():
    """No retry, a 429 included: the run fails and the ticket goes to a
    human as `ai_engine_unavailable`, rather than waiting out a backoff."""

    with pytest.raises(httpx.HTTPStatusError):
        _jev(lambda request: httpx.Response(429)).request(
            "/systemone", JevRequest(model="m", state={}, questions={})
        )


def test_jev_client_sends_the_key_as_a_bearer_token():
    client = HttpClient(base_url="https://jev.test/v1", api_key=SecretStr("k"))
    assert client._http.headers["Authorization"] == "Bearer k"


def test_a_client_without_a_key_sends_no_authorization_header():
    """vLLM is unauthenticated; an empty `Bearer ` would be a malformed header."""
    assert "Authorization" not in HttpClient(base_url="http://vllm:8000/v1")._http.headers


@pytest.fixture
def serve_jev(serve):
    return lambda body: serve("jev", body)


def _jev_reply(noul, model=None):
    return {
        "model": model or settings.jev_model,
        "answers": {"resolves": {"type": "noul", "noul": noul}},
    }


def test_a_jev_reply_from_another_model_raises(serve_jev):
    """An alias move would change the scale the floor is set against."""

    serve_jev(_jev_reply(0.9, model="jev-latest"))

    with pytest.raises(ValueError, match="Jev answered as"):
        JevReranker().score("s", "b", [Passage("t", "x")])


def test_a_jev_answer_outside_0_1_raises(serve_jev):
    serve_jev(_jev_reply(1.5))

    with pytest.raises(ValueError, match="unusable Jev reply"):
        JevReranker().score("s", "b", [Passage("t", "x")])


_UNUSABLE_JEV_REPLIES = {
    "error body": {"error": "rate limited"},
    "no answer for the question": {"model": "M", "answers": {}},
    "not a noul": {"model": "M", "answers": {"resolves": {"type": "bool", "noul": 0.5}}},
    "missing noul": {"model": "M", "answers": {"resolves": {"type": "noul"}}},
    "negative noul": {"model": "M", "answers": {"resolves": {"type": "noul", "noul": -0.1}}},
}


@pytest.mark.parametrize("body", _UNUSABLE_JEV_REPLIES.values(), ids=_UNUSABLE_JEV_REPLIES.keys())
def test_jev_raises_on_an_unusable_reply(body, serve_jev):
    """Every malformed reply raises, so the run goes to a human. A defaulted
    score would compare against a floor set on Jev's scale (ADR-0015)."""

    if body.get("model") == "M":
        body = {**body, "model": settings.jev_model}
    serve_jev(body)

    with pytest.raises(ValueError, match="unusable Jev reply"):
        JevReranker().score("s", "b", [Passage("t", "x")])


def test_jev_scores_through_the_jev_client(serve_jev):
    jev = serve_jev(_jev_reply(0.7))

    assert JevReranker().score("s", "b", [Passage("t", "x")]) == [0.7]
    [(path, payload)] = jev.sent
    assert path == "/systemone"
    assert payload["state"] == {
        "ticket": {"subject": "s", "body": "b"},
        "passage": {"title": "t", "text": "x"},
    }


@pytest.mark.parametrize(
    ("embedding_provider", "shortlist_provider"),
    [("stub", "lexical"), ("vllm", "vllm")],
)
def test_every_built_provider_is_the_shared_type(
    embedding_provider, shortlist_provider, monkeypatch, reload_embeddings, reload_shortlister
):
    """Whatever the config, the modules must build something the nodes can
    call: an embedder, a reranker and a `ChatClient`."""

    monkeypatch.setattr(settings, "embedding_provider", embedding_provider)
    monkeypatch.setattr(settings, "shortlist_provider", shortlist_provider)
    e = reload_embeddings()
    r = reload_shortlister()

    assert isinstance(e.embedder, e.Embedder)
    assert isinstance(r.shortlister, r.Shortlister)
    assert isinstance(clients.chat, ChatClient)
