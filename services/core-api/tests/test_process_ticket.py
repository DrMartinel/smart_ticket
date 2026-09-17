"""
process_ticket — spec §10.3's overarching rule: any degradation must fail
open to a human, never fail silent. AIEngineUnavailable already had that
fallback; the embedding call ahead of it (used for incident/duplicate
detection) did not — an embedding outage there raised an uncaught exception
straight out of the Celery task, leaving the ticket stuck at status="new"
forever with no RoutingDecision and no ReviewItem, invisible to every
queue and dashboard. This is the regression test for that fix.
"""

import httpx
import pytest

from contracts.enums import Branch, PIILevel, ReasonCode

from apps.tickets.models import Ticket
from apps.tickets.tasks import process_ticket


def make_ticket(reporter) -> Ticket:
    return Ticket.objects.create(
        public_id="TKT-TEST-EMB-001",
        reporter=reporter,
        subject_masked="May tinh khong vao duoc mang",
        body_masked="Tu sang nay may tinh cua toi khong ket noi duoc mang noi bo",
        pii_level=PIILevel.ROUTINE.value,
    )


@pytest.mark.django_db
class TestEmbeddingFailureFailsOpenToHitl:
    def test_connect_timeout_produces_hitl_routing_decision(self, employee_user, monkeypatch):
        ticket = make_ticket(employee_user)

        def raise_timeout(text):
            raise httpx.ConnectTimeout("simulated: embedding service unreachable")

        monkeypatch.setattr("apps.tickets.tasks.embed_text", raise_timeout)

        result = process_ticket.apply(args=[ticket.id]).get()

        assert result["branch"] == Branch.HITL.value

        ticket.refresh_from_db()
        decision = ticket.routing_decisions.order_by("-id").first()
        assert decision is not None
        assert decision.branch == Branch.HITL.value
        assert decision.reason_code == ReasonCode.EMBEDDING_UNAVAILABLE.value

        review_item = ticket.review_items.order_by("-id").first()
        assert review_item is not None, "ticket must land in a review queue, not vanish silently"

    def test_ticket_never_left_stuck_at_new_status(self, employee_user, monkeypatch):
        ticket = make_ticket(employee_user)
        monkeypatch.setattr(
            "apps.tickets.tasks.embed_text",
            lambda text: (_ for _ in ()).throw(httpx.ConnectTimeout("simulated")),
        )

        process_ticket.apply(args=[ticket.id]).get()

        ticket.refresh_from_db()
        assert ticket.status != "new"
