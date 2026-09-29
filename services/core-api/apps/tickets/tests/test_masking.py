"""
Masking engine — spec §5. This is the P0 exit condition (spec §14:
"masking test coverage 100%"), so every branch of the two-tier pipeline is
covered: critical short-circuit, LLM success, LLM timeout/error
(MASK_FAILED, never silently "clean"), and placeholder numbering.
"""

import json

import httpx
import pytest
from asgiref.sync import async_to_sync

from apps.tickets.utils.patterns import PIILevel
from apps.tickets.request_schema import TicketIn

from apps.tickets.utils.masking import (
    NERError,
    _spans_to_hits,
    mask,
    llm_ner,
    regex_scan,
    regex_scan_ticket,
)


def run_mask(raw: TicketIn):
    return async_to_sync(mask)(raw)


def run_ner(text: str):
    return async_to_sync(llm_ner)(text)


def _serve_spans(serve_ai_engine, spans):
    """ai-engine's `/v1/pii/detect` answering with `spans`."""
    return serve_ai_engine(lambda request: httpx.Response(200, json={"spans": spans}))


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
    def test_critical_short_circuits_before_llm(self, monkeypatch):
        called = False

        async def fake_ner(*a, **kw):
            nonlocal called
            called = True
            return []

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)
        raw = TicketIn(subject="quen mat khau", body="password: hunter2 can ho tro gap")
        result = run_mask(raw)

        assert result.pii_level is PIILevel.CRITICAL
        assert "hunter2" not in result.body_masked
        assert called is False, "The LLM must never be called once a CRITICAL hit is found"


class TestMaskLlmTier:
    def test_llm_timeout_becomes_mask_failed_not_clean(self, monkeypatch):
        async def raise_timeout(*a, **kw):
            raise TimeoutError("simulated timeout")

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", raise_timeout)
        raw = TicketIn(
            subject="Van de ky thuat", body="Toi can ho tro voi thiet bi cua minh, xin cam on"
        )
        result = run_mask(raw)

        assert result.pii_level is PIILevel.MASK_FAILED

    def test_llm_error_becomes_mask_failed_not_clean(self, monkeypatch):
        # llm_ner's own contract already converts httpx/JSON errors into
        # NERError before they escape (see masking.py) — that's the
        # exception shape callers of llm_ner actually need to handle.
        async def raise_error(*a, **kw):
            raise NERError("simulated 500")

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", raise_error)
        raw = TicketIn(
            subject="Van de ky thuat", body="May tinh cua toi bi loi man hinh xanh sang nay"
        )
        result = run_mask(raw)

        assert result.pii_level is PIILevel.MASK_FAILED

    def test_llm_success_merges_freeform_hits(self, monkeypatch):
        async def fake_ner(text, timeout=None):
            return ["anh Tuan phong ke toan"] if "Tuan" in text else []

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)
        raw = TicketIn(
            subject="Ho tro", body="Lien he anh Tuan phong ke toan de biet them chi tiet nhe"
        )
        result = run_mask(raw)

        assert "anh Tuan phong ke toan" not in result.body_masked
        assert result.pii_level is not PIILevel.CRITICAL

    def test_no_hits_at_all_stays_routine(self, monkeypatch):
        async def fake_ner(*a, **kw):
            return []

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)
        raw = TicketIn(
            subject="May in bi ket giay", body="May in tren tang 3 bi ket giay tu sang nay"
        )
        result = run_mask(raw)

        assert result.pii_level is PIILevel.ROUTINE
        assert result.placeholder_map == {}

    def test_cccd_hit_escalates_full_mask_to_sensitive(self, monkeypatch):
        async def fake_ner(*a, **kw):
            return []

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)
        raw = TicketIn(
            subject="Xac minh danh tinh", body="So CCCD cua toi la 012345678901, can xac minh gap"
        )
        result = run_mask(raw)

        assert result.pii_level is PIILevel.SENSITIVE
        assert "012345678901" not in result.body_masked


class TestLlmNer:
    """`llm_ner` asks ai-engine (ADR-0012), which owns the prompt and the
    reply parsing (ai-engine `tests/test_pii.py`). What stays here is the
    contract masking relies on: every failure becomes NERError or
    TimeoutError, which `mask` resolves to MASK_FAILED, never to "no PII
    found"."""

    def test_spans_come_from_ai_engine(self, serve_ai_engine):
        calls = _serve_spans(serve_ai_engine, ["anh Tuan phong ke toan"])

        assert run_ner("Lien he anh Tuan phong ke toan") == ["anh Tuan phong ke toan"]
        [request] = calls.requests
        assert request.url.path == "/v1/pii/detect"
        assert json.loads(request.content) == {"text": "Lien he anh Tuan phong ke toan"}

    def test_an_empty_answer_is_passed_through(self, serve_ai_engine):
        _serve_spans(serve_ai_engine, [])
        assert run_ner("...") == []

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(502, json={"detail": "PII NER failed"}),
            httpx.Response(200, json={}),
            httpx.Response(200, json={"spans": None}),
            httpx.Response(200, text="not json at all"),
        ],
        ids=["ai-engine 502", "no spans key", "null spans", "not json"],
    )
    def test_unusable_answer_fails_closed(self, serve_ai_engine, response):
        """A broken answer is not "nothing found". Reading it as [] would
        resolve toward clean — the one direction masking may never fail
        (spec §5.2)."""
        serve_ai_engine(lambda request: response)
        with pytest.raises(NERError):
            run_ner("...")

    def test_transport_timeout_becomes_timeout_error(self, serve_ai_engine):
        # Exercises llm_ner's own httpx.TimeoutException -> TimeoutError
        # conversion — the other timeout test in TestMaskLlmTier mocks
        # llm_ner() wholesale, so it never runs this branch.
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated network timeout")

        serve_ai_engine(handler)
        with pytest.raises(TimeoutError):
            run_ner("...")

    def test_connect_timeout_still_becomes_mask_failed(self, serve_ai_engine):
        """Failing fast must not change the safety property: an
        unreachable ai-engine is still 'we could not verify', never
        'there was no PII'."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("simulated: route blocked, handshake never completes")

        serve_ai_engine(handler)
        raw = TicketIn(subject="May in bi ket giay", body="May in tang 3 bi ket giay tu sang nay")
        assert run_mask(raw).pii_level is PIILevel.MASK_FAILED

    def test_error_message_never_carries_the_text(self, serve_ai_engine):
        """`mask` logs the error. The request and reply are raw PII, and a
        pydantic or httpx error can quote them."""
        text = "Lien he anh Tuan phong ke toan"
        serve_ai_engine(lambda request: httpx.Response(200, json={"spans": [{"v": text}]}))

        with pytest.raises(NERError) as caught:
            run_ner(text)

        assert text not in str(caught.value)


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

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)
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

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)
        raw = TicketIn(subject="lien he", body="email 1 la a@x.com, email 2 la b@x.com nhe ban oi")
        result = run_mask(raw)
        assert "[EMAIL_1]" in result.body_masked
        assert "[EMAIL_2]" in result.body_masked
