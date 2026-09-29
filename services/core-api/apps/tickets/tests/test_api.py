"""
Ticket reads over HTTP. `category` is null until the ticket is classified,
and the response schema must allow that: typed too strictly, a new ticket
cannot be opened. The submit response is pinned in test_submit_ticket.py.
"""

import pytest

from apps.tickets.utils.patterns import PIILevel

from apps.tickets.models import Ticket


@pytest.mark.django_db
def test_an_unclassified_ticket(employee_user, api_as):
    Ticket.objects.create(
        public_id="TKT-API-001",
        reporter=employee_user,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )

    response = api_as(employee_user).get("/api/tickets/TKT-API-001")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "public_id",
        "subject_masked",
        "body_masked",
        "pii_level",
        "status",
        "category",
        "created_at",
    }
    assert body["category"] is None


@pytest.mark.django_db
def test_an_unknown_ticket_is_a_404(employee_user, api_as):
    response = api_as(employee_user).get("/api/tickets/TKT-NOPE")

    assert response.status_code == 404
    assert response.json() == {"detail": "ticket not found"}
