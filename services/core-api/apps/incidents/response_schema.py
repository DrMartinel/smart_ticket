"""What staff see of an incident, and the banner a linked ticket's requester sees (F7 §h)."""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema

from apps.sla.models import ClockKind
from apps.incidents.models import IncidentBroadcast, IncidentLink
from apps.incidents.utils.incidents import incidents
from apps.tickets.models import Incident, IncidentStatus, Ticket


class IncidentRowOut(Schema):
    public_id: str
    title: str
    status: str
    stage: str
    category: str | None
    service: str
    ticket_count: int
    detected_by: str
    eta: datetime | None
    eta_unknown: bool
    target_resolve_at: datetime | None
    target_breached: bool
    created_at: datetime
    confirmed_at: datetime | None
    resolved_at: datetime | None

    @classmethod
    def of(cls, incident: Incident) -> IncidentRowOut:
        return cls(
            public_id=incident.public_id,
            title=incident.title,
            status=incident.status,
            stage=incident.stage,
            category=incident.category,
            service=incident.service,
            ticket_count=incident.ticket_count,
            detected_by=incident.detected_by,
            eta=incident.eta,
            eta_unknown=incident.eta_unknown,
            target_resolve_at=incident.target_resolve_at,
            target_breached=incident.target_breached_at is not None,
            created_at=incident.created_at,
            confirmed_at=incident.confirmed_at,
            resolved_at=incident.resolved_at,
        )


class IncidentLinkOut(Schema):
    ticket: str
    subject_masked: str
    requester: str
    status: str
    assigned_to: str | None
    linked_by: str
    linked_at: datetime
    similarity: float | None
    # The resolution clock's state: `paused` while the incident is confirmed (BR-F7-07).
    clock_state: str | None

    @classmethod
    def of(cls, link: IncidentLink) -> IncidentLinkOut:
        ticket = link.ticket
        clock = next((c for c in ticket.sla_clocks.all() if c.kind == ClockKind.RESOLUTION), None)
        return cls(
            ticket=ticket.public_id,
            subject_masked=ticket.subject_masked,
            requester=ticket.reporter.username,
            status=ticket.status,
            assigned_to=ticket.assigned_to.username if ticket.assigned_to else None,
            linked_by=link.linked_by,
            linked_at=link.linked_at,
            similarity=link.similarity,
            clock_state=clock.state if clock else None,
        )


class BroadcastDeliveryOut(Schema):
    requesters: int
    in_app_delivered: int
    email_delivered: int
    email_failed: int


class BroadcastOut(Schema):
    id: uuid.UUID
    stage: str
    body_vi_masked: str
    body_en_masked: str
    eta: datetime | None
    eta_unknown: bool
    sent_by: str
    sent_at: datetime
    delivery: BroadcastDeliveryOut

    @classmethod
    def of(cls, sent: IncidentBroadcast) -> BroadcastOut:
        return cls(
            id=sent.id,
            stage=sent.stage,
            body_vi_masked=sent.body_vi_masked,
            body_en_masked=sent.body_en_masked,
            eta=sent.eta,
            eta_unknown=sent.eta_unknown,
            sent_by=sent.sent_by.username,
            sent_at=sent.sent_at,
            delivery=BroadcastDeliveryOut(**incidents.delivery(sent)),
        )


class IncidentDetailOut(IncidentRowOut):
    detector: dict[str, float]
    confirmed_by: str | None
    resolved_by: str | None
    resolution_note_masked: str
    dismiss_reason: str
    requesters: int
    links: list[IncidentLinkOut]
    broadcasts: list[BroadcastOut]

    @classmethod
    def build(cls, incident: Incident) -> IncidentDetailOut:
        links = (
            IncidentLink.objects.active()
            .filter(incident=incident)
            .select_related("ticket__reporter", "ticket__assigned_to")
            .prefetch_related("ticket__sla_clocks")
            .order_by("linked_at")
        )
        return cls(
            **IncidentRowOut.of(incident).model_dump(),
            detector=incident.detector,
            confirmed_by=incident.confirmed_by.username if incident.confirmed_by else None,
            resolved_by=incident.resolved_by.username if incident.resolved_by else None,
            resolution_note_masked=incident.resolution_note_masked,
            dismiss_reason=incident.dismiss_reason,
            requesters=len({link.ticket.reporter_id for link in links}),
            links=[IncidentLinkOut.of(link) for link in links],
            broadcasts=[BroadcastOut.of(b) for b in incident.broadcasts.select_related("sent_by")],
        )


class CloseResultOut(Schema):
    closed: list[str]
    failed: list[dict[str, str]]


class IncidentBannerOut(Schema):
    """The incident a requester's ticket belongs to, once a person confirmed it (FR-F7-012)."""

    title: str
    status: str
    stage: str
    eta: datetime | None
    eta_unknown: bool
    last_update: str | None
    last_update_at: datetime | None

    @classmethod
    def of(cls, ticket: Ticket) -> IncidentBannerOut | None:
        incident = ticket.incident if ticket.incident_id is not None else None
        shown = (IncidentStatus.CONFIRMED.value, IncidentStatus.RESOLVED.value)
        if incident is None or incident.status not in shown:
            return None
        latest = incident.broadcasts.first()
        return cls(
            title=incident.title,
            status=incident.status,
            stage=incident.stage,
            eta=incident.eta,
            eta_unknown=incident.eta_unknown,
            last_update=latest.body_vi_masked if latest else None,
            last_update_at=latest.sent_at if latest else None,
        )
