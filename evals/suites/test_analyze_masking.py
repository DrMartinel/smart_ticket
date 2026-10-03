"""
`analyze()` sends ai-engine what core-api's pipeline sends it: the ticket
after `mask()`, with the PII level masking found. Offline: masking's NER and
ai-engine are both faked, so this pins the harness wiring, not model output.

Before, the harness sent raw text as "masked" with the level pinned to
routine, so the router's `pii_critical` gate never fired in an eval and
g144's raw password was auto-replied (evals/HISTORY.md, 2026-10-04).
"""

from __future__ import annotations

import json

import httpx
import pytest

from suites.golden_utils import analyze


def _capturing_client() -> tuple[httpx.Client, list[dict]]:
    """An ai-engine stand-in that records each /v1/analyze body."""
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"signals": {}, "proposal": None})

    return httpx.Client(base_url="http://ai-engine", transport=httpx.MockTransport(handler)), sent


def _fake_ner(spans: list[str]):
    async def fake(text, timeout=None):
        return [s for s in spans if s in text]

    return fake


def test_raw_password_reaches_ai_engine_masked_and_critical(monkeypatch):
    """g144's shape. Critical PII short-circuits before NER, as in
    production, and its level is what lets the router block."""

    async def ner_must_not_run(*a, **kw):
        raise AssertionError("NER called on a critical ticket")

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", ner_must_not_run)
    client, sent = _capturing_client()

    analyze(client, "Can't sign in", "password: Summer2024! doesn't work on the access portal")

    ticket = sent[0]["ticket"]
    assert ticket["pii_level"] == "critical"
    assert "Summer2024!" not in ticket["body_masked"]
    assert ticket["placeholder_keys"] == ["[PASSWORD_1]"]


def test_routine_pii_is_masked_before_ai_engine_sees_it(monkeypatch):
    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", _fake_ner(["anh Tuan"]))
    client, sent = _capturing_client()

    analyze(client, "Reset please", "I am anh Tuan, mail me at an.nguyen@example.com")

    ticket = sent[0]["ticket"]
    assert ticket["pii_level"] == "routine"
    assert ticket["body_masked"] == "I am [FREEFORM_1], mail me at [EMAIL_1]"
    assert sorted(ticket["placeholder_keys"]) == ["[EMAIL_1]", "[FREEFORM_1]"]


@pytest.mark.parametrize("error", [TimeoutError("ner timed out"), RuntimeError("ner down")])
def test_ner_failure_is_sent_as_mask_failed_not_routine(monkeypatch, error):
    """A masking failure must reach the router as `mask_failed` (HITL), never
    as the routine level the harness used to assume."""
    from apps.tickets.utils.masking import NERError

    async def failing(*a, **kw):
        raise error if isinstance(error, TimeoutError) else NERError(str(error))

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", failing)
    client, sent = _capturing_client()

    analyze(client, "Printer jam", "The printer on floor 3 jams every morning")

    assert sent[0]["ticket"]["pii_level"] == "mask_failed"
