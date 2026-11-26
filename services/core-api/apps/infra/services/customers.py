"""Customer companies and their tiers (F17 §o, ADR-0048 decision 11), and the customer a ticket
is stamped with when its pipeline starts (BR-F17-21..23)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.infra.clients.backends import BackendNotFound, BackendUnavailable, openstack
from apps.infra.domain.vocabulary import InfraError, InfraRefusal
from apps.infra.models import Customer, CustomerLookup, InfraBackend
from apps.infra.services.scope import keystone_user
from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)

_FIELDS = ("name", "tier")


@dataclass(frozen=True)
class Domain:
    id: str
    name: str


@dataclass(frozen=True)
class CustomerListing:
    customers: list[Customer]
    unclaimed_domains: list[Domain]
    domains_unavailable: bool


class Customers:
    """Lists, adds and changes customers, each change with a reason and audited; stamps a
    ticket with its reporter's customer."""

    def listing(self) -> CustomerListing:
        """Every customer, and Keystone's domains that have none; the customers alone, marked
        `domains_unavailable`, when Keystone can't answer."""
        rows = list(Customer.objects.select_related("created_by"))
        try:
            domains = self.domains()
        except BackendUnavailable as e:
            logger.warning("infra: Keystone's domains are unavailable: %s", e)
            return CustomerListing(rows, [], domains_unavailable=True)
        claimed = {c.keystone_domain_id for c in rows}
        unclaimed = [d for d in domains if d.id not in claimed]
        return CustomerListing(rows, unclaimed, domains_unavailable=False)

    def domains(self) -> list[Domain]:
        """Keystone's domains; raises `BackendUnavailable` when Keystone can't answer."""
        try:
            found = openstack().get("identity", "/domains")
            return sorted(
                (Domain(d["id"], d["name"]) for d in found["domains"]), key=lambda d: d.name
            )
        except BackendNotFound as e:
            raise BackendUnavailable(InfraBackend.CLOUD, "Keystone lists no domains") from e
        except (KeyError, TypeError) as e:
            raise BackendUnavailable(InfraBackend.CLOUD, "Keystone's answer is unreadable") from e

    def create(self, actor: User, data: dict[str, Any]) -> Customer:
        """Adds a customer for one of Keystone's domains and audits `customer_created`."""
        reason = self.reason_of(data)
        domain_id, name = data["domain_id"], data["name"]
        if Customer.objects.filter(Q(keystone_domain_id=domain_id) | Q(name=name)).exists():
            raise InfraError(InfraRefusal.CUSTOMER_EXISTS, "that domain or name has a customer")
        try:
            known = {d.id for d in self.domains()}
        except BackendUnavailable as e:
            raise InfraError(
                InfraRefusal.SCOPE_UNAVAILABLE, "Keystone can't list its domains"
            ) from e
        if domain_id not in known:
            raise InfraError(InfraRefusal.UNKNOWN_DOMAIN, f"Keystone lists no domain {domain_id!r}")
        try:
            with transaction.atomic():
                customer = Customer.objects.create(
                    name=name, keystone_domain_id=domain_id, tier=data["tier"], created_by=actor
                )
                AuditLog.objects.record(
                    "customer_created",
                    actor_type="human",
                    actor_id=actor.id,
                    payload={
                        "customer": str(customer.id),
                        "reason": reason,
                        **self.snapshot(customer),
                    },
                )
        except IntegrityError as e:
            raise InfraError(
                InfraRefusal.CUSTOMER_EXISTS, "that domain or name has a customer"
            ) from e
        return customer

    def change(self, actor: User, customer_id: uuid.UUID, data: dict[str, Any]) -> Customer:
        """Applies the given `name` and `tier` and audits `customer_changed`; tickets already
        handed off keep their priority (BR-F1-16)."""
        reason = self.reason_of(data)
        try:
            with transaction.atomic():
                customer = Customer.objects.select_for_update().filter(id=customer_id).first()
                if customer is None:
                    raise InfraError(InfraRefusal.NOT_FOUND, "no such customer")
                before = self.snapshot(customer)
                changed = {
                    name: data[name]
                    for name in _FIELDS
                    if data.get(name) is not None and data[name] != getattr(customer, name)
                }
                if not changed:
                    return customer
                for name, value in changed.items():
                    setattr(customer, name, value)
                customer.save(update_fields=[*changed, "updated_at"])
                AuditLog.objects.record(
                    "customer_changed",
                    actor_type="human",
                    actor_id=actor.id,
                    payload={
                        "customer": str(customer.id),
                        "reason": reason,
                        "before": before,
                        "after": self.snapshot(customer),
                    },
                )
        except IntegrityError as e:
            raise InfraError(InfraRefusal.CUSTOMER_EXISTS, "another customer has that name") from e
        return customer

    def stamp(self, ticket: Ticket) -> None:
        """Records `ticket`'s customer and how the lookup went, unless an earlier run found one
        or found there was none (BR-F17-23); records `unavailable` and audits
        `customer_lookup_failed` when the lookup fails for any reason (BR-F17-21)."""
        if ticket.customer_lookup in (CustomerLookup.FOUND, CustomerLookup.NONE):
            return
        try:
            with transaction.atomic():
                lookup, customer = self.of(ticket.reporter)
        except Exception as e:  # noqa: BLE001 — a failed lookup is unavailable, never a stuck ticket
            logger.warning("infra: customer lookup failed for %s: %r", ticket.public_id, e)
            lookup, customer = CustomerLookup.UNAVAILABLE, None
            AuditLog.objects.record(
                "customer_lookup_failed",
                actor_type="system",
                ticket_id=ticket.id,
                payload={
                    "ticket_public_id": ticket.public_id,
                    "error": f"{type(e).__name__}: {e}",
                },
            )
        ticket.customer, ticket.customer_lookup = customer, lookup.value
        ticket.save(update_fields=["customer", "customer_lookup"])

    def of(self, reporter: User) -> tuple[CustomerLookup, Customer | None]:
        """The customer whose Keystone domain holds `reporter`'s Keystone user, or none
        (BR-F17-21, BR-F17-23)."""
        if not reporter.external_id or not Customer.objects.exists():
            return CustomerLookup.NONE, None
        found = keystone_user(reporter, openstack())
        if found is None:
            return CustomerLookup.NONE, None
        customer = Customer.objects.filter(keystone_domain_id=found.domain_id).first()
        return (CustomerLookup.FOUND, customer) if customer else (CustomerLookup.NONE, None)

    def snapshot(self, customer: Customer) -> dict[str, str]:
        return {
            "name": customer.name,
            "tier": customer.tier,
            "keystone_domain_id": customer.keystone_domain_id,
        }

    def reason_of(self, data: dict[str, Any]) -> str:
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise InfraError(InfraRefusal.REASON_REQUIRED, "say why")
        return reason


customers = Customers()
