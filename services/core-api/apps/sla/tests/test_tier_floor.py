"""A customer's tier raises a ticket's starting priority and never lowers it (F1 BR-F1-16,
AC-F1-13..16)."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from django.conf import settings as django_settings
from pydantic import ValidationError

from apps.audit.models import AuditLog
from apps.infra.models import Customer, CustomerTier
from apps.infra.services.customers import customers
from apps.sla.tests.conftest import FLOOR, handed_off, set_tier_floor
from apps.tickets.models import Incident, Ticket
from config.settings.base import SlaThresholds, TierName

pytestmark = pytest.mark.django_db


def company(people: dict[str, Any], tier: str, name: str = "Sao Mai Logistics") -> Customer:
    return Customer.objects.create(
        name=name, keystone_domain_id=f"domain-{name}", tier=tier, created_by=people["huy"]
    )


def from_customer(people: dict[str, Any], customer: Customer, **fields: Any) -> Ticket:
    return handed_off(people["lan"], customer=customer, customer_lookup="found", **fields)


def open_incident() -> Incident:
    return Incident.objects.create(
        public_id="INC-2026-0042",
        title="Storage outage",
        category="network",
        severity="high",
        detected_by="human",
    )


def test_a_tier_floor_raises_the_rules_priority(clock, people, settings):
    set_tier_floor(settings, FLOOR)

    ticket = from_customer(people, company(people, "enterprise"), category="software")

    assert ticket.priority == FLOOR["enterprise"] == "P2"


def test_a_floor_below_the_rules_priority_never_lowers_it(clock, people, settings):
    set_tier_floor(settings, FLOOR)

    ticket = from_customer(people, company(people, "standard"), category="software")

    assert FLOOR["standard"] == "P4"
    assert ticket.priority == "P3"


def test_the_tier_floor_raises_never_lowers(clock, people):
    incident = open_incident()

    started = {
        tier.value: from_customer(
            people, company(people, tier.value, name=tier.value), incident=incident
        ).priority
        for tier in CustomerTier
    }

    assert started == {tier.value: "P1" for tier in CustomerTier}


@pytest.mark.parametrize("lookup", ["none", "unavailable"])
def test_no_customer_means_no_floor(clock, people, lookup):
    ticket = handed_off(people["lan"], category="software", customer_lookup=lookup)

    assert ticket.priority == "P3"


def test_a_tier_missing_from_the_floor_map_gets_no_floor(clock, people, settings):
    set_tier_floor(settings, {"business": "P3"})

    ticket = from_customer(people, company(people, "enterprise"), category="software")

    assert ticket.priority == "P3"


def test_a_tier_change_keeps_a_handed_off_tickets_priority(clock, people, settings):
    set_tier_floor(settings, FLOOR)
    sao_mai = company(people, "enterprise")
    first = from_customer(people, sao_mai, category="software")

    customers.change(people["huy"], sao_mai.id, {"tier": "standard", "reason": "Downgraded"})
    first.refresh_from_db()
    second = from_customer(people, sao_mai, category="software")

    assert first.priority == "P2"
    assert second.priority == "P3"


def test_sla_started_records_the_rule_priority_and_floor(clock, people, settings):
    set_tier_floor(settings, FLOOR)
    ticket = from_customer(people, company(people, "enterprise"), category="software")

    started = AuditLog.objects.get(event="sla_started", ticket_id=ticket.id).payload

    assert started["priority"] == "P2"
    assert started["rule_priority"] == "P3"
    assert started["tier"] == "enterprise"
    assert started["floor"] == "P2"


def test_thresholds_refuse_a_tier_floor_outside_p1_to_p4():
    for floor in ({"enterprise": "P0"}, {"enterprise": "high"}, {"platinum": "P2"}):
        with pytest.raises(ValidationError):
            SlaThresholds.model_validate(
                {
                    "warn_at_percent": 75,
                    "escalate_at_percent": 125,
                    "holidays_reminder_month_day": "12-01",
                    "tier_floor": floor,
                }
            )


def test_the_shipped_tier_floor_names_every_tier():
    tiers = {tier.value for tier in CustomerTier}

    assert set(get_args(TierName)) == tiers
    assert set(django_settings.THRESHOLDS.sla.tier_floor) == tiers
