"""Customers: the lookup that stamps a ticket with its reporter's company, and the routes a
manager adds and changes customers with (F17 §o, BR-F17-21..23, UC-F17-10, UC-F17-11)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from cloud_sim.cloud import User as SimUser
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.incidents.services.incidents import incidents
from apps.infra.clients.backends import OpenStack
from apps.infra.models import Customer, CustomerLookup
from apps.infra.services import customers as customers_module
from apps.infra.services.customers import customers
from apps.infra.tests.conftest import LAN_SUBJECT, CloudSim, mock_http
from apps.tickets.domain.patterns import PIILevel
from apps.tickets.domain.router import Branch
from apps.tickets.models import IncidentVerdict, Ticket
from apps.tickets.tasks import process_ticket
from apps.tickets.testing import nothing_found
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import AIRunResponse, LLMProposalEnvelope

pytestmark = pytest.mark.django_db

SAO_MAI = "8fed0033-eaa7-5729-9e9c-824134fb7ac2"
HOA_BINH = "52c86fa9-0f2c-52f7-882e-15b1696ab041"
JSON = "application/json"


@pytest.fixture
def lan(employee_user: User) -> User:
    """lan.nt, whose Keystone user is in the Sao Mai Logistics domain."""
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    return employee_user


def customer(manager: User, domain_id: str, name: str, tier: str = "enterprise") -> Customer:
    return Customer.objects.create(
        name=name, keystone_domain_id=domain_id, tier=tier, created_by=manager
    )


def ticket_from(reporter: User, number: int = 1) -> Ticket:
    return Ticket.objects.create(
        public_id=f"TKT-CUST-{number:06d}",
        reporter=reporter,
        subject_masked="db-01 chậm từ sáng",
        body_masked="Database của chúng tôi phản hồi rất chậm",
        pii_level=PIILevel.ROUTINE.value,
    )


def keystone_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Keystone is down")

    monkeypatch.setattr(customers_module, "openstack", lambda: OpenStack(mock_http(refuse)))


def insufficient_context_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes ai-engine find a close page but propose insufficient context, which the router
    hands to a person."""

    def answer(masked: Any, request_id: str, categories: Any) -> AIRunResponse:
        signals = nothing_found()
        signals.retrieval.rerank_top1 = 0.9
        signals.retrieval.rerank_total = 0.95
        return AIRunResponse(
            request_id=request_id,
            graph_version="test",
            prompt_version="test",
            model="test",
            proposal=LLMProposalEnvelope.model_validate(
                {
                    "proposed_intent": "insufficient_context",
                    "missing_information": "which database is slow",
                }
            ),
            signals=signals,
        )

    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(ai_engine, "analyze", answer)


# ── the lookup ──


def test_keystone_down_at_customer_lookup_never_blocks_the_pipeline(lan, manager_user, monkeypatch):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    keystone_down(monkeypatch)
    insufficient_context_answers(monkeypatch)
    ticket = ticket_from(lan)

    result = process_ticket.apply(args=(ticket.id,)).get()

    ticket.refresh_from_db()
    assert result["branch"] == Branch.HITL.value
    assert ticket.customer is None
    assert ticket.customer_lookup == CustomerLookup.UNAVAILABLE
    failed = AuditLog.objects.get(event="customer_lookup_failed")
    assert failed.ticket_id == ticket.id


def test_customer_never_changes_the_decision(lan, manager_user, cloud_sim: CloudSim, monkeypatch):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    insufficient_context_answers(monkeypatch)
    with_customer = ticket_from(lan, 1)
    process_ticket.apply(args=(with_customer.id,)).get()
    lan.external_id = None
    lan.save(update_fields=["external_id"])
    without = ticket_from(lan, 2)
    process_ticket.apply(args=(without.id,)).get()

    with_customer.refresh_from_db()
    without.refresh_from_db()
    assert with_customer.customer_lookup == CustomerLookup.FOUND
    assert without.customer_lookup == CustomerLookup.NONE
    decided = [
        (
            t.routing_decisions.values(
                "branch", "reason_code", "reason_detail", "gate_failed"
            ).get(),
            list(t.review_items.values_list("queue", "priority")),
        )
        for t in (with_customer, without)
    ]
    assert decided[0] == decided[1]


def test_no_customer_rows_means_no_lookup(lan, cloud_sim: CloudSim):
    ticket = ticket_from(lan)

    customers.stamp(ticket)

    assert ticket.customer_lookup == CustomerLookup.NONE
    assert cloud_sim.calls == []


def test_a_reporter_with_no_keycloak_subject_is_none_without_asking_keystone(
    employee_user, manager_user, cloud_sim: CloudSim
):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    ticket = ticket_from(employee_user)

    customers.stamp(ticket)

    assert ticket.customer_lookup == CustomerLookup.NONE
    assert cloud_sim.calls == []


def test_the_reporters_keystone_domain_gives_the_ticket_its_customer(
    lan, manager_user, cloud_sim: CloudSim
):
    sao_mai = customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    customer(manager_user, HOA_BINH, "Hoa Binh Retail", tier="standard")
    ticket = ticket_from(lan)

    customers.stamp(ticket)

    ticket.refresh_from_db()
    assert ticket.customer == sao_mai
    assert ticket.customer_lookup == CustomerLookup.FOUND


def test_a_domain_with_no_customer_row_is_none(lan, manager_user, cloud_sim: CloudSim):
    customer(manager_user, HOA_BINH, "Hoa Binh Retail", tier="standard")
    ticket = ticket_from(lan)

    customers.stamp(ticket)

    assert ticket.customer is None
    assert ticket.customer_lookup == CustomerLookup.NONE


def test_two_keystone_users_for_one_subject_is_unavailable(lan, manager_user, cloud_sim: CloudSim):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    cloud_sim.cloud.users["twin"] = SimUser("twin", "lan.twin", HOA_BINH, LAN_SUBJECT)
    ticket = ticket_from(lan)

    customers.stamp(ticket)

    assert ticket.customer is None
    assert ticket.customer_lookup == CustomerLookup.UNAVAILABLE


def test_a_rerun_looks_again_only_after_unavailable(
    lan, manager_user, cloud_sim: CloudSim, monkeypatch
):
    sao_mai = customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    ticket = ticket_from(lan)
    with monkeypatch.context() as down:
        keystone_down(down)
        customers.stamp(ticket)
    assert ticket.customer_lookup == CustomerLookup.UNAVAILABLE

    customers.stamp(ticket)
    assert ticket.customer == sao_mai
    looked = len(cloud_sim.calls)

    sao_mai.keystone_domain_id = HOA_BINH
    sao_mai.save(update_fields=["keystone_domain_id"])
    customers.stamp(ticket)
    assert len(cloud_sim.calls) == looked
    assert ticket.customer == sao_mai


def test_the_database_refuses_a_customer_without_a_found_lookup(lan, manager_user):
    sao_mai = customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    ticket = ticket_from(lan)

    for lookup in (None, CustomerLookup.NONE, CustomerLookup.UNAVAILABLE):
        with pytest.raises(IntegrityError), transaction.atomic():
            Ticket.objects.filter(id=ticket.id).update(customer=sao_mai, customer_lookup=lookup)


def test_the_database_refuses_found_without_a_customer(lan):
    ticket = ticket_from(lan)

    with pytest.raises(IntegrityError), transaction.atomic():
        Ticket.objects.filter(id=ticket.id).update(customer_lookup=CustomerLookup.FOUND)


# ── the ticket page ──


def test_the_ticket_page_shows_the_customer_and_its_tier(
    lan, manager_user, technician_user, api_as
):
    sao_mai = customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    ticket = ticket_from(lan)
    Ticket.objects.filter(id=ticket.id).update(customer=sao_mai, customer_lookup="found")

    detail = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/detail").json()

    assert detail["customer"] == {"name": "Sao Mai Logistics", "tier": "enterprise"}
    assert detail["customer_lookup"] == "found"


def test_the_ticket_page_says_when_the_lookup_failed(lan, technician_user, api_as):
    ticket = ticket_from(lan)
    Ticket.objects.filter(id=ticket.id).update(customer_lookup="unavailable")

    detail = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/detail").json()

    assert detail["customer"] is None
    assert detail["customer_lookup"] == "unavailable"


# ── the routes ──


def body(**overrides: Any) -> dict[str, Any]:
    return {
        "domain_id": SAO_MAI,
        "name": "Sao Mai Logistics",
        "tier": "enterprise",
        "reason": "Enterprise contract signed 2026-11-20",
        **overrides,
    }


def test_customer_routes_refuse_a_person_without_the_permission(technician_user, api_as):
    client = api_as(technician_user)

    replies = [
        client.get("/api/infra/customers"),
        client.post("/api/infra/customers", content_type=JSON, data=body()),
        client.patch(
            f"/api/infra/customers/{SAO_MAI}",
            content_type=JSON,
            data={"tier": "standard", "reason": "x"},
        ),
    ]

    assert [r.status_code for r in replies] == [403, 403, 403]
    assert not Customer.objects.exists()


def test_adding_a_customer_needs_a_reason(manager_user, api_as, cloud_sim: CloudSim):
    reply = api_as(manager_user).post(
        "/api/infra/customers", content_type=JSON, data=body(reason="  ")
    )

    assert reply.status_code == 422
    assert reply.json()["code"] == "reason_required"
    assert not Customer.objects.exists()


def test_a_domain_keystone_does_not_list_is_refused(manager_user, api_as, cloud_sim: CloudSim):
    reply = api_as(manager_user).post(
        "/api/infra/customers", content_type=JSON, data=body(domain_id="no-such")
    )

    assert reply.status_code == 422
    assert reply.json()["code"] == "unknown_domain"


def test_a_second_customer_for_a_domain_or_a_name_is_refused(
    manager_user, api_as, cloud_sim: CloudSim
):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    client = api_as(manager_user)

    same_domain = client.post(
        "/api/infra/customers", content_type=JSON, data=body(name="Sao Mai 2")
    )
    same_name = client.post(
        "/api/infra/customers", content_type=JSON, data=body(domain_id=HOA_BINH)
    )

    assert [same_domain.status_code, same_name.status_code] == [409, 409]
    assert {same_domain.json()["code"], same_name.json()["code"]} == {"customer_exists"}
    assert Customer.objects.count() == 1


def test_adding_a_customer_while_keystone_is_down_is_refused(manager_user, api_as, monkeypatch):
    keystone_down(monkeypatch)

    reply = api_as(manager_user).post("/api/infra/customers", content_type=JSON, data=body())

    assert reply.status_code == 424
    assert reply.json()["code"] == "infra_scope_unavailable"
    assert not Customer.objects.exists()


def test_adding_a_customer_audits_its_reason(manager_user, api_as, cloud_sim: CloudSim):
    reply = api_as(manager_user).post("/api/infra/customers", content_type=JSON, data=body())

    assert reply.status_code == 201
    assert reply.json()["tier"] == "enterprise"
    created = AuditLog.objects.get(event="customer_created")
    assert created.payload["reason"] == "Enterprise contract signed 2026-11-20"
    assert created.payload["keystone_domain_id"] == SAO_MAI


def test_the_listing_marks_the_domains_with_no_customer(manager_user, api_as, cloud_sim: CloudSim):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")

    listing = api_as(manager_user).get("/api/infra/customers").json()

    assert [c["name"] for c in listing["customers"]] == ["Sao Mai Logistics"]
    unclaimed = {d["id"] for d in listing["unclaimed_domains"]}
    assert HOA_BINH in unclaimed and SAO_MAI not in unclaimed
    assert listing["domains_unavailable"] is False


def test_the_listing_still_shows_customers_when_keystone_is_down(manager_user, api_as, monkeypatch):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    keystone_down(monkeypatch)

    reply = api_as(manager_user).get("/api/infra/customers")

    assert reply.status_code == 200
    assert [c["name"] for c in reply.json()["customers"]] == ["Sao Mai Logistics"]
    assert reply.json()["unclaimed_domains"] == []
    assert reply.json()["domains_unavailable"] is True


def test_a_change_needs_a_reason_and_audits_before_and_after(manager_user, api_as):
    sao_mai = customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    client = api_as(manager_user)

    refused = client.patch(
        f"/api/infra/customers/{sao_mai.id}", content_type=JSON, data={"tier": "standard"}
    )
    changed = client.patch(
        f"/api/infra/customers/{sao_mai.id}",
        content_type=JSON,
        data={"tier": "standard", "reason": "Contract downgraded"},
    )

    assert refused.status_code == 422
    assert refused.json()["code"] == "reason_required"
    assert changed.status_code == 200
    assert changed.json()["tier"] == "standard"
    audit = AuditLog.objects.get(event="customer_changed")
    assert audit.payload["reason"] == "Contract downgraded"
    assert audit.payload["before"]["tier"] == "enterprise"
    assert audit.payload["after"]["tier"] == "standard"


def test_changing_a_customer_that_does_not_exist_is_404(manager_user, api_as):
    reply = api_as(manager_user).patch(
        "/api/infra/customers/00000000-0000-0000-0000-000000000000",
        content_type=JSON,
        data={"tier": "standard", "reason": "x"},
    )

    assert reply.status_code == 404
    assert reply.json()["code"] == "infra_not_found"


def test_renaming_onto_another_customers_name_is_refused(manager_user, api_as):
    customer(manager_user, SAO_MAI, "Sao Mai Logistics")
    hoa_binh = customer(manager_user, HOA_BINH, "Hoa Binh Retail", tier="standard")

    reply = api_as(manager_user).patch(
        f"/api/infra/customers/{hoa_binh.id}",
        content_type=JSON,
        data={"name": "Sao Mai Logistics", "reason": "typo"},
    )

    assert reply.status_code == 409
    assert reply.json()["code"] == "customer_exists"
    hoa_binh.refresh_from_db()
    assert hoa_binh.name == "Hoa Binh Retail"
    assert not AuditLog.objects.filter(event="customer_changed").exists()
