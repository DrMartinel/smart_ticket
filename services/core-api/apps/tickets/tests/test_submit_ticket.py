"""
Ticket submission — spec §5's inline-masking contract, end to end over
HTTP. By the time submit returns, the `tickets` row holds ONLY masked
text, `pii_quarantine` holds the raw values encrypted, the submission is
audited, and processing has been handed to Celery.

A regression here does not fail loudly: raw PII landing in `tickets`, or a
masking failure that drops the ticket instead of routing it to a human, both
look like a successful submit to the caller.
"""

import pytest
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.tickets.utils.patterns import PIILevel

from apps.audit.models import AuditLog
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.utils.crypto import decrypt

EMAIL = "an.nguyen@example.com"
PHONE = "0912345678"


class FakeProcessTicket:
    """Stands in for the Celery task: records what was enqueued, and whether
    the enqueue happened inside a still-open transaction."""

    def __init__(self):
        self.enqueued: list[int] = []
        self.enqueued_inside_transaction: list[bool] = []

    def delay(self, ticket_id: int) -> None:
        self.enqueued.append(ticket_id)
        self.enqueued_inside_transaction.append(connection.in_atomic_block)


@pytest.fixture
def process_ticket(monkeypatch):
    fake = FakeProcessTicket()
    monkeypatch.setattr("apps.tickets.tasks.process_ticket", fake)
    return fake


@pytest.fixture
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


def submit(client, subject: str, body: str, trace_id: str = "trace-abc"):
    """POSTs over HTTP; TraceIdMiddleware picks the trace_id up from the header."""
    return client.post(
        "/api/tickets/submit",
        {"subject": subject, "body": body},
        content_type="application/json",
        HTTP_X_TRACE_ID=trace_id,
    )


@pytest.mark.django_db
class TestSubmitPersistsOnlyMaskedText:
    def test_tickets_row_holds_placeholders_not_raw_values(
        self, employee_user, process_ticket, ner_finds_nothing, api_as
    ):
        """The core §5 guarantee: nothing raw is ever written to `tickets`."""
        response = submit(
            api_as(employee_user), f"Loi email {EMAIL}", f"Goi lai cho toi so {PHONE} nhe"
        )

        ticket = Ticket.objects.get(public_id=response.json()["ticket_public_id"])
        assert EMAIL not in ticket.subject_masked
        assert PHONE not in ticket.body_masked
        assert "[EMAIL_1]" in ticket.subject_masked
        assert "[PHONE_VN_1]" in ticket.body_masked
        assert ticket.pii_level == PIILevel.ROUTINE.value
        assert ticket.reporter_id == employee_user.id
        assert response.status_code == 200
        assert response.json() == {
            "ticket_public_id": ticket.public_id,
            "status": "new",
            "pii_level": PIILevel.ROUTINE.value,
        }

    def test_quarantine_rows_decrypt_to_the_raw_values(
        self, employee_user, process_ticket, ner_finds_nothing, api_as
    ):
        """`pii_map` points each placeholder at a quarantine ref, and that ref
        decrypts back to exactly the value it replaced, with the §3.1 TTL."""
        before = timezone.now()
        response = submit(
            api_as(employee_user), f"Loi email {EMAIL}", f"Goi lai cho toi so {PHONE} nhe"
        )
        after = timezone.now()

        ticket = Ticket.objects.get(public_id=response.json()["ticket_public_id"])
        rows = {str(q.ref): q for q in PiiQuarantine.objects.filter(ticket=ticket)}
        assert set(ticket.pii_map) == {"[EMAIL_1]", "[PHONE_VN_1]"}
        assert set(ticket.pii_map.values()) == set(rows)

        raw = {
            ph: decrypt(bytes(rows[ref].ciphertext), bytes(rows[ref].nonce))
            for ph, ref in ticket.pii_map.items()
        }
        assert raw == {"[EMAIL_1]": EMAIL, "[PHONE_VN_1]": PHONE}

        ttl = timedelta(hours=settings.PII_QUARANTINE_TTL_HOURS)
        for row in rows.values():
            assert before + ttl <= row.expires_at <= after + ttl

    def test_submission_is_audited_with_the_request_trace_id(
        self, employee_user, process_ticket, ner_finds_nothing, api_as
    ):
        response = submit(
            api_as(employee_user), "May in bi hong", "May in tang 2 khong in duoc tu sang"
        )

        ticket = Ticket.objects.get(public_id=response.json()["ticket_public_id"])
        entry = AuditLog.objects.get(event="ticket_submitted", ticket_id=ticket.id)
        assert entry.actor_type == "human"
        assert entry.actor_id == employee_user.id
        assert entry.trace_id == "trace-abc"
        assert entry.payload == {
            "ticket_public_id": ticket.public_id,
            "pii_level": PIILevel.ROUTINE.value,
            "source": "form",
            "trace_id": "trace-abc",
        }


@pytest.mark.django_db(transaction=True)
def test_processing_is_enqueued_only_after_the_ticket_commits(
    employee_user, process_ticket, ner_finds_nothing, api_as
):
    """Enqueueing inside the transaction would let a fast worker look the
    ticket up before it is committed, fail with DoesNotExist, and leave it
    stuck at status="new" with no routing decision."""
    response = submit(
        api_as(employee_user), "May in bi hong", "May in tang 2 khong in duoc tu sang"
    )

    ticket = Ticket.objects.get(public_id=response.json()["ticket_public_id"])
    assert process_ticket.enqueued == [str(ticket.id)]
    assert process_ticket.enqueued_inside_transaction == [False]


@pytest.mark.django_db
def test_ner_failure_still_files_the_ticket_as_mask_failed(
    employee_user, process_ticket, monkeypatch, api_as
):
    """A masking failure degrades toward a human: the ticket is stored with
    what regex could mask, flagged MASK_FAILED (the router's HITL gate), and
    still enqueued — never dropped, never treated as clean."""

    async def raise_timeout(*a, **kw):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", raise_timeout)
    response = submit(
        api_as(employee_user), f"Loi email {EMAIL}", "Toi can ho tro voi thiet bi cua minh"
    )

    ticket = Ticket.objects.get(public_id=response.json()["ticket_public_id"])
    assert ticket.pii_level == PIILevel.MASK_FAILED.value
    assert EMAIL not in ticket.subject_masked
    assert process_ticket.enqueued == [str(ticket.id)]


@pytest.mark.django_db
def test_invalid_submission_is_rejected_before_masking(
    employee_user, process_ticket, monkeypatch, api_as
):
    """`TicketIn`'s length limits are the real validation; a submission that
    fails them never reaches the NER model and writes nothing."""
    called = False

    async def fake_ner(*a, **kw):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)

    response = submit(api_as(employee_user), "ab", "too short")

    assert response.status_code == 422
    assert called is False
    assert not Ticket.objects.exists()
    assert process_ticket.enqueued == []
