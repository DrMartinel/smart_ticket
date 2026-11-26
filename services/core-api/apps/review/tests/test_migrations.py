"""Migration 0005: a ticket handed off on a confirmed category before that category was saved gets
it; no other ticket changes."""

from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest
from django.apps import apps as django_apps

from apps.review.models import ReviewDecision, ReviewItem
from apps.review.tests.test_decide import SHOWN_ACCESS, SHOWN_NONE, review_item
from apps.tickets.models import Ticket

backfill = import_module("apps.review.migrations.0005_backfill_confirmed_category").backfill


def decided(
    item: ReviewItem,
    reviewer,
    *,
    action: str = "approve",
    verdict: str | None = "correct",
    corrected: str | None = None,
) -> ReviewItem:
    """`item` with one recorded decision, as `decide` wrote it before the category was saved."""
    ReviewDecision.objects.create(
        review_item=item,
        reviewer=reviewer,
        action_taken=action,
        category_verdict=verdict,
        corrected_category=corrected,
        override_reason=None if action == "approve" else "a reason",
        time_spent_sec=10,
    )
    return item


@pytest.mark.django_db
def test_a_ticket_handed_off_on_a_confirmed_category_gets_it(employee_user, technician_user):
    item = decided(review_item(employee_user, trust_signals=SHOWN_ACCESS), technician_user)

    backfill(django_apps, None)

    assert Ticket.objects.get(pk=item.ticket_id).category == "access"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "ticket, decision",
    [
        pytest.param({"category": "network"}, {}, id="has_a_category"),
        pytest.param({"queue": "injection"}, {}, id="injection_queue"),
        pytest.param({"queue": "pii_verify"}, {}, id="pii_verify_queue"),
        pytest.param({"trust_signals": SHOWN_NONE}, {}, id="no_category_choice"),
        pytest.param({}, {"verdict": None}, id="incident_confirmation"),
        pytest.param({}, {"corrected": "network"}, id="corrected"),
        pytest.param({}, {"action": "reject"}, id="rejected"),
    ],
)
def test_a_ticket_without_a_confirmed_handoff_is_left_as_it_is(
    employee_user, technician_user, ticket: dict[str, Any], decision: dict[str, Any]
):
    fields = {"trust_signals": SHOWN_ACCESS, **ticket}
    item = decided(review_item(employee_user, **fields), technician_user, **decision)

    backfill(django_apps, None)

    assert Ticket.objects.get(pk=item.ticket_id).category == fields.get("category")


@pytest.mark.django_db
def test_a_ticket_with_no_run_is_left_without_a_category(employee_user, technician_user):
    item = review_item(employee_user, trust_signals=SHOWN_ACCESS)
    item.ai_run = None
    item.save(update_fields=["ai_run"])
    decided(item, technician_user)

    backfill(django_apps, None)

    assert Ticket.objects.get(pk=item.ticket_id).category is None
