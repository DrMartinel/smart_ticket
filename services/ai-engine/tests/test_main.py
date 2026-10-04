"""
HTTP surface tests for `/v1/embed` and `/v1/pii/detect` (ADR-0012). What
matters is the failure contract core-api relies on: a provider failure is a
502, never an empty result. A 502 on embed means `embedding_unavailable`,
and a 502 on NER means `mask_failed`. `/v1/pii/detect` takes raw PII, so no
response or log line may carry it back out.
"""

from __future__ import annotations

import logging

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ai_engine.core.providers.pii import PiiDetectionError
from ai_engine.main import app

_RAW = "anh Tuấn phòng kế toán tầng 3 không in được"


@pytest.fixture
def client():
    return TestClient(app)


# --- failure paths first ------------------------------------------------------


def test_embedder_failure_is_a_502_not_an_empty_vector(client, fake_embedder, use_embedder):
    """An empty or zero vector would read as "nothing similar", not "the
    embedder is down"."""

    use_embedder(fake_embedder(error=RuntimeError("vllm-embed down")))

    resp = client.post("/v1/embed", json={"text": "SSH connection timed out"})

    assert resp.status_code == 502
    assert "vector" not in resp.json()


def test_ner_failure_is_a_502_not_an_empty_span_list(client, fake_pii_detector, use_pii_detector):
    """[] means "no PII found", and core-api would file the ticket as clean."""

    use_pii_detector(fake_pii_detector(error=PiiDetectionError("NER call failed")))

    resp = client.post("/v1/pii/detect", json={"text": _RAW})

    assert resp.status_code == 502
    assert "spans" not in resp.json()


def test_any_ner_exception_is_a_502(client, fake_pii_detector, use_pii_detector):
    """Not only PiiDetectionError: an unexpected bug must not become a 200."""

    use_pii_detector(fake_pii_detector(error=KeyError("choices")))

    assert client.post("/v1/pii/detect", json={"text": _RAW}).status_code == 502


def test_ner_failure_leaks_the_text_into_neither_response_nor_log(
    client, fake_pii_detector, use_pii_detector, caplog
):
    use_pii_detector(fake_pii_detector(error=RuntimeError(f"echo: {_RAW}")))

    with caplog.at_level(logging.DEBUG):
        resp = client.post("/v1/pii/detect", json={"text": _RAW})

    assert _RAW not in resp.text
    assert _RAW not in caplog.text


def test_a_malformed_ner_request_is_rejected_without_echoing_it(client):
    """FastAPI's default 422 echoes the input, which here is raw PII."""

    resp = client.post("/v1/pii/detect", json={"txt": _RAW})

    assert resp.status_code == 422
    assert _RAW not in resp.text


# --- behaviour ------------------------------------------------------------------


def test_embed_returns_the_vector_and_the_model_that_made_it(client, fake_embedder, use_embedder):
    """core-api stores `model` with the embedding instead of keeping its own
    copy of EMBED_MODEL in step."""

    embedder = use_embedder(fake_embedder(vector=[0.5] * 8))

    resp = client.post("/v1/embed", json={"text": "SSH connection timed out"})

    assert resp.status_code == 200
    assert resp.json() == {"vector": [0.5] * 8, "model": "fake-embed"}
    assert embedder.calls == ["SSH connection timed out"]


def test_detect_returns_the_detectors_spans(client, fake_pii_detector, use_pii_detector):
    detector = use_pii_detector(fake_pii_detector(spans=["anh Tuấn phòng kế toán tầng 3"]))

    resp = client.post("/v1/pii/detect", json={"text": _RAW})

    assert resp.status_code == 200
    assert resp.json() == {"spans": ["anh Tuấn phòng kế toán tầng 3"]}
    assert detector.calls == [_RAW]


def test_detect_passes_an_empty_answer_through(client, fake_pii_detector, use_pii_detector):
    use_pii_detector(fake_pii_detector(spans=[]))
    assert client.post("/v1/pii/detect", json={"text": _RAW}).json() == {"spans": []}


# --- /v1/analyze ----------------------------------------------------------------


def test_retrieved_chunks_carry_both_stages_scores(client, make_state, monkeypatch):
    """Each chunk reports the final score the floor compared (`rerank_score`,
    the key stored runs have always had) and the shortlister's
    (`shortlist_score`). Without both, a run can't show what Jev changed,
    and neither scale can be calibrated against the other."""

    from ai_engine import main
    from ai_engine.graph.nodes.emit_signals.signals import EngineSignals, RetrievalSignals
    from ai_engine.graph.state import RankedChunk
    from ai_engine.graph.nodes.emit_signals.signals import ClassificationSignals, GenerationSignals

    chunk = RankedChunk(
        chunk_id=UUID(int=1),
        article_id=UUID(int=10),
        article_slug="kb-a",
        content="c",
        shortlist_score=0.7,
        rerank_score=0.95,
    )
    signals = EngineSignals(
        retrieval=RetrievalSignals(rerank_top1=0.95, rerank_margin=0.0, docs_above_floor=1),
        generation=GenerationSignals(
            quote_applicable=False,
            quote_match_ratio=0.0,
            quote_source_in_topk=False,
            negation_consistent=False,
        ),
        classification=ClassificationSignals(category_choice=None, category_confidence=0.0),
        injection_detected=False,
    )
    final = make_state(reranked=[chunk], signals=signals)
    monkeypatch.setattr(
        main, "triage_graph", type("G", (), {"invoke": lambda self, s: final.model_dump()})()
    )

    resp = client.post(
        "/v1/analyze",
        json={
            "request_id": "r",
            "ticket": final.ticket.model_dump(mode="json"),
            "retrieval_floor": 0.3,
        },
    )

    assert resp.status_code == 200
    [out] = resp.json()["retrieved_chunks"]
    assert out == {
        "chunk_id": str(UUID(int=1)),
        "kb_slug": "kb-a",
        "rerank_score": 0.95,
        "shortlist_score": 0.7,
    }
