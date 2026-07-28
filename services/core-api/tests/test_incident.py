"""
Incident Detector — spec §9. `_get_or_create_incident` is the one piece of
this service with real DB reuse logic (everything else is retrieval +
adaptive-threshold arithmetic), so this is where a bug hides: an incident
detected across several tickets in the same batch must resolve to ONE
`Incident` row, not one per ticket that independently trips the
mass-incident condition.
"""

import pytest

from contracts.enums import PIILevel

from apps.tickets.models import Incident, Ticket, TicketEmbedding
from apps.tickets.services.incident import _get_or_create_incident


def make_ticket(reporter, n: int, category=None) -> Ticket:
    ticket = Ticket.objects.create(
        public_id=f"TKT-TEST-{n:03d}",
        reporter=reporter,
        subject_masked=f"Mang noi bo bi ngat quang {n}",
        body_masked="Toan bo may tinh khong vao duoc mang tu sang nay",
        pii_level=PIILevel.ROUTINE.value,
        category=category,
    )
    TicketEmbedding.objects.create(ticket=ticket, model="test", embedding=[0.1] * 1024)
    return ticket


@pytest.mark.django_db
class TestGetOrCreateIncident:
    def test_second_batch_reuses_the_first_incident_not_a_duplicate(self, employee_user):
        # Regression test: the "existing incident" lookup used to filter
        # on the ticket's RAW category (usually None/blank at this stage,
        # since incident detection runs before the router assigns one —
        # spec §1 component map), while newly created incidents were
        # stored under the resolved "other" fallback. Those two values
        # never matched, so every ticket that independently satisfied the
        # mass-incident condition created its own Incident row instead of
        # joining the existing one — defeating spec §9's whole point: one
        # notification with an ETA, not a fragmented picture.
        tickets = [make_ticket(employee_user, n) for n in range(1, 6)]

        first = _get_or_create_incident(tickets[0], similar=tickets, baseline_rate=0.1)
        second = _get_or_create_incident(tickets[1], similar=tickets, baseline_rate=0.1)

        assert first.id == second.id
        assert Incident.objects.count() == 1

    def test_ticket_count_updates_on_reuse(self, employee_user):
        tickets = [make_ticket(employee_user, n) for n in range(10, 14)]

        # ticket_count is stored as len(similar) + 1 (see _get_or_create_incident).
        first = _get_or_create_incident(tickets[0], similar=tickets[:3], baseline_rate=0.1)
        assert first.ticket_count == 4

        _get_or_create_incident(tickets[1], similar=tickets, baseline_rate=0.1)
        first.refresh_from_db()
        assert first.ticket_count == 5

    def test_all_similar_tickets_get_linked_to_the_incident(self, employee_user):
        tickets = [make_ticket(employee_user, n) for n in range(20, 25)]

        incident = _get_or_create_incident(tickets[0], similar=tickets, baseline_rate=0.1)

        for t in tickets:
            t.refresh_from_db()
            assert t.incident_id == incident.id

    def test_different_categories_get_separate_incidents(self, employee_user):
        network_tickets = [make_ticket(employee_user, n, category="network") for n in range(30, 33)]
        hardware_tickets = [make_ticket(employee_user, n, category="hardware") for n in range(40, 43)]

        network_incident = _get_or_create_incident(network_tickets[0], similar=network_tickets, baseline_rate=0.1)
        hardware_incident = _get_or_create_incident(hardware_tickets[0], similar=hardware_tickets, baseline_rate=0.1)

        assert network_incident.id != hardware_incident.id
        assert network_incident.category == "network"
        assert hardware_incident.category == "hardware"
