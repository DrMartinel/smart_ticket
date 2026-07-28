"""
Masking engine — spec §5. This is the P0 exit condition (spec §14:
"masking test coverage 100%"), so every branch of the two-tier pipeline is
covered: critical short-circuit, Ollama success, Ollama timeout/error
(MASK_FAILED, never silently "clean"), and placeholder numbering.
"""

import json

import httpx
import pytest
from asgiref.sync import async_to_sync

from contracts.enums import PIILevel
from contracts.ticket import TicketIn

from apps.tickets.services.masking import (
    OllamaError,
    _spans_to_hits,
    mask,
    ollama_ner,
    regex_scan,
    regex_scan_ticket,
)


def run_mask(raw: TicketIn):
    return async_to_sync(mask)(raw)


def run_ner(text: str):
    return async_to_sync(ollama_ner)(text)


def _mock_ollama_client(monkeypatch, generate_response: str):
    """Ollama's format="json" guarantees valid JSON, not any particular
    top-level shape — this stubs the /api/generate call to return a given
    `response` string, exactly as Ollama's HTTP API wraps it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": generate_response})

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("apps.tickets.services.masking.httpx.AsyncClient", MockAsyncClient)


class TestRegexTier:
    def test_email_detected(self):
        hits = regex_scan("lien he toi qua an.nguyen@company.com nhe")
        assert any(h.label == "EMAIL" for h in hits)

    def test_vn_phone_detected(self):
        hits = regex_scan("sdt cua toi la 0912345678")
        assert any(h.label == "PHONE_VN" for h in hits)

    def test_cccd_detected_as_sensitive(self):
        hits = regex_scan("so CCCD cua toi la 012345678901")
        assert any(h.label == "CCCD" and h.level is PIILevel.SENSITIVE for h in hits)

    def test_password_detected_as_critical(self):
        hits = regex_scan("password: hunter2")
        assert any(h.level is PIILevel.CRITICAL for h in hits)

    def test_internal_ip_detected(self):
        hits = regex_scan("server o dia chi 10.0.5.23 khong phan hoi")
        assert any(h.label == "INTERNAL_IP" for h in hits)

    def test_no_pii_no_hits(self):
        hits = regex_scan("May in bi ket giay")
        assert hits == []

    def test_scan_ticket_combines_subject_and_body(self):
        raw = TicketIn(subject="lien he an@x.com", body="so dien thoai 0912345678 cua toi day nhe")
        result = regex_scan_ticket(raw)
        labels = {h.label for h in result.hits}
        assert "EMAIL" in labels
        assert "PHONE_VN" in labels
        assert result.has_critical is False


class TestMaskCriticalShortCircuit:
    def test_critical_short_circuits_before_ollama(self, monkeypatch):
        called = False

        async def fake_ner(*a, **kw):
            nonlocal called
            called = True
            return []

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", fake_ner)
        raw = TicketIn(subject="quen mat khau", body="password: hunter2 can ho tro gap")
        result = run_mask(raw)

        assert result.pii_level is PIILevel.CRITICAL
        assert "hunter2" not in result.body_masked
        assert called is False, "Ollama must never be called once a CRITICAL hit is found"


class TestMaskOllamaTier:
    def test_ollama_timeout_becomes_mask_failed_not_clean(self, monkeypatch):
        async def raise_timeout(*a, **kw):
            raise TimeoutError("simulated timeout")

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", raise_timeout)
        raw = TicketIn(subject="Van de ky thuat", body="Toi can ho tro voi thiet bi cua minh, xin cam on")
        result = run_mask(raw)

        assert result.pii_level is PIILevel.MASK_FAILED

    def test_ollama_error_becomes_mask_failed_not_clean(self, monkeypatch):
        # ollama_ner's own contract already converts httpx/JSON errors into
        # OllamaError before they escape (see masking.py) — that's the
        # exception shape callers of ollama_ner actually need to handle.
        async def raise_error(*a, **kw):
            raise OllamaError("simulated 500")

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", raise_error)
        raw = TicketIn(subject="Van de ky thuat", body="May tinh cua toi bi loi man hinh xanh sang nay")
        result = run_mask(raw)

        assert result.pii_level is PIILevel.MASK_FAILED

    def test_ollama_success_merges_freeform_hits(self, monkeypatch):
        async def fake_ner(text, timeout=3.0):
            return ["anh Tuan phong ke toan"] if "Tuan" in text else []

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", fake_ner)
        raw = TicketIn(subject="Ho tro", body="Lien he anh Tuan phong ke toan de biet them chi tiet nhe")
        result = run_mask(raw)

        assert "anh Tuan phong ke toan" not in result.body_masked
        assert result.pii_level is not PIILevel.CRITICAL

    def test_no_hits_at_all_stays_routine(self, monkeypatch):
        async def fake_ner(*a, **kw):
            return []

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", fake_ner)
        raw = TicketIn(subject="May in bi ket giay", body="May in tren tang 3 bi ket giay tu sang nay")
        result = run_mask(raw)

        assert result.pii_level is PIILevel.ROUTINE
        assert result.placeholder_map == {}

    def test_cccd_hit_escalates_full_mask_to_sensitive(self, monkeypatch):
        async def fake_ner(*a, **kw):
            return []

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", fake_ner)
        raw = TicketIn(subject="Xac minh danh tinh", body="So CCCD cua toi la 012345678901, can xac minh gap")
        result = run_mask(raw)

        assert result.pii_level is PIILevel.SENSITIVE
        assert "012345678901" not in result.body_masked


class TestOllamaNerResponseParsing:
    """Regression coverage for a real failure mode hit against a live
    Ollama qwen3:8b: despite the prompt asking for a bare JSON array,
    format="json" only guarantees valid JSON — the model routinely wraps
    the array in an object, e.g. {"found": []} instead of []. Before the
    fix, that shape was treated as an unrecoverable parse error, which
    flagged every single ticket as MASK_FAILED regardless of content."""

    def test_bare_array_response(self, monkeypatch):
        _mock_ollama_client(monkeypatch, json.dumps(["anh Tuan phong ke toan"]))
        assert run_ner("...") == ["anh Tuan phong ke toan"]

    def test_object_wrapped_array_response(self, monkeypatch):
        _mock_ollama_client(monkeypatch, json.dumps({"found": ["anh Tuan phong ke toan"]}))
        assert run_ner("...") == ["anh Tuan phong ke toan"]

    def test_object_wrapped_empty_array_response(self, monkeypatch):
        _mock_ollama_client(monkeypatch, json.dumps({"result": []}))
        assert run_ner("...") == []

    def test_object_with_no_list_value_raises(self, monkeypatch):
        _mock_ollama_client(monkeypatch, json.dumps({"found": "not a list"}))
        with pytest.raises(OllamaError):
            run_ner("...")

    def test_non_json_response_raises(self, monkeypatch):
        _mock_ollama_client(monkeypatch, "not json at all")
        with pytest.raises(OllamaError):
            run_ner("...")

    def test_transport_timeout_becomes_timeout_error(self, monkeypatch):
        # Exercises ollama_ner's own httpx.TimeoutException -> TimeoutError
        # conversion — the other timeout test in TestMaskOllamaTier mocks
        # ollama_ner() wholesale, so it never runs this branch.
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("simulated network timeout")

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr("apps.tickets.services.masking.httpx.AsyncClient", MockAsyncClient)
        with pytest.raises(TimeoutError):
            run_ner("...")


class TestSpansToHits:
    def test_hallucinated_span_not_in_text_is_skipped(self):
        # The LLM is asked to return exact substrings, but nothing enforces
        # that at the model level — a span it "found" that doesn't actually
        # occur in the source text must be dropped, not turned into a
        # placeholder that masks non-existent content.
        hits = _spans_to_hits("May in tren tang 3 bi ket giay", ["anh Tuan phong ke toan"])
        assert hits == []

    def test_blank_span_is_skipped(self):
        hits = _spans_to_hits("May in tren tang 3 bi ket giay", ["   "])
        assert hits == []

    def test_real_span_is_kept(self):
        hits = _spans_to_hits("Lien he anh Tuan phong ke toan nhe", ["anh Tuan phong ke toan"])
        assert len(hits) == 1
        assert hits[0].value == "anh Tuan phong ke toan"


class TestPlaceholderNumbering:
    def test_repeated_email_shares_one_placeholder_number(self, monkeypatch):
        async def fake_ner(*a, **kw):
            return []

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", fake_ner)
        raw = TicketIn(
            subject="lien he an@x.com",
            body="Neu khong lien lac duoc qua an@x.com thi goi dt gium toi voi",
        )
        result = run_mask(raw)
        assert result.subject_masked.count("[EMAIL_1]") == 1
        assert result.body_masked.count("[EMAIL_1]") == 1
        assert "[EMAIL_2]" not in result.body_masked

    def test_distinct_values_get_distinct_numbers(self, monkeypatch):
        async def fake_ner(*a, **kw):
            return []

        monkeypatch.setattr("apps.tickets.services.masking.ollama_ner", fake_ner)
        raw = TicketIn(subject="lien he", body="email 1 la a@x.com, email 2 la b@x.com nhe ban oi")
        result = run_mask(raw)
        assert "[EMAIL_1]" in result.body_masked
        assert "[EMAIL_2]" in result.body_masked
