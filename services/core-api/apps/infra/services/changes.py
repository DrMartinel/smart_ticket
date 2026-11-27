"""A caller's changes to the cloud's servers, volumes and security groups (F17 §h.1,
BR-F17-08..11): each within the caller's scope and, on a staff route, for an open ticket the
caller works on; sent to the cloud once; audited; and noted on that ticket, whose requester is
told of a change made to their company's resource."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.accounts.domain.access import Access
from apps.accounts.domain.catalog import Permission
from apps.accounts.permissions import Caller
from apps.audit.models import AuditLog
from apps.infra.clients.backends import (
    BackendConflict,
    BackendNotFound,
    BackendRefused,
    BackendUnavailable,
    ChangeOutcomeUnknown,
    OpenStack,
    openstack,
)
from apps.infra.domain.changes import (
    Change,
    ChangeOutcome,
    ChangeTarget,
    InfraChange,
    InfraResource,
    RuleSpec,
)
from apps.infra.domain.resources import Project, Rule, SecurityGroup, Server, Volume
from apps.infra.domain.vocabulary import InfraError, InfraOutcomeUnknown, InfraRefusal
from apps.infra.models import InfraBackend
from apps.infra.services.recording import UNREADABLE, QueryLog
from apps.infra.services.scope import InfraScope
from apps.lifecycle.domain.vocabulary import TRIAGE_STATUSES
from apps.notifications.domain.vocabulary import NotificationEvent
from apps.notifications.services.notifier import Notice, notifier
from apps.teams.services.assignment import TeamError, assignment
from apps.tickets.models import CommentVisibility, Ticket
from apps.tickets.services.comments import comments

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeDone:
    """A change the cloud accepted, and the ticket it was for."""

    change: InfraChange
    target_kind: InfraResource
    target_id: str
    target_name: str
    project_id: str
    ticket: str | None


class InfraChanges:
    """The changes one caller makes to the cloud: every project's on a staff route, each for an
    open ticket; or, on a customer route, their own Keystone projects' with no ticket."""

    def __init__(
        self, caller: Caller, scope: InfraScope, cloud: OpenStack, *, for_a_ticket: bool
    ) -> None:
        self.caller = caller
        self.scope = scope
        self.cloud = cloud
        self.for_a_ticket = for_a_ticket

    @classmethod
    def for_all(cls, caller: Caller) -> InfraChanges:
        """Staff changes on any project, each for an open ticket the caller works on."""
        return cls(caller, InfraScope.all(), openstack(), for_a_ticket=True)

    @classmethod
    def for_own(cls, caller: Caller) -> InfraChanges:
        """Customer changes on the caller's Keystone projects only."""
        cloud = openstack()
        return cls(caller, QueryLog.of(caller).own_scope(cloud), cloud, for_a_ticket=False)

    # ── servers ──

    def reboot(self, server_id: str, *, hard: bool, public_id: str | None = None) -> ChangeDone:
        kind = InfraChange.HARD_REBOOT if hard else InfraChange.SOFT_REBOOT
        return self.server_action(kind, server_id, public_id)

    def start(self, server_id: str, public_id: str | None = None) -> ChangeDone:
        return self.server_action(InfraChange.START, server_id, public_id)

    def stop(self, server_id: str, public_id: str | None = None) -> ChangeDone:
        return self.server_action(InfraChange.STOP, server_id, public_id)

    def server_action(self, kind: InfraChange, server_id: str, public_id: str | None) -> ChangeDone:
        """One Nova server action on a server the caller reaches."""
        ticket = self.ticket(public_id)
        server = self.server(server_id)
        path = f"/servers/{server.id}/action"
        return self.send(
            ticket, Change(kind, server, "POST", "compute", path, kind.server_action())
        )

    # ── volumes ──

    def attach(self, volume_id: str, server_id: str, public_id: str) -> ChangeDone:
        """Attaches the volume to a server of the same project."""
        ticket = self.ticket(public_id)
        volume, _ = self.volume(volume_id)
        server = self.server(server_id)
        if server.project_id != volume.project_id:
            raise InfraError(
                InfraRefusal.CHANGE_REFUSED,
                "the volume and the server are in different projects",
                {"target_kind": InfraResource.VOLUME.value, "target_id": volume.id},
            )
        path = f"/servers/{server.id}/os-volume_attachments"
        body = {"volumeAttachment": {"volumeId": volume.id}}
        using = f"{server.name} ({server.id})"
        return self.send(
            ticket, Change(InfraChange.ATTACH_VOLUME, volume, "POST", "compute", path, body, using)
        )

    def detach(self, volume_id: str, public_id: str) -> ChangeDone:
        """Detaches the volume from the one server it is attached to."""
        ticket = self.ticket(public_id)
        volume, read = self.volume(volume_id)
        if len(read.attachments) != 1:
            raise InfraError(
                InfraRefusal.STATE_CHANGED,
                f"the volume is attached to {len(read.attachments)} servers, not one",
                {"target_kind": InfraResource.VOLUME.value, "target_id": volume.id},
            )
        server_id = read.attachments[0].server_id
        path = f"/servers/{server_id}/os-volume_attachments/{volume.id}"
        return self.send(
            ticket,
            Change(InfraChange.DETACH_VOLUME, volume, "DELETE", "compute", path, using=server_id),
        )

    # ── security groups ──

    def add_rule(self, group_id: str, rule: RuleSpec, public_id: str) -> ChangeDone:
        ticket = self.ticket(public_id)
        group, _ = self.security_group(group_id)
        return self.send(
            ticket,
            Change(
                InfraChange.ADD_SECURITY_RULE,
                group,
                "POST",
                "network",
                "/v2.0/security-group-rules",
                rule.neutron(group.id),
                rule.described(),
            ),
        )

    def remove_rule(self, group_id: str, rule_id: str, public_id: str) -> ChangeDone:
        """Removes a rule of the group; a rule of any other group is `infra_not_found`."""
        ticket = self.ticket(public_id)
        group, rules = self.security_group(group_id)
        rule = next((r for r in rules if r.id == rule_id), None)
        if rule is None:
            raise InfraError(InfraRefusal.NOT_FOUND, "no such resource")
        spec = RuleSpec(
            rule.direction,
            rule.ethertype,
            rule.protocol,
            rule.port_min,
            rule.port_max,
            rule.remote_ip_prefix,
        )
        path = f"/v2.0/security-group-rules/{rule.id}"
        using = f"{spec.described()} ({rule.id})"
        return self.send(
            ticket,
            Change(InfraChange.REMOVE_SECURITY_RULE, group, "DELETE", "network", path, None, using),
        )

    # ── before a change ──

    def ticket(self, public_id: str | None) -> Ticket | None:
        """The open ticket a staff change is for, which the caller works on; None on a customer
        route (BR-F17-11)."""
        if not self.for_a_ticket:
            return None
        user = self.caller.user
        refused = InfraError(
            InfraRefusal.TICKET_REQUIRED,
            "a change names an open ticket you work on",
            {"public_id": public_id},
        )
        ticket = (
            Ticket.objects.select_related("reporter", "customer")
            .filter(public_id=public_id)
            .first()
        )
        if (
            ticket is None
            or ticket.resolved_at is not None
            or ticket.status in TRIAGE_STATUSES
            or not Access.of(user).covers_ticket(Permission.TICKETS_COMMENT, ticket)
        ):
            raise refused
        try:
            assignment.check_category_scope(user, ticket)
        except TeamError as e:
            raise refused from e
        return ticket

    def server(self, server_id: str) -> ChangeTarget:
        read = self.read("compute", f"/servers/{server_id}", lambda raw: Server.of(raw["server"]))
        target = ChangeTarget(InfraResource.SERVER, read.id, read.name, read.project_id)
        return self.reached(server_id, target)

    def volume(self, volume_id: str) -> tuple[ChangeTarget, Volume]:
        read = self.read("volumev3", f"/volumes/{volume_id}", lambda raw: Volume.of(raw["volume"]))
        target = ChangeTarget(InfraResource.VOLUME, read.id, read.name, read.project_id)
        return self.reached(volume_id, target), read

    def security_group(self, group_id: str) -> tuple[ChangeTarget, list[Rule]]:
        read = self.read(
            "network",
            f"/v2.0/security-groups/{group_id}",
            lambda raw: SecurityGroup.of(raw["security_group"]),
        )
        target = ChangeTarget(InfraResource.SECURITY_GROUP, read.id, read.name, read.project_id)
        return self.reached(group_id, target), read.rules

    def read[T](self, service: str, path: str, parse: Callable[[Any], T]) -> T:
        """A resource read a change needs first; one that doesn't exist is `infra_not_found`."""
        try:
            return parse(self.cloud.get(service, path))
        except BackendNotFound as e:
            raise InfraError(InfraRefusal.NOT_FOUND, "no such resource") from e
        except (BackendUnavailable, *UNREADABLE) as e:
            logger.warning("infra: reading %s before a change failed: %s", path, e)
            raise InfraError(
                InfraRefusal.BACKEND_UNAVAILABLE,
                "cloud did not answer",
                {"backend": InfraBackend.CLOUD.value},
            ) from e

    def reached(self, asked_id: str, target: ChangeTarget) -> ChangeTarget:
        """`target`, if it is the one asked for and within the caller's scope; otherwise refused
        exactly as a resource that doesn't exist."""
        if target.id != asked_id or not self.scope.reaches(target.project_id):
            raise InfraError(InfraRefusal.NOT_FOUND, "no such resource")
        return target

    # ── the change ──

    def send(self, ticket: Ticket | None, change: Change) -> ChangeDone:
        """Sends `change` to the cloud once and records it; a lost answer is recorded as unknown
        and refused with `infra_outcome_unknown`."""
        try:
            self.cloud.change(change.method, change.service, change.path, change.body)
        except BackendNotFound as e:
            raise InfraError(InfraRefusal.NOT_FOUND, "no such resource") from e
        except BackendConflict as e:
            raise InfraError(
                InfraRefusal.STATE_CHANGED,
                f"the {change.target.kind.value} is not in a state that allows this; read it again",
                change.details(),
            ) from e
        except BackendRefused as e:
            raise InfraError(
                InfraRefusal.CHANGE_REFUSED, "the cloud refused this change", change.details()
            ) from e
        except BackendUnavailable as e:
            logger.warning("infra: %s was not sent: %s", change.kind.value, e)
            raise InfraError(
                InfraRefusal.BACKEND_UNAVAILABLE,
                "cloud did not answer",
                {"backend": InfraBackend.CLOUD.value},
            ) from e
        except ChangeOutcomeUnknown as e:
            logger.error("infra: %s on %s: no answer: %s", change.kind.value, change.path, e)
            self.record(ticket, change, ChangeOutcome.UNKNOWN)
            raise InfraOutcomeUnknown(
                "the cloud's answer was lost; check the resource before trying again",
                change.details(),
            ) from e
        self.record(ticket, change, ChangeOutcome.DONE)
        target = change.target
        return ChangeDone(
            change=change.kind,
            target_kind=target.kind,
            target_id=target.id,
            target_name=target.name,
            project_id=target.project_id,
            ticket=ticket.public_id if ticket else None,
        )

    def record(self, ticket: Ticket | None, change: Change, outcome: ChangeOutcome) -> None:
        """Audits a change the cloud may have made, notes it on its ticket, and tells the
        ticket's requester of one made when their company owns the resource; a failure here
        never reaches the caller."""
        user = self.caller.user
        try:
            AuditLog.objects.record(
                "infra_change",
                actor_type="human",
                actor_id=user.id,
                ticket_id=ticket.id if ticket else None,
                payload={
                    **change.details(),
                    "project_id": change.target.project_id,
                    "outcome": outcome.value,
                    "ticket_public_id": ticket.public_id if ticket else None,
                },
                trace_id=self.caller.trace_id,
            )
        except Exception:  # noqa: BLE001 — the change is already sent
            logger.exception("infra: auditing %s failed", change.kind.value)
        if ticket is None:
            return
        try:
            comments.by_staff(
                ticket,
                user,
                change.note(outcome, user.preferred_language()),
                visibility=CommentVisibility.INTERNAL,
                move_to_waiting=False,
                expected_version=None,
            )
        except Exception:  # noqa: BLE001 — the change is already sent
            logger.exception("infra: noting %s on %s failed", change.kind.value, ticket.public_id)
        if outcome is not ChangeOutcome.DONE or ticket.customer is None:
            return
        try:
            owner = Project.of(
                self.cloud.get("identity", f"/projects/{change.target.project_id}")["project"]
            )
            if owner.domain_id == ticket.customer.keystone_domain_id:
                notifier.emit(
                    NotificationEvent.INFRA_CHANGE_ON_YOUR_RESOURCE,
                    ticket,
                    Notice(
                        actor=user.username,
                        message=change.target.name or change.target.id,
                        detail=change.kind.value,
                        data=change.details(),
                    ),
                )
        except Exception:  # noqa: BLE001 — the change is already sent
            logger.exception("infra: telling the owner of %s failed", change.kind.value)
