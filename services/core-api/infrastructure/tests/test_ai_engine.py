"""
`AIEngineClient`, core-api's only way to reach ai-engine and, through it,
any model (ADR-0012). It's transport only, but its failure contract carries
safety weight:
- `analyze` raises only `AIEngineUnavailable` → HITL as ai_engine_unavailable,
- `embed` raises only `httpx.HTTPError` / `ValueError` → embedding_unavailable
  (ai-engine unreachable included, ADR-0012), and never returns a vector
  that doesn't fit the pgvector column,
- `detect_pii` raises only `httpx.HTTPError` / `ValueError` → MASK_FAILED.
An exception outside those escapes its caller's handler, and a ticket is
left stuck or a submit request 500s.
"""

import json

import httpx
import pytest
from asgiref.sync import async_to_sync

from apps.tickets.utils.patterns import PIILevel
from infrastructure.dtos import (
    EMBED_DIM,
    AIRunResponse,
    GenerationSignals,
    PolicySignals,
    RetrievalSignals,
    TicketMasked,
    TrustSignals,
)
from infrastructure.ai_engine import AIEngineUnavailable, ai_engine

_TICKET = TicketMasked(
    ticket_public_id="TKT-1",
    subject_masked="May in bi ket giay",
    body_masked="May in tang 3 bi ket giay",
    pii_level=PIILevel.ROUTINE,
)


def _run_response(request_id: str) -> dict:
    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="n/a",
        proposal=None,
        signals=TrustSignals(
            retrieval=RetrievalSignals(
                rerank_top1=0, rerank_margin=0, bm25_keyword_hit=False, docs_above_floor=0
            ),
            generation=GenerationSignals(
                schema_valid=False,
                quote_match_ratio=0,
                quote_source_in_topk=False,
                negation_consistent=False,
                category_consistent=False,
            ),
            policy=PolicySignals(
                kb_auto_reply_allowed=False,
                kb_risk_tier="high",
                pii_level=PIILevel.ROUTINE,
                injection_detected=False,
                mass_incident=False,
            ),
        ),
    ).model_dump(mode="json")


def _raise(error: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


def _reply(status: int = 200, **kw):
    return lambda request: httpx.Response(status, **kw)


_TRANSPORT_FAILURES = {
    "connect error": _raise(httpx.ConnectError("ai-engine unreachable")),
    "read timeout": _raise(httpx.ReadTimeout("slow")),
    "server error": _reply(502),
    "not json": _reply(200, text="<html>bad gateway</html>"),
    "wrong shape": _reply(200, json={"unexpected": True}),
}


# --- analyze ------------------------------------------------------------------


@pytest.mark.parametrize("handler", _TRANSPORT_FAILURES.values(), ids=_TRANSPORT_FAILURES.keys())
def test_analyze_failure_is_always_ai_engine_unavailable(serve_ai_engine, handler):
    """The pipeline catches exactly AIEngineUnavailable and sends the ticket
    to a human. Anything else escapes the Celery task and leaves the ticket
    at status="new", invisible to every queue."""

    serve_ai_engine(handler)
    with pytest.raises(AIEngineUnavailable):
        ai_engine.analyze(_TICKET, request_id="t:1")


def test_analyze_posts_the_masked_ticket_and_retrieval_floor(serve_ai_engine, settings):
    settings.AI_ENGINE_URL = "http://ai-engine:8001/"
    calls = serve_ai_engine(_reply(200, json=_run_response("t:1")))

    resp = ai_engine.analyze(_TICKET, request_id="t:1")

    assert resp.request_id == "t:1"
    [request] = calls.requests
    assert str(request.url) == "http://ai-engine:8001/v1/analyze"
    body = json.loads(request.content)
    assert body["ticket"]["subject_masked"] == "May in bi ket giay"
    assert body["retrieval_floor"] == settings.THRESHOLDS.retrieval_floor


def test_analyze_connect_timeout_is_short_and_separate_from_the_read_budget(
    serve_ai_engine, settings
):
    """Before, one number (budget + 5s) covered both, so an unreachable
    ai-engine held the task for the whole five-minute budget before an error
    that was knowable in three seconds."""

    calls = serve_ai_engine(_reply(200, json=_run_response("t:1")))

    ai_engine.analyze(_TICKET, request_id="t:1")

    [timeout] = calls.timeouts
    assert timeout.connect == settings.MODEL_CONNECT_TIMEOUT_SEC
    assert (
        timeout.read
        == settings.THRESHOLDS.budget.max_latency_sec + settings.AI_ENGINE_ANALYZE_GRACE_SEC
    )


# --- embed ----------------------------------------------------------------------


@pytest.mark.parametrize("handler", _TRANSPORT_FAILURES.values(), ids=_TRANSPORT_FAILURES.keys())
def test_embed_failure_is_http_error_or_value_error(serve_ai_engine, handler):
    """The two types process_ticket turns into embedding_unavailable."""

    serve_ai_engine(handler)
    with pytest.raises((httpx.HTTPError, ValueError)):
        ai_engine.embed("...")


def test_embed_rejects_a_vector_of_the_wrong_width(serve_ai_engine):
    """EMBED_DIM is the pgvector column width; a short vector would fail far
    away as a database error."""

    serve_ai_engine(_reply(200, json={"vector": [0.1] * 768, "model": "other"}))
    with pytest.raises(ValueError, match=f"expected {EMBED_DIM}"):
        ai_engine.embed("...")


def test_embed_reads_the_vector_and_the_model(serve_ai_engine):
    vector = [0.01] * EMBED_DIM
    calls = serve_ai_engine(_reply(200, json={"vector": vector, "model": "BAAI/bge-m3"}))

    resp = ai_engine.embed("may in bi ket giay")

    assert (resp.vector, resp.model) == (vector, "BAAI/bge-m3")
    [request] = calls.requests
    assert request.url.path == "/v1/embed"
    assert json.loads(request.content) == {"text": "may in bi ket giay"}


# --- detect_pii -----------------------------------------------------------------


def _detect(text: str) -> list[str]:
    return async_to_sync(ai_engine.detect_pii)(text)


@pytest.mark.parametrize("handler", _TRANSPORT_FAILURES.values(), ids=_TRANSPORT_FAILURES.keys())
def test_detect_pii_failure_is_http_error_or_value_error(serve_ai_engine, handler):
    """The two types masking resolves to MASK_FAILED. Anything else would
    500 the submit request instead of filing the ticket for a human."""

    serve_ai_engine(handler)
    with pytest.raises((httpx.HTTPError, ValueError)):
        _detect("...")


def test_detect_pii_rejects_a_reply_that_is_not_a_list_of_spans(serve_ai_engine):
    """`{}` or `{"spans": null}` must not read as "nothing found"."""

    serve_ai_engine(_reply(200, json={"spans": None}))
    with pytest.raises(ValueError):
        _detect("...")


def test_detect_pii_sends_the_text_and_reads_the_spans(serve_ai_engine):
    calls = serve_ai_engine(_reply(200, json={"spans": ["anh Tuan phong ke toan"]}))

    assert _detect("Lien he anh Tuan phong ke toan") == ["anh Tuan phong ke toan"]
    [request] = calls.requests
    assert request.url.path == "/v1/pii/detect"
    assert json.loads(request.content) == {"text": "Lien he anh Tuan phong ke toan"}


def test_model_calls_get_the_model_read_budget_and_a_short_connect(serve_ai_engine, settings):
    """Masking runs inline in the submit request: an unreachable ai-engine
    must fail in seconds, while a cold model load still gets its full read
    budget. Read at call time, so override_settings applies."""

    settings.MODEL_TIMEOUT_SEC = 45.0
    calls = serve_ai_engine(_reply(200, json={"spans": []}))

    _detect("...")

    [timeout] = calls.timeouts
    assert timeout.connect == settings.MODEL_CONNECT_TIMEOUT_SEC == 3.0
    assert timeout.read == 45.0
