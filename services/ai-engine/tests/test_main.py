"""
HTTP surface tests for `/v1/embed` and `/v1/pii/detect` (ADR-0012). What
matters is the failure contract core-api relies on: a provider failure is a
502, never an empty result. A 502 on embed means `embedding_unavailable`,
and a 502 on NER means `mask_failed`. `/v1/pii/detect` takes raw PII, so no
response or log line may carry it back out.
"""

from __future__ import annotations

import logging

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

    resp = client.post("/v1/embed", json={"text": "máy in kẹt giấy"})

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

    resp = client.post("/v1/embed", json={"text": "máy in kẹt giấy"})

    assert resp.status_code == 200
    assert resp.json() == {"vector": [0.5] * 8, "model": "fake-embed"}
    assert embedder.calls == ["máy in kẹt giấy"]


def test_detect_returns_the_detectors_spans(client, fake_pii_detector, use_pii_detector):
    detector = use_pii_detector(fake_pii_detector(spans=["anh Tuấn phòng kế toán tầng 3"]))

    resp = client.post("/v1/pii/detect", json={"text": _RAW})

    assert resp.status_code == 200
    assert resp.json() == {"spans": ["anh Tuấn phòng kế toán tầng 3"]}
    assert detector.calls == [_RAW]


def test_detect_passes_an_empty_answer_through(client, fake_pii_detector, use_pii_detector):
    use_pii_detector(fake_pii_detector(spans=[]))
    assert client.post("/v1/pii/detect", json={"text": _RAW}).json() == {"spans": []}
