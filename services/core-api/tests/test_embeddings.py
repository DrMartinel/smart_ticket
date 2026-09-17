"""
core-api's embedder (ADR-0009). Every failure must surface as httpx.HTTPError
or ValueError: those are the two types process_ticket turns into an
embedding_unavailable HITL route. Anything else escapes the Celery task and
leaves the ticket stuck at status="new", invisible to every queue.
"""

import httpx
import pytest

from apps.tickets.services import embeddings
from apps.tickets.services.embeddings import EMBED_DIM, embed_text


def _mock_post(monkeypatch, handler):
    """Route `httpx.post` through a MockTransport, recording the request."""

    seen = {}

    def post(url, **kw):
        seen["url"], seen["json"], seen["timeout"] = url, kw["json"], kw["timeout"]
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.post(url, json=kw["json"])

    monkeypatch.setattr(embeddings.httpx, "post", post)
    return seen


@pytest.fixture
def vllm(settings):
    settings.EMBEDDING_PROVIDER = "vllm"
    settings.VLLM_EMBED_BASE_URL = "http://vllm-embed:8000/v1"
    settings.VLLM_EMBED_MODEL = "BAAI/bge-m3"
    return settings


def test_vllm_embedding_is_read_from_the_openai_shape(vllm, monkeypatch):
    vector = [0.01] * EMBED_DIM
    seen = _mock_post(
        monkeypatch, lambda request: httpx.Response(200, json={"data": [{"embedding": vector}]})
    )

    assert embed_text("may in bi ket giay") == vector
    assert seen["url"] == "http://vllm-embed:8000/v1/embeddings"
    assert seen["json"] == {"model": "BAAI/bge-m3", "input": "may in bi ket giay"}
    assert seen["timeout"].connect < seen["timeout"].read, "connect must fail fast"


_UNUSABLE = {
    "no data": {"data": []},
    "error body": {"error": "model not loaded"},
    "no embedding key": {"data": [{}]},
    "null embedding": {"data": [{"embedding": None}]},
}


@pytest.mark.parametrize("body", _UNUSABLE.values(), ids=_UNUSABLE.keys())
def test_unusable_reply_raises_value_error(vllm, monkeypatch, body):
    _mock_post(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        embed_text("...")


def test_wrong_width_vector_raises_value_error(vllm, monkeypatch):
    """EMBED_DIM is the pgvector column width; a short vector would fail far
    away as a database error."""

    _mock_post(
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": [{"embedding": [0.1] * 768}]}),
    )
    with pytest.raises(ValueError, match=f"expected {EMBED_DIM}"):
        embed_text("...")


def test_server_error_raises_http_error(vllm, monkeypatch):
    _mock_post(monkeypatch, lambda request: httpx.Response(503))
    with pytest.raises(httpx.HTTPError):
        embed_text("...")


def test_non_json_reply_raises_value_error(vllm, monkeypatch):
    _mock_post(monkeypatch, lambda request: httpx.Response(200, text="<html>bad gateway</html>"))
    with pytest.raises(ValueError):
        embed_text("...")


def test_unknown_provider_raises_value_error(settings):
    """A typo must reach a human as embedding_unavailable, not quietly pick
    a provider."""

    settings.EMBEDDING_PROVIDER = "ollama"
    with pytest.raises(ValueError, match="unknown EMBEDDING_PROVIDER"):
        embed_text("...")


def test_stub_provider_makes_no_request(settings, monkeypatch):
    settings.EMBEDDING_PROVIDER = "stub"

    def fail(*a, **kw):
        raise AssertionError("stub must not make a request")

    monkeypatch.setattr(embeddings.httpx, "post", fail)
    assert len(embed_text("...")) == EMBED_DIM
