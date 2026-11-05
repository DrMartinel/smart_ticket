"""Mass incidents (spec §9, F7): a new ticket joins an open incident by similarity or the detector
proposes one; an incident manager confirms, broadcasts with an ETA and resolves it with its
tickets."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.accounts.models import Capability, User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.incidents.models import IncidentBroadcast, IncidentLink
from apps.notifications.models import Message
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.tickets.models import (
    Incident,
    IncidentStage,
    IncidentStatus,
    IncidentVerdict,
    Ticket,
    TicketEmbedding,
)

if TYPE_CHECKING:
    from apps.review.models import ReviewItem

logger = logging.getLogger(__name__)

# One lock for every detection and match: categories aren't known yet (BR-F7-02).
_LOCK = "mass_incident"


class IncidentRefusal(StrEnum):
    NOT_FOUND = "incident_not_found"
    NOT_PROPOSED = "not_proposed"
    NOT_CONFIRMED = "not_confirmed"
    NOT_RESOLVED = "not_resolved"
    NOT_OPEN = "not_open"
    REASON_REQUIRED = "reason_required"
    BODY_REQUIRED = "body_required"
    ALREADY_LINKED = "already_linked"
    NOT_LINKED = "not_linked"
    NOT_ALLOWED = "not_allowed"
    MASK_FAILED = "mask_failed"


class IncidentError(CodedError):
    """An incident request core-api refuses."""


@dataclass
class CloseResult:
    closed: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)


def mean(vectors: list[list[float]]) -> list[float] | None:
    """The element-wise mean of `vectors`; None for none."""
    if not vectors:
        return None
    n = len(vectors)
    return [sum(column) / n for column in zip(*vectors, strict=True)]


def mask_text(text: str) -> str:
    """A person's broadcast, note or reason, masked like a comment; values are dropped, never
    stored. Refused when masking fails."""
    from asgiref.sync import async_to_sync

    from apps.tickets.utils.masking import mask_reply
    from apps.tickets.utils.patterns import PIILevel

    if not text.strip():
        return ""
    masked = async_to_sync(mask_reply)(text.strip(), settings.THRESHOLDS.masking.ner_max_share, [])
    if masked.pii_level is PIILevel.MASK_FAILED:
        raise IncidentError(503, IncidentRefusal.MASK_FAILED, "masking failed: nothing was sent")
    return masked.text_masked


class Incidents:
    """Detection, linking and the incident manager's actions."""

    # ── detection (BR-F7-02, BR-F7-09) ──

    def lock(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [_LOCK])

    def classify(self, ticket: Ticket, embedding: list[float]) -> IncidentVerdict:
        """Joins an open incident whose centroid the ticket matches; else the detector may propose
        one (count above baseline + kσ and at least `min_count`); else a duplicate or unique."""
        th = settings.THRESHOLDS.incident
        with transaction.atomic():
            self.lock()
            match = self.matching(embedding)
            if match is not None:
                incident, similarity = match
                self.link(incident, ticket, "matcher", similarity)
                self.update_centroid(incident)
                return IncidentVerdict(kind="mass_incident", parent=incident)
            window = timedelta(minutes=th.window_minutes)
            similar = [
                t
                for t in Ticket.objects.similar_to(embedding, None, th.similarity, window)
                if t.pk != ticket.pk and not t.incident_links.active().exists()
            ]
            if not similar:
                return IncidentVerdict(kind="unique")
            baseline, sigma = Ticket.objects.rolling_baseline(
                None, days=30, window_minutes=th.window_minutes
            )
            count = len(similar) + 1
            if count > baseline + th.sigma_multiplier * sigma and count >= th.min_count:
                incident = self.propose(ticket, similar, count, baseline, sigma)
                return IncidentVerdict(
                    kind="mass_incident", parent=incident, baseline_rate=baseline
                )
        return IncidentVerdict(kind="duplicate", of=similar[0].id)

    def matching(self, embedding: list[float]) -> tuple[Incident, float] | None:
        """The open incident whose centroid is nearest, when within `incident.similarity`."""
        bar = 1 - settings.THRESHOLDS.incident.similarity
        found = (
            Incident.objects.open()
            .exclude(centroid__isnull=True)
            .annotate(distance=CosineDistance("centroid", embedding))
            .filter(distance__lte=bar)
            .order_by("distance")
            .first()
        )
        if found is None:
            return None
        return found, 1 - float(found.distance)

    def propose(
        self, ticket: Ticket, similar: list[Ticket], count: int, baseline: float, sigma: float
    ) -> Incident:
        """A `proposed` incident linking the ticket and the similar ones (BR-F7-01)."""
        th = settings.THRESHOLDS.incident
        incident = Incident.objects.create(
            public_id=Incident.objects.next_public_id(),
            title=f"Proposed: {ticket.subject_masked[:120]}",
            severity="high",
            detected_by="density_detector",
            detection_window_min=th.window_minutes,
            baseline_rate=baseline,
            detector={
                "count": count,
                "baseline": baseline,
                "sigma": sigma,
                "window_minutes": th.window_minutes,
                "min_count": th.min_count,
            },
        )
        for member in [*similar, ticket]:
            self.link(incident, member, "detector", None)
        self.update_centroid(incident)
        AuditLog.objects.record(
            "incident_proposed",
            actor_type="system",
            payload={"incident": incident.public_id, "count": count, "baseline": baseline},
        )
        notifier.emit(
            NotificationEvent.INCIDENT_PROPOSED,
            notice=Notice(
                reason=incident.public_id,
                detail=f"{count} similar tickets in {th.window_minutes} min",
                message=incident.title,
                link=f"/incidents/{incident.public_id}",
                data={"incident": incident.public_id, "count": count},
            ),
        )
        return incident

    def link(
        self, incident: Incident, ticket: Ticket, by: str, similarity: float | None
    ) -> IncidentLink:
        """Links a ticket (once); the count comes from the links (BR-F7-09)."""
        existing = IncidentLink.objects.active().filter(ticket=ticket).first()
        if existing is not None:
            if existing.incident_id != incident.id:
                raise IncidentError(
                    409, IncidentRefusal.ALREADY_LINKED, f"{ticket.public_id} is linked"
                )
            return existing
        link = IncidentLink.objects.create(
            incident=incident, ticket=ticket, linked_by=by, similarity=similarity
        )
        Ticket.objects.filter(pk=ticket.pk).update(incident=incident)
        ticket.incident = incident
        self.recount(incident)
        AuditLog.objects.record(
            "incident_ticket_linked",
            actor_type="system" if by in ("detector", "matcher") else "human",
            ticket_id=ticket.id,
            payload={"incident": incident.public_id, "by": by, "similarity": similarity},
        )
        return link

    def recount(self, incident: Incident) -> None:
        incident.ticket_count = IncidentLink.objects.active().filter(incident=incident).count()
        Incident.objects.filter(pk=incident.pk).update(ticket_count=incident.ticket_count)

    def update_centroid(self, incident: Incident) -> None:
        """The mean embedding of the linked tickets."""
        ids = (
            IncidentLink.objects.active()
            .filter(incident=incident)
            .values_list("ticket_id", flat=True)
        )
        vectors = [
            list(e)
            for e in TicketEmbedding.objects.filter(ticket_id__in=ids).values_list(
                "embedding", flat=True
            )
        ]
        centroid = mean(vectors)
        if centroid is not None:
            Incident.objects.filter(pk=incident.pk).update(centroid=centroid)
            incident.centroid = centroid

    # ── the incident manager ──

    def check_manager(self, actor: User) -> None:
        if Capability.INCIDENT_MANAGER.value not in actor.capability_set():
            raise IncidentError(403, IncidentRefusal.NOT_ALLOWED, "incident managers only")

    def get(self, public_id: str) -> Incident:
        incident = Incident.objects.select_for_update().filter(public_id=public_id).first()
        if incident is None:
            raise IncidentError(404, IncidentRefusal.NOT_FOUND, "no such incident")
        return incident

    def linked(self, incident: Incident) -> list[Ticket]:
        return list(
            Ticket.objects.filter(
                incident_links__incident=incident, incident_links__unlinked_at__isnull=True
            ).select_related("reporter", "workflow_status", "assigned_to")
        )

    def confirm(
        self, public_id: str, actor: User, title: str, category: str | None, service: str
    ) -> Incident:
        """Confirms a proposal: each linked ticket's pending review item is decided `approve` in the
        manager's name, and their resolution clocks wait for the incident (BR-F7-03, 07)."""
        self.check_manager(actor)
        with transaction.atomic():
            incident = self.get(public_id)
            if incident.status != IncidentStatus.PROPOSED.value:
                raise IncidentError(409, IncidentRefusal.NOT_PROPOSED, f"it is {incident.status}")
            self.start(incident, actor, title, category, service)
            for ticket in self.linked(incident):
                self.agree(ticket, actor)
            AuditLog.objects.record(
                "incident_confirmed",
                actor_type="human",
                actor_id=actor.id,
                payload={"incident": incident.public_id, "tickets": incident.ticket_count},
            )
        return incident

    def start(
        self, incident: Incident, actor: User, title: str, category: str | None, service: str
    ) -> None:
        from apps.sla.utils.clocks import sla_clocks

        now = timezone.now()
        incident.status = IncidentStatus.CONFIRMED.value
        incident.title = title.strip() or incident.title
        incident.category = category or incident.category
        incident.service = service.strip()
        incident.confirmed_by, incident.confirmed_at = actor, now
        incident.target_resolve_at = now + timedelta(
            minutes=settings.THRESHOLDS.incident.resolve_target_minutes
        )
        incident.save()
        for ticket in self.linked(incident):
            sla_clocks.incident_hold(ticket, True)

    def agree(self, ticket: Ticket, actor: User) -> None:
        """Decides the ticket's pending review item `approve`: agreement with the router's
        escalation, so no eval candidate and no hand-off."""
        from apps.review.models import ReviewItem
        from apps.review.request_schema import DecisionIn
        from apps.review.utils import review_decisions

        item: ReviewItem | None = ReviewItem.objects.filter(
            ticket=ticket, state__in=ReviewItem.OPEN_STATES, comment__isnull=True
        ).first()
        if item is not None:
            review_decisions.decide(
                item, actor, DecisionIn(action_taken="approve", time_spent_sec=0), handoff=False
            )

    def dismiss(self, public_id: str, actor: User, reason: str) -> Incident:
        """Not an incident: its tickets are unlinked and stay in review as they were."""
        self.check_manager(actor)
        if not reason.strip():
            raise IncidentError(422, IncidentRefusal.REASON_REQUIRED, "say why")
        masked = mask_text(reason)
        with transaction.atomic():
            incident = self.get(public_id)
            if incident.status != IncidentStatus.PROPOSED.value:
                raise IncidentError(409, IncidentRefusal.NOT_PROPOSED, f"it is {incident.status}")
            for ticket in self.linked(incident):
                self.detach(incident, ticket, f"dismissed: {masked}")
            incident.status = IncidentStatus.DISMISSED.value
            incident.dismiss_reason = masked
            incident.save()
            AuditLog.objects.record(
                "incident_dismissed",
                actor_type="human",
                actor_id=actor.id,
                payload={"incident": incident.public_id},
            )
        return incident

    def declare(
        self,
        actor: User,
        title: str,
        category: str | None,
        service: str,
        ticket_ids: list[str],
        broadcast: dict[str, Any] | None,
    ) -> Incident:
        """A confirmed incident a manager opens by hand, with tickets and a first broadcast."""
        self.check_manager(actor)
        with transaction.atomic():
            self.lock()
            incident = Incident.objects.create(
                public_id=Incident.objects.next_public_id(),
                title=title.strip(),
                severity="high",
                detected_by="human",
            )
            for ticket in Ticket.objects.filter(public_id__in=ticket_ids):
                self.link(incident, ticket, actor.username, None)
            self.update_centroid(incident)
            self.start(incident, actor, title, category, service)
            for ticket in self.linked(incident):
                self.agree(ticket, actor)
            AuditLog.objects.record(
                "incident_declared",
                actor_type="human",
                actor_id=actor.id,
                payload={"incident": incident.public_id, "tickets": incident.ticket_count},
            )
        if broadcast and broadcast.get("body_vi", "").strip():
            self.broadcast(incident.public_id, actor, **broadcast)
        return incident

    # ── broadcasts (BR-F7-05) ──

    def broadcast(
        self,
        public_id: str,
        actor: User,
        *,
        stage: str = IncidentStage.INVESTIGATING.value,
        body_vi: str,
        body_en: str = "",
        eta: datetime | None = None,
        eta_unknown: bool = False,
    ) -> IncidentBroadcast:
        """One notice per requester, mandatory, and a system comment on each linked ticket; the
        first broadcast meets their response clocks."""
        from apps.sla.utils.clocks import sla_clocks
        from apps.tickets.utils.comments import comments

        self.check_manager(actor)
        vi, en = mask_text(body_vi), mask_text(body_en)
        if not vi:
            raise IncidentError(422, IncidentRefusal.BODY_REQUIRED, "write the update")
        with transaction.atomic():
            incident = self.get(public_id)
            if incident.status not in (
                IncidentStatus.CONFIRMED.value,
                IncidentStatus.RESOLVED.value,
            ):
                raise IncidentError(409, IncidentRefusal.NOT_CONFIRMED, f"it is {incident.status}")
            tickets = self.linked(incident)
            requesters = list({t.reporter_id: t.reporter for t in tickets}.values())
            sent = IncidentBroadcast.objects.create(
                incident=incident,
                stage=stage,
                body_vi_masked=vi,
                body_en_masked=en,
                eta=None if eta_unknown else eta,
                eta_unknown=eta_unknown,
                sent_by=actor,
                requesters_count=len(requesters),
            )
            incident.stage = stage
            incident.eta, incident.eta_unknown = sent.eta, eta_unknown
            incident.save(update_fields=["stage", "eta", "eta_unknown"])
            for ticket in tickets:
                comments.system(ticket, vi, sent)
                sla_clocks.responded(ticket, actor)
            self.announce(incident, sent, requesters)
            AuditLog.objects.record(
                "incident_broadcast",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "incident": incident.public_id,
                    "broadcast": str(sent.id),
                    "requesters": len(requesters),
                    "stage": stage,
                },
            )
        return sent

    def announce(
        self,
        incident: Incident,
        sent: IncidentBroadcast,
        requesters: list[User],
        late: User | None = None,
    ) -> None:
        """The broadcast's notice to `requesters`, each once per broadcast."""
        if not requesters:
            return
        eta = (
            "chưa xác định / unknown"
            if sent.eta_unknown
            else (sent.eta.isoformat() if sent.eta else "—")
        )
        notifier.emit(
            NotificationEvent.INCIDENT_BROADCAST,
            notice=Notice(
                reason=incident.title,
                message=sent.body_vi_masked,
                detail=sent.body_en_masked or sent.body_vi_masked,
                linked_requesters=tuple(requesters),
                link=f"{settings.NOTIFICATION_CHAT_BASE_URL.rstrip('/')}/tickets",
                data={"incident": incident.public_id, "stage": sent.stage, "eta": eta},
            ),
            event_id=self.notice_id(sent, late),
        )

    def notice_id(self, sent: IncidentBroadcast, late: User | None = None) -> uuid.UUID:
        """The broadcast's notice id: one for the send, one per requester who joined later."""
        key = f"broadcast:{sent.id}" + (f":late:{late.id}" if late else "")
        return uuid.uuid5(uuid.NAMESPACE_URL, key)

    def delivery(self, sent: IncidentBroadcast) -> dict[str, int]:
        """Requesters, in-app delivered, email delivered and failed (FR-F7-008)."""
        reporters = User.objects.filter(
            reported_tickets__incident_links__incident=sent.incident_id
        ).distinct()
        ids = [self.notice_id(sent), *(self.notice_id(sent, u) for u in reporters)]
        messages = Message.objects.filter(
            event=NotificationEvent.INCIDENT_BROADCAST.value, event_id__in=ids
        )
        return {
            "requesters": sent.requesters_count,
            "in_app_delivered": messages.filter(channel="in_app", state="delivered").count(),
            "email_delivered": messages.filter(channel="email", state="delivered").count(),
            "email_failed": messages.filter(channel="email", state="failed").count(),
        }

    # ── resolving (UC-F7-04) ──

    def resolve(self, public_id: str, actor: User, note: str, close_all: bool) -> CloseResult:
        """A final `resolved` broadcast with the note; with close-all, each linked open ticket gets
        the note and a governed move to `resolved`, a refusal not stopping the rest (BR-F7-06)."""
        from apps.sla.utils.clocks import sla_clocks

        self.check_manager(actor)
        masked = mask_text(note)
        if not masked:
            raise IncidentError(422, IncidentRefusal.REASON_REQUIRED, "write the resolution note")
        with transaction.atomic():
            incident = self.get(public_id)
            if incident.status != IncidentStatus.CONFIRMED.value:
                raise IncidentError(409, IncidentRefusal.NOT_CONFIRMED, f"it is {incident.status}")
            incident.status = IncidentStatus.RESOLVED.value
            incident.resolved_by, incident.resolved_at = actor, timezone.now()
            incident.resolution_note_masked = masked
            incident.save()
            AuditLog.objects.record(
                "incident_resolved",
                actor_type="human",
                actor_id=actor.id,
                payload={"incident": incident.public_id, "close_all": close_all},
            )
        self.broadcast(public_id, actor, stage=IncidentStage.RESOLVED.value, body_vi=note)
        result = self.close_all(incident, actor) if close_all else CloseResult()
        if not close_all:
            for ticket in self.linked(incident):
                sla_clocks.incident_hold(ticket, False)
        return result

    def close_all(self, incident: Incident, actor: User) -> CloseResult:
        """Moves each linked open ticket to `resolved`, each audited; a refusal is listed and its
        assignee told."""
        from apps.lifecycle.utils.engine import lifecycle
        from apps.lifecycle.utils.errors import LifecycleError
        from apps.sla.utils.clocks import sla_clocks

        result = CloseResult()
        for ticket in self.linked(incident):
            if ticket.resolved_at is not None:
                continue
            try:
                with transaction.atomic():
                    lifecycle.automatic_move(ticket, "resolved")
                    AuditLog.objects.record(
                        "incident_ticket_closed",
                        actor_type="human",
                        actor_id=actor.id,
                        ticket_id=ticket.id,
                        payload={"incident": incident.public_id},
                    )
                result.closed.append(ticket.public_id)
            except LifecycleError as e:
                result.failed.append({"ticket": ticket.public_id, "code": e.code.value})
                sla_clocks.incident_hold(ticket, False)
                notifier.emit(
                    NotificationEvent.INCIDENT_TICKET_NOT_CLOSED,
                    ticket,
                    Notice(
                        actor=actor.username,
                        reason=incident.public_id,
                        detail=e.code.value,
                        data={"incident": incident.public_id, "code": e.code.value},
                    ),
                )
        AuditLog.objects.record(
            "incident_close_all",
            actor_type="human",
            actor_id=actor.id,
            payload={
                "incident": incident.public_id,
                "closed": len(result.closed),
                "failed": result.failed,
            },
        )
        return result

    def reopen(self, public_id: str, actor: User, reason: str) -> Incident:
        """The same outage is back: confirmed again, clocks of linked open tickets wait again."""
        from apps.sla.utils.clocks import sla_clocks

        self.check_manager(actor)
        if not reason.strip():
            raise IncidentError(422, IncidentRefusal.REASON_REQUIRED, "say why")
        masked = mask_text(reason)
        with transaction.atomic():
            incident = self.get(public_id)
            if incident.status != IncidentStatus.RESOLVED.value:
                raise IncidentError(409, IncidentRefusal.NOT_RESOLVED, f"it is {incident.status}")
            incident.status = IncidentStatus.CONFIRMED.value
            incident.resolved_at = None
            incident.save()
            for ticket in self.linked(incident):
                if ticket.resolved_at is None:
                    sla_clocks.incident_hold(ticket, True)
            AuditLog.objects.record(
                "incident_reopened",
                actor_type="human",
                actor_id=actor.id,
                payload={"incident": incident.public_id, "reason": masked},
            )
        return incident

    # ── links by hand (UC-F7-05) ──

    def add_links(self, public_id: str, actor: User, ticket_ids: list[str]) -> list[IncidentLink]:
        self.check_manager(actor)
        with transaction.atomic():
            self.lock()
            incident = self.get(public_id)
            if not incident.is_open:
                raise IncidentError(409, IncidentRefusal.NOT_OPEN, f"it is {incident.status}")
            links = [
                self.link(incident, ticket, actor.username, None)
                for ticket in Ticket.objects.filter(public_id__in=ticket_ids)
            ]
            self.update_centroid(incident)
            if incident.status == IncidentStatus.CONFIRMED.value:
                from apps.sla.utils.clocks import sla_clocks

                for link in links:
                    sla_clocks.incident_hold(link.ticket, True)
        return links

    def unlink(self, public_id: str, ticket_id: str, actor: User, reason: str) -> None:
        """Not part of this outage: unlinked with a reason, back to a person's review, clocks
        resume (counted in detector precision, F10)."""
        from apps.review.models import ReviewItem
        from apps.tickets.utils.router import ReviewQueue

        if not reason.strip():
            raise IncidentError(422, IncidentRefusal.REASON_REQUIRED, "say why")
        masked = mask_text(reason)
        with transaction.atomic():
            incident = self.get(public_id)
            ticket = Ticket.objects.filter(public_id=ticket_id).first()
            if (
                ticket is None
                or not IncidentLink.objects.active()
                .filter(incident=incident, ticket=ticket)
                .exists()
            ):
                raise IncidentError(404, IncidentRefusal.NOT_LINKED, "not linked to this incident")
            is_manager = Capability.INCIDENT_MANAGER.value in actor.capability_set()
            if not is_manager and ticket.assigned_to_id != actor.id:
                raise IncidentError(
                    403, IncidentRefusal.NOT_ALLOWED, "incident managers and the assignee"
                )
            self.detach(incident, ticket, masked)
            if not ReviewItem.objects.filter(
                ticket=ticket, state__in=ReviewItem.OPEN_STATES
            ).exists():
                ReviewItem.objects.create(
                    ticket=ticket, queue=ReviewQueue.LOW_CONFIDENCE.value, priority=2
                )
            self.update_centroid(incident)
            AuditLog.objects.record(
                "incident_ticket_unlinked",
                actor_type="human",
                actor_id=actor.id,
                ticket_id=ticket.id,
                payload={"incident": incident.public_id, "reason": masked},
            )

    def detach(self, incident: Incident, ticket: Ticket, masked_reason: str) -> None:
        """Ends the ticket's link with an already masked reason; its clock no longer waits."""
        from apps.sla.utils.clocks import sla_clocks

        IncidentLink.objects.active().filter(incident=incident, ticket=ticket).update(
            unlinked_at=timezone.now(), unlink_reason=masked_reason
        )
        Ticket.objects.filter(pk=ticket.pk).update(incident=None)
        ticket.incident = None
        self.recount(incident)
        sla_clocks.incident_hold(ticket, False)

    # ── a ticket joining a confirmed incident (BR-F7-04) ──

    def attach(self, ticket: Ticket, *, live: bool) -> bool:
        """A ticket the router escalated into a confirmed incident: its resolution clock waits;
        live, it needs no review item and its requester gets the latest broadcast at once."""
        from apps.sla.utils.clocks import sla_clocks
        from apps.tickets.utils.comments import comments

        incident = ticket.incident
        if incident is None or incident.status != IncidentStatus.CONFIRMED.value:
            return False
        sla_clocks.incident_hold(ticket, True)
        if not live:
            return False
        latest = incident.broadcasts.first()
        if latest is not None:
            comments.system(ticket, latest.body_vi_masked, latest)
            self.announce(incident, latest, [ticket.reporter], late=ticket.reporter)
        AuditLog.objects.record(
            "incident_ticket_attached",
            actor_type="system",
            ticket_id=ticket.id,
            payload={"incident": incident.public_id},
        )
        return True

    # ── the sweep (BR-F7-10) ──

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Target breaches once each; resolved incidents closed after `auto_close_after_days`."""
        now = now or timezone.now()
        breached = 0
        for incident in Incident.objects.filter(
            status=IncidentStatus.CONFIRMED.value,
            target_resolve_at__lte=now,
            target_breached_at__isnull=True,
        ):
            if Incident.objects.filter(pk=incident.pk, target_breached_at__isnull=True).update(
                target_breached_at=now
            ):
                notifier.emit(
                    NotificationEvent.INCIDENT_SLA_BREACHED,
                    notice=Notice(
                        reason=incident.public_id,
                        detail=f"target {incident.target_resolve_at:%Y-%m-%d %H:%M} UTC",
                        message=incident.title,
                        link=f"/incidents/{incident.public_id}",
                        data={"incident": incident.public_id},
                    ),
                    event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"incident_breach:{incident.id}"),
                )
                breached += 1
        cutoff = now - timedelta(days=settings.THRESHOLDS.incident.auto_close_after_days)
        closed = Incident.objects.filter(
            status=IncidentStatus.RESOLVED.value, resolved_at__lte=cutoff
        ).update(status=IncidentStatus.CLOSED.value, closed_at=now)
        if closed:
            AuditLog.objects.record(
                "incident_closed", actor_type="system", payload={"count": closed}
            )
        return {"breached": breached, "closed": closed}


# --- the incidents service ---

incidents = Incidents()
