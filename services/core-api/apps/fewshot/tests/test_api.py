# pyright: standard
"""
Few-shot endpoints over HTTP. The response schema decides what the web
receives, so the keys are pinned here.
"""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from contracts.enums import PIILevel

from apps.fewshot.models import FewshotExample
from apps.tickets.models import Ticket


@pytest.mark.django_db
def test_active_examples_for_a_category(employee_user, manager_user, technician_user, api_as):
    source = Ticket.objects.create(
        public_id="TKT-FSAPI-001",
        reporter=employee_user,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )
    example = FewshotExample.objects.create(
        source_ticket=source,
        category="network",
        input_text="masked input",
        output_json={"proposed_category": "network"},
        approver=manager_user,
        approved_at=timezone.now(),
        user_confirmed=True,
        expires_at=timezone.now() + timedelta(days=30),
    )

    response = api_as(technician_user).get("/api/fewshot/category/network")

    assert response.status_code == 200
    [row] = response.json()
    assert set(row) == {"id", "category", "input_text", "output_json", "expires_at"}
    assert row["id"] == example.id
    assert row["output_json"] == {"proposed_category": "network"}
    assert datetime.fromisoformat(row["expires_at"]) == example.expires_at.replace(
        microsecond=example.expires_at.microsecond // 1000 * 1000
    )
