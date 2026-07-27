"""
Masking engine — spec §5. This is the P0 exit condition (spec §14:
"masking test coverage 100%"), so every branch of the two-tier pipeline is
covered: critical short-circuit, Ollama success, Ollama timeout/error
(MASK_FAILED, never silently "clean"), and placeholder numbering.
"""

from asgiref.sync import async_to_sync

from contracts.enums import PIILevel
from contracts.ticket import TicketIn

from apps.tickets.services.masking import OllamaError, mask, regex_scan, regex_scan_ticket


def run_mask(raw: TicketIn):
    return async_to_sync(mask)(raw)


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
