"""What a requester does with their tickets after asking: see them, read and answer the thread,
reopen and rate (F3 UC-F3-02 … UC-F3-05), and the sweep that closes stale waits (BR-F3-11)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.chat.utils.conversations import conversations
from apps.fewshot.models import FewshotExample
from apps.lifecycle.models import Transfer
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.vocabulary import TRIAGE_STATUSES, PipelineStatus
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.requester.utils.vocabulary import (
    AUTO_CLOSED_COMMENT,
    RELATED_TO,
    RequesterError,
    RequesterRefusal,
)
from apps.review.models import EvalCandidate
from apps.sla.models import Calendar, ClockKind, ClockState
from apps.sla.utils.business_time import BusinessCalendar, parse_hours
from apps.sla.utils.clocks import holidays_of
from apps.teams.utils.assignment import assignment
from apps.teams.utils.vocabulary import AssignmentTrigger
from apps.tickets.models import (
    CommentAuthorKind,
    CommentVisibility,
    Ticket,
    TicketComment,
    TicketRating,
    TicketSource,
)
from apps.tickets.request_schema import TicketIn
from apps.tickets.utils.comments import comments
from apps.tickets.utils.patterns import PIILevel

logger = logging.getLogger(__name__)

# The status a requester's reply resumes when the status before the wait is a pipeline one.
_RESUME_FALLBACK = "in_progress"
# Older completed tickets My tickets hands out per "Xem thêm".
_PAGE = 20


@dataclass(frozen=True)
class Listing:
    open: list[Ticket]
    recent: list[Ticket]
    # Pass as `before` for the next page of older completed tickets; None when there is none.
    more_before: datetime | None


@dataclass(frozen=True)
class Reopened:
    reopened: bool
    new_ticket: str | None = None


class RequesterTickets:
    """A requester's own tickets: anyone else's is not found (BR-F3-04)."""

    def own(self, requester: User, public_id: str) -> Ticket:
        ticket = Ticket.objects.for_requester(requester).filter(public_id=public_id).first()
        if ticket is None:
            raise RequesterError(404, RequesterRefusal.TICKET_NOT_FOUND, "no such ticket")
        return ticket

    def listing(self, requester: User, before: datetime | None = None) -> Listing:
        """Open tickets by last change, then those completed in `list_resolved_days`; with
        `before`, the next page of older completed tickets (UC-F3-02)."""
        tickets = Ticket.objects.for_requester(requester)
        completed = tickets.filter(resolved_at__isnull=False).order_by("-resolved_at")
        if before is None:
            days = settings.THRESHOLDS.requester.list_resolved_days
            open_ = list(tickets.filter(resolved_at__isnull=True).order_by(F("last_update").desc()))
            recent = list(completed.filter(resolved_at__gte=timezone.now() - timedelta(days=days)))
            cursor = recent[-1].resolved_at if recent else timezone.now()
        else:
            open_ = []
            recent = list(completed.filter(resolved_at__lt=before)[:_PAGE])
            cursor = recent[-1].resolved_at if len(recent) == _PAGE else None
        more = cursor is not None and completed.filter(resolved_at__lt=cursor).exists()
        return Listing(open_, recent, cursor if more else None)

    # ── what a row shows ──

    def reopen_until(self, ticket: Ticket) -> datetime | None:
        """Until when the requester may reopen or rate the ticket; None while it is open."""
        if ticket.resolved_at is None:
            return None
        return ticket.resolved_at + timedelta(days=settings.THRESHOLDS.requester.reopen_window_days)

    def rating(self, ticket: Ticket) -> TicketRating | None:
        """The rating of the ticket's current resolution."""
        return next(
            (r for r in ticket.ratings.all() if r.resolution_seq == ticket.resolution_seq), None
        )

    def resolution_clock(self, ticket: Ticket) -> dict[str, Any]:
        """The resolution clock's due time and pause, the only SLA a requester sees (F1)."""
        clock = next((c for c in ticket.sla_clocks.all() if c.kind == ClockKind.RESOLUTION), None)
        paused = clock is not None and clock.state == ClockState.PAUSED.value
        open_ = clock is not None and clock.met_at is None
        return {
            "resolution_due_at": clock.due_at if open_ and not paused and clock else None,
            "sla_paused": paused,
        }

    def unread(self, ticket: Ticket) -> int:
        """Support's public comments since the requester last wrote."""
        thread = ticket.comments.public().for_staff().filter(discarded_at__isnull=True)
        last = (
            thread.filter(author_kind=CommentAuthorKind.REQUESTER.value)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        theirs = thread.exclude(author_kind=CommentAuthorKind.REQUESTER.value)
        return (theirs.filter(created_at__gt=last) if last else theirs).count()

    def thread(self, ticket: Ticket) -> list[TicketComment]:
        """The public thread as the requester may see it: support's visible comments and every
        comment of their own, held or discarded ones included."""
        return [
            c
            for c in ticket.comments.public().select_related("author").order_by("created_at")
            if c.author_kind == CommentAuthorKind.REQUESTER.value
            or (not c.hidden_for_review and c.discarded_at is None)
        ]

    # ── replying ──

    def reply(self, requester: User, public_id: str, body: str) -> TicketComment:
        """Masks and stores the reply; a ticket waiting on its requester moves back through the
        workflow (UC-F3-03, BR-F3-07)."""
        ticket = self.own(requester, public_id)
        if ticket.status in TRIAGE_STATUSES:
            raise RequesterError(
                409, RequesterRefusal.TICKET_IN_TRIAGE, "answer in the chat while it is analysed"
            )
        if ticket.resolved_at is not None:
            raise RequesterError(
                409,
                RequesterRefusal.TICKET_CLOSED,
                "the ticket is resolved; reopen it or ask a new question",
                details={"can_reopen_until": self.reopen_until(ticket)},
            )
        comment = comments.add(
            ticket,
            body,
            author=requester,
            kind=CommentAuthorKind.REQUESTER,
            visibility=CommentVisibility.PUBLIC,
        )
        moved_to = self.resume(ticket)
        AuditLog.objects.record(
            "requester_replied",
            actor_type="human",
            actor_id=requester.id,
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "comment": str(comment.id),
                "resumed_to": moved_to,
            },
        )
        comments.announce(ticket, comment, requester)
        return comment

    def resume(self, ticket: Ticket) -> str | None:
        """Moves a ticket out of `waiting_on_requester` to the status before it; the status key it
        moved to, or None when it wasn't waiting or the workflow refused."""
        status = ticket.workflow_status
        if status is None or not status.pauses_sla:
            return None
        entered = (
            Transfer.objects.filter(ticket=ticket, after_status=status, committed_at__isnull=False)
            .select_related("before_status")
            .order_by("-committed_at")
            .first()
        )
        before = entered.before_status if entered else None
        target = (
            before.key
            if before is not None and not before.is_pipeline and not before.pauses_sla
            else _RESUME_FALLBACK
        )
        try:
            lifecycle.automatic_move(ticket, target)
        except LifecycleError as e:
            AuditLog.objects.record(
                "requester_reply_move_refused",
                actor_type="system",
                ticket_id=ticket.id,
                payload={"ticket_public_id": ticket.public_id, "to": target, "code": e.code.value},
            )
            return None
        return target

    # ── reopening ──

    def reopen(self, requester: User, public_id: str, reason: str) -> Reopened:
        """Reopens within the window, else submits a new ticket linked to this one (UC-F3-04)."""
        reason = reason.strip()
        if not reason:
            raise RequesterError(422, RequesterRefusal.REASON_REQUIRED, "say why it isn't solved")
        ticket = self.own(requester, public_id)
        until = self.reopen_until(ticket)
        if until is None:
            raise RequesterError(409, RequesterRefusal.NOT_RESOLVED, "the ticket is still open")
        if timezone.now() > until:
            linked = Ticket.objects.submit(
                reporter=requester,
                ticket_in=TicketIn(
                    subject=f"{RELATED_TO} {ticket.public_id}",
                    body=f"{reason}\n\n{RELATED_TO} {ticket.public_id}",
                ),
                trace_id=None,
                source=TicketSource.FORM,
                reopened_from=ticket,
            )
            AuditLog.objects.record(
                "ticket_reopen_linked",
                actor_type="human",
                actor_id=requester.id,
                ticket_id=ticket.id,
                payload={"ticket_public_id": ticket.public_id, "new_ticket": linked.public_id},
            )
            return Reopened(reopened=False, new_ticket=linked.public_id)
        comment = comments.add(
            ticket,
            reason,
            author=requester,
            kind=CommentAuthorKind.REQUESTER,
            visibility=CommentVisibility.PUBLIC,
        )
        self.reopen_now(ticket.id, requester, comment)
        return Reopened(reopened=True)

    def reopen_now(
        self, ticket_id: uuid.UUID, actor: User | None, reason: TicketComment | None = None
    ) -> Ticket:
        """Moves a completed ticket to `reopened`, retracts its few-shot examples, labels a reopened
        auto-reply for evals and hands the ticket back to its assignee or team (BR-F3-08, 09)."""
        with transaction.atomic():
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            if ticket.resolved_at is None:
                raise RequesterError(409, RequesterRefusal.NOT_RESOLVED, "the ticket is still open")
            auto_replied = ticket.transfers.filter(
                after_status__key=PipelineStatus.AUTO_REPLIED.value
            ).exists()
            ticket.reopened_count += 1
            ticket.save(update_fields=["reopened_count"])
            lifecycle.system_move(ticket, PipelineStatus.REOPENED)
            FewshotExample.objects.retract_for_ticket(ticket)
            AuditLog.objects.record(
                "ticket_reopened",
                actor_type="human" if actor else "system",
                actor_id=actor.id if actor else None,
                ticket_id=ticket.id,
                payload={
                    "ticket_public_id": ticket.public_id,
                    "reopened_count": ticket.reopened_count,
                    "auto_replied": auto_replied,
                },
            )
            if auto_replied:
                EvalCandidate.objects.create(
                    ticket=ticket,
                    source="reopen",
                    ai_prediction=self.auto_reply_proposal(ticket),
                    human_truth={
                        "resolved": False,
                        "reason_masked": reason.body_masked if reason else None,
                    },
                )
        assignment.assign_after_handoff(ticket, AssignmentTrigger.REOPEN)
        notifier.emit(
            NotificationEvent.TICKET_REOPENED,
            ticket,
            Notice(
                actor=actor.username if actor else "system",
                message=reason.body_masked if reason and not reason.hidden_for_review else "",
                data={"reopened_count": ticket.reopened_count},
            ),
        )
        return ticket

    def auto_reply_proposal(self, ticket: Ticket) -> dict[str, Any]:
        """The proposal of the auto-reply the requester was given."""
        decision = (
            ticket.routing_decisions.filter(branch="auto_reply")
            .select_related("ai_run")
            .order_by("-decided_at")
            .first()
        )
        if decision is None or decision.ai_run is None:
            return {}
        return decision.ai_run.proposed_draft or {}

    # ── rating ──

    def rate(
        self, requester: User, public_id: str, score: int, comment: str | None
    ) -> TicketRating:
        """Saves or changes the rating of the current resolution while the reopen window is open; a
        low one alerts the team lead and never reopens (UC-F3-05, BR-F3-10)."""
        if not 1 <= score <= 5:
            raise RequesterError(422, RequesterRefusal.BAD_SCORE, "a rating is 1 to 5")
        ticket = self.own(requester, public_id)
        until = self.reopen_until(ticket)
        if until is None:
            raise RequesterError(409, RequesterRefusal.NOT_RESOLVED, "the ticket is still open")
        if timezone.now() > until:
            raise RequesterError(
                409, RequesterRefusal.RATING_WINDOW_CLOSED, "ratings close with the reopen window"
            )
        text = (comment or "").strip()
        masked = comments.mask(ticket, text) if text else None
        with transaction.atomic():
            locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
            comment_masked = None
            if masked is not None and masked.pii_level is not PIILevel.MASK_FAILED:
                if not set(masked.placeholder_map) & set(locked.pii_map):
                    comments.keep_pii(locked, masked)
                    comment_masked = masked.text_masked
                    if masked.pii_level is PIILevel.CRITICAL:
                        comments.alert(locked, requester, "credential_in_rating", public_id)
            rating, created = TicketRating.objects.update_or_create(
                ticket=locked,
                resolution_seq=locked.resolution_seq,
                defaults={"score": score, "comment_masked": comment_masked},
            )
            AuditLog.objects.record(
                "ticket_rated",
                actor_type="human",
                actor_id=requester.id,
                ticket_id=locked.id,
                payload={
                    "ticket_public_id": locked.public_id,
                    "score": score,
                    "resolution_seq": locked.resolution_seq,
                    "changed": not created,
                    "comment_dropped": masked is not None and comment_masked is None,
                },
            )
            if score <= settings.THRESHOLDS.requester.low_rating_at_most:
                self.rated_low(locked, rating)
        return rating

    def rated_low(self, ticket: Ticket, rating: TicketRating) -> None:
        """Tells the team lead, once per resolution, and labels a low-rated auto-reply for evals."""
        seq = rating.resolution_seq
        notifier.emit(
            NotificationEvent.TICKET_RATED_LOW,
            ticket,
            Notice(
                reason=str(rating.score),
                message=rating.comment_masked or "",
                data={"score": rating.score, "resolution_seq": seq},
            ),
            event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"rated_low:{ticket.id}:{seq}"),
        )
        auto_replied = ticket.status == PipelineStatus.AUTO_REPLIED.value
        labelled = EvalCandidate.objects.filter(
            ticket=ticket, source="low_rating", human_truth__resolution_seq=seq
        ).exists()
        if auto_replied and not labelled:
            EvalCandidate.objects.create(
                ticket=ticket,
                source="low_rating",
                ai_prediction=self.auto_reply_proposal(ticket),
                human_truth={
                    "score": rating.score,
                    "comment_masked": rating.comment_masked,
                    "resolution_seq": seq,
                },
            )

    # ── the sweep ──

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Ends idle conversations and resolves tickets left waiting on their requester."""
        now = now or timezone.now()
        return {"conversations_ended": conversations.end_idle(now), "closed": self.close_stale(now)}

    def close_stale(self, now: datetime) -> int:
        """Resolves each ticket waiting on its requester for `auto_close_after_business_days`
        working days of its team's calendar (BR-F3-11)."""
        days = settings.THRESHOLDS.requester.auto_close_after_business_days
        closed = 0
        waiting = Ticket.objects.filter(workflow_status__pauses_sla=True).select_related(
            "team__calendar", "workflow_status"
        )
        for ticket in waiting:
            entered = (
                Transfer.objects.filter(
                    ticket=ticket, after_status_id=ticket.workflow_status_id, committed_at__lte=now
                )
                .order_by("-committed_at")
                .values_list("committed_at", flat=True)
                .first()
            )
            if entered is None or self.calendar(ticket).whole_days(entered, now) < days:
                continue
            closed += self.close(ticket)
        return closed

    def calendar(self, ticket: Ticket) -> BusinessCalendar:
        """The team's calendar, else the default one, with its holidays."""
        calendar = ticket.team.calendar if ticket.team and ticket.team.calendar else None
        calendar = calendar or Calendar.objects.filter(is_default=True).first()
        if calendar is None:
            return BusinessCalendar(ZoneInfo("UTC"), {}, frozenset(), is_24x7=True)
        return BusinessCalendar(
            ZoneInfo(calendar.timezone),
            parse_hours(calendar.working_hours),
            holidays_of(calendar.id),
        )

    def close(self, ticket: Ticket) -> int:
        """Resolves one stale wait once, under the ticket's lock; 1 when it closed."""
        with transaction.atomic():
            locked = (
                Ticket.objects.select_for_update(of=("self",))
                .select_related("workflow_status")
                .get(pk=ticket.pk)
            )
            if locked.workflow_status is None or not locked.workflow_status.pauses_sla:
                return 0
            refused = AuditLog.objects.filter(
                event="ticket_auto_close_refused",
                ticket_id=locked.id,
                payload__status_entered_version=locked.version,
            ).exists()
            if refused:
                return 0
            try:
                with transaction.atomic():
                    lifecycle.automatic_move(locked, "resolved")
            except LifecycleError as e:
                AuditLog.objects.record(
                    "ticket_auto_close_refused",
                    actor_type="system",
                    ticket_id=locked.id,
                    payload={
                        "ticket_public_id": locked.public_id,
                        "code": e.code.value,
                        "status_entered_version": locked.version,
                    },
                )
                return 0
            comments.system(locked, AUTO_CLOSED_COMMENT)
            AuditLog.objects.record(
                "ticket_auto_closed",
                actor_type="system",
                ticket_id=locked.id,
                payload={"ticket_public_id": locked.public_id},
            )
        return 1


# --- the requester tickets service ---

requester_tickets = RequesterTickets()
