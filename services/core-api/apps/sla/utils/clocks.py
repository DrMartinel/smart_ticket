"""SLA clocks on tickets: started at handoff, paused while waiting on the requester, met on a
response or a resolution, warned, breached and escalated by the sweep (F1, ADR-0030)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.sla.models import (
    OPEN_CLOCK_STATES,
    Calendar,
    Clock,
    ClockEvent,
    ClockEventKind,
    ClockKind,
    ClockState,
    Holiday,
    Policy,
    Priority,
    Rebuild,
)
from apps.sla.utils.business_time import BusinessCalendar, parse_hours

if TYPE_CHECKING:
    from apps.lifecycle.models import Transfer, WorkflowStatus
    from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)

_SLA_NAMESPACE = uuid.UUID("8d1c3c2e-6c3a-4f2e-9a51-0f1f6a3b7e21")
_COUNTING = (ClockState.RUNNING.value, ClockState.BREACHED.value)
_STAFF = (UserRole.TECHNICIAN.value, UserRole.MANAGER.value, UserRole.SECURITY.value)


class SlaRefusal(StrEnum):
    REASON_REQUIRED = "reason_required"
    VERSION_CONFLICT = "version_conflict"
    NOT_ALLOWED = "not_allowed"
    NO_CLOCK = "no_clock"
    NO_POLICY = "no_policy"


class SlaError(CodedError):
    """An SLA request core-api refuses (BR-X-08)."""


@dataclass(frozen=True)
class Due:
    due_at: datetime
    warn_at: datetime


@dataclass(frozen=True)
class BadgeLine:
    """One clock's state and use, for the badge tooltip."""

    kind: str
    state: str
    due_at: datetime | None
    met_at: datetime | None
    elapsed_minutes: int
    target_minutes: int
    warned: bool

    def level(self) -> str:
        """on_track, at_risk, breached, paused or met (F1 · SLA badge 8-604)."""
        if self.state == ClockState.PAUSED.value:
            return "paused"
        if self.state == ClockState.MET.value:
            return "met"
        if self.state == ClockState.BREACHED.value or self.elapsed_minutes >= self.target_minutes:
            return "breached"
        return "at_risk" if self.warned else "on_track"


@dataclass(frozen=True)
class Badge:
    kind: str
    level: str
    remaining_minutes: int
    due_at: datetime | None
    policy: str
    calendar: str
    clocks: list[BadgeLine]


@dataclass(frozen=True)
class Preview:
    policy: str
    calendar: str
    response: Due
    resolution: Due


def initial_priority(ticket: Ticket) -> Priority:
    """P1 for a ticket in an open incident, P2 for security, else P3; never from a proposal
    (BR-F1-02)."""
    incident = ticket.incident if ticket.incident_id is not None else None
    if incident is not None and incident.status == "open":
        return Priority.P1
    if ticket.category == "security":
        return Priority.P2
    return Priority.P3


def snapshot_of(policy: Policy, calendar: Calendar) -> dict[str, Any]:
    """The targets and calendar a clock keeps for its whole life (BR-F1-05)."""
    return {
        "policy": policy.name,
        "order": policy.order,
        "response_minutes": policy.response_minutes,
        "resolution_minutes": policy.resolution_minutes,
        "is_24x7": policy.is_24x7,
        "calendar": {
            "id": str(calendar.id),
            "name": calendar.name,
            "timezone": calendar.timezone,
            "working_hours": calendar.working_hours,
        },
    }


def holidays_of(calendar_id: Any) -> frozenset[date]:
    return frozenset(Holiday.objects.filter(calendar_id=calendar_id).values_list("date", flat=True))


class SlaClocks:
    """Every change to a ticket's SLA clocks; a failure never reaches the status move (BR-F1-11)."""

    # ── what the engine and the review service call ──

    def on_status_entered(self, ticket: Ticket, transfer: Transfer) -> None:
        """Starts, pauses, resumes or stops clocks for a committed status change."""
        manual = transfer.trigger in ("manual", "force")
        self.guarded(
            ticket,
            lambda: self.apply(
                ticket,
                transfer.before_status,
                transfer.after_status,
                transfer.committed_at or timezone.now(),
                transfer=transfer,
                actor=transfer.actor if manual else None,
            ),
        )

    def responded(self, ticket: Ticket, actor: User) -> None:
        """A person acted on the ticket: the response clock is met (BR-F1-06)."""
        self.guarded(ticket, lambda: self.respond(ticket, actor, timezone.now(), None))

    def guarded(self, ticket: Ticket, change: Any) -> None:
        try:
            with transaction.atomic():
                change()
        except Exception as e:  # noqa: BLE001 — an SLA error never fails the move (BR-F1-11)
            logger.exception("SLA update for %s failed", ticket.public_id)
            Rebuild.objects.get_or_create(ticket=ticket)
            AuditLog.objects.record(
                "sla_update_failed",
                actor_type="system",
                ticket_id=ticket.id,
                payload={"ticket_public_id": ticket.public_id, "error": type(e).__name__},
            )

    # ── status changes ──

    def apply(
        self,
        ticket: Ticket,
        before: WorkflowStatus | None,
        after: WorkflowStatus | None,
        at: datetime,
        *,
        transfer: Transfer | None,
        actor: User | None,
    ) -> None:
        if after is None:
            return
        base = after.base
        clocks = self.locked(ticket)
        if base.is_backlog:
            for clock in clocks.values():
                if clock.state in OPEN_CLOCK_STATES:
                    self.finish(clock, ClockState.CANCELLED, ClockEventKind.CANCEL, at, transfer)
            self.mirror(ticket)
            return
        if not any(c.state != ClockState.CANCELLED.value for c in clocks.values()):
            if base.is_completed:
                return
            clocks = self.start(ticket, at, transfer)
        if actor is not None and actor.role in _STAFF:
            self.respond(ticket, actor, at, transfer)
        resolution = clocks[ClockKind.RESOLUTION.value]
        if base.is_completed:
            for clock in self.locked(ticket).values():
                if clock.state in OPEN_CLOCK_STATES:
                    self.finish(clock, ClockState.MET, ClockEventKind.MET, at, transfer)
            self.mirror(ticket)
            return
        resolution.refresh_from_db()
        if resolution.state == ClockState.MET.value:
            self.reopen(resolution, at, transfer)
        was_paused = before is not None and before.pauses_sla
        if after.pauses_sla and not was_paused:
            for clock in self.locked(ticket).values():
                if clock.state in _COUNTING:
                    self.pause(clock, at, transfer)
        elif was_paused and not after.pauses_sla:
            for clock in self.locked(ticket).values():
                if clock.state == ClockState.PAUSED.value:
                    self.resume(clock, at, transfer)
        self.mirror(ticket)

    def start(self, ticket: Ticket, at: datetime, transfer: Transfer | None) -> dict[str, Clock]:
        """Picks priority, policy and calendar and starts both clocks at handoff (UC-F1-01)."""
        if not ticket.priority:
            ticket.priority = initial_priority(ticket).value
            ticket.save(update_fields=["priority"])
        policy = Policy.objects.matching(ticket.category, ticket.priority)
        if policy is None:
            raise SlaError(409, SlaRefusal.NO_POLICY, "no active SLA policy matches")
        calendar = self.calendar_for(policy, ticket)
        snapshot = snapshot_of(policy, calendar)
        Clock.objects.filter(ticket=ticket).delete()
        clocks = {}
        for kind in ClockKind:
            clock = Clock(
                ticket=ticket,
                kind=kind.value,
                policy=policy,
                policy_snapshot=snapshot,
                state=ClockState.RUNNING.value,
                started_at=at,
                elapsed_as_of=at,
            )
            self.recompute(clock, at)
            clock.save()
            self.event(clock, ClockEventKind.START, at, transfer)
            clocks[kind.value] = clock
        AuditLog.objects.record(
            "sla_started",
            actor_type="system",
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "priority": ticket.priority,
                "policy": policy.name,
                "calendar": calendar.name,
                "response_due": clocks["response"].due_at.isoformat()
                if clocks["response"].due_at
                else None,
                "resolution_due": clocks["resolution"].due_at.isoformat()
                if clocks["resolution"].due_at
                else None,
            },
        )
        if policy.is_default():
            AuditLog.objects.record(
                "sla_policy_fallback",
                actor_type="system",
                ticket_id=ticket.id,
                payload={"category": ticket.category, "priority": ticket.priority},
            )
        return clocks

    def calendar_for(self, policy: Policy, ticket: Ticket | None) -> Calendar:
        """The policy's calendar, else the ticket's team's, else the default (BR-F1-04)."""
        if policy.calendar_id is not None:
            assert policy.calendar is not None
            return policy.calendar
        team = ticket.team if ticket is not None else None
        if team is not None and team.calendar_id is not None:
            assert team.calendar is not None
            return team.calendar
        default = Calendar.objects.filter(is_default=True).first()
        if default is None:
            raise SlaError(409, SlaRefusal.NO_POLICY, "no default business calendar")
        return default

    def respond(self, ticket: Ticket, actor: User, at: datetime, transfer: Transfer | None) -> None:
        clock = self.locked(ticket).get(ClockKind.RESPONSE.value)
        if clock is not None and clock.state in OPEN_CLOCK_STATES:
            self.finish(clock, ClockState.MET, ClockEventKind.MET, at, transfer, actor=actor)

    def pause(self, clock: Clock, at: datetime, transfer: Transfer | None) -> None:
        self.fold(clock, at)
        clock.state = ClockState.PAUSED.value
        clock.paused_at = at
        clock.due_at = clock.warn_at = clock.escalate_at = None
        clock.save()
        self.event(clock, ClockEventKind.PAUSE, at, transfer)
        self.audit(clock, "sla_paused", at)

    def resume(self, clock: Clock, at: datetime, transfer: Transfer | None) -> None:
        clock.state = ClockState.BREACHED.value if clock.breached_at else ClockState.RUNNING.value
        clock.paused_at = None
        clock.elapsed_as_of = at
        self.recompute(clock, at)
        clock.save()
        self.event(clock, ClockEventKind.RESUME, at, transfer)
        self.audit(clock, "sla_resumed", at)

    def reopen(self, clock: Clock, at: datetime, transfer: Transfer | None) -> None:
        """A reopened ticket's resolution clock runs again with its elapsed kept (BR-F1-13)."""
        clock.state = ClockState.BREACHED.value if clock.breached_at else ClockState.RUNNING.value
        clock.met_at = None
        clock.elapsed_as_of = at
        self.recompute(clock, at)
        clock.save()
        self.event(clock, ClockEventKind.REOPEN, at, transfer)
        self.audit(clock, "sla_resumed", at)

    def finish(
        self,
        clock: Clock,
        state: ClockState,
        kind: ClockEventKind,
        at: datetime,
        transfer: Transfer | None,
        *,
        actor: User | None = None,
    ) -> None:
        self.fold(clock, at)
        clock.state = state.value
        if state is ClockState.MET:
            clock.met_at = at
        clock.warn_at = clock.escalate_at = None
        clock.save()
        self.event(clock, kind, at, transfer, actor=actor)
        if state is ClockState.MET:
            self.audit(clock, "sla_met", at, breached=clock.breached_at is not None)

    # ── the arithmetic ──

    def fold(self, clock: Clock, at: datetime) -> None:
        """Adds the business time counted since `elapsed_as_of` and moves it to `at`."""
        calendar = clock.calendar(holidays_of(clock.policy_snapshot["calendar"]["id"]))
        clock.elapsed_business_sec = clock.elapsed_at(at, calendar)
        clock.elapsed_as_of = at

    def recompute(self, clock: Clock, at: datetime) -> None:
        """Due, warning and escalation times from the business time left, on today's holidays."""
        calendar = clock.calendar(holidays_of(clock.policy_snapshot["calendar"]["id"]))
        self.fold(clock, at)
        target = clock.target_minutes() * 60
        thresholds = settings.THRESHOLDS.sla
        elapsed = clock.elapsed_business_sec

        def at_share(share: float, known: datetime | None) -> datetime:
            left = share * target - elapsed
            if left <= 0 and known is not None and known <= at:
                return known
            return calendar.add(at, max(0.0, left))

        clock.due_at = at_share(1.0, clock.due_at)
        clock.warn_at = at_share(thresholds.warn_at_percent / 100, clock.warn_at)
        clock.escalate_at = at_share(thresholds.escalate_at_percent / 100, clock.escalate_at)

    def mirror(self, ticket: Ticket) -> None:
        """Keeps `tickets.sla_due_at` equal to the counting resolution clock's due time."""
        resolution = Clock.objects.filter(ticket=ticket, kind=ClockKind.RESOLUTION.value).first()
        due = resolution.due_at if resolution and resolution.state in _COUNTING else None
        if ticket.sla_due_at != due:
            ticket.sla_due_at = due
            ticket.save(update_fields=["sla_due_at"])

    def locked(self, ticket: Ticket) -> dict[str, Clock]:
        return {c.kind: c for c in Clock.objects.select_for_update().filter(ticket=ticket)}

    def event(
        self,
        clock: Clock,
        kind: ClockEventKind,
        at: datetime,
        transfer: Transfer | None,
        *,
        actor: User | None = None,
    ) -> None:
        ClockEvent.objects.create(
            clock=clock,
            event=kind.value,
            at=at,
            transfer=transfer,
            actor=actor,
            elapsed_business_sec=clock.elapsed_business_sec,
        )

    def audit(self, clock: Clock, event: str, at: datetime, **extra: Any) -> None:
        AuditLog.objects.record(
            event,
            actor_type="system",
            ticket_id=clock.ticket_id,
            payload={
                "kind": clock.kind,
                "at": at.isoformat(),
                "elapsed_minutes": clock.elapsed_business_sec // 60,
                **extra,
            },
        )

    # ── people ──

    def change_priority(
        self, ticket: Ticket, actor: User, priority: Priority, reason: str, expected_version: int
    ) -> Ticket:
        """Sets the priority with a reason and retargets running clocks, elapsed kept (UC-F1-05)."""
        from apps.tickets.models import Ticket as TicketModel

        if not reason.strip():
            raise SlaError(422, SlaRefusal.REASON_REQUIRED, "say why the priority changes")
        with transaction.atomic():
            locked = (
                TicketModel.objects.select_for_update(of=("self",))
                .select_related("team")
                .get(pk=ticket.pk)
            )
            if locked.version != expected_version:
                raise SlaError(
                    409, SlaRefusal.VERSION_CONFLICT, "the ticket changed; reload and try again"
                )
            self.check_may_change(locked, actor)
            before = locked.priority
            locked.priority = priority.value
            locked.version += 1
            locked.save(update_fields=["priority", "version"])
            AuditLog.objects.record(
                "ticket_priority_changed",
                actor_type="human",
                actor_id=actor.id,
                ticket_id=locked.id,
                payload={"before": before, "after": priority.value, "reason": reason.strip()},
            )
            self.retarget(locked, actor, timezone.now())
        return locked

    def check_may_change(self, ticket: Ticket, actor: User) -> None:
        """The assignee, the team lead or a manager (UC-F1-05)."""
        if actor.role == UserRole.MANAGER.value or ticket.assigned_to_id == actor.id:
            return
        if ticket.team is not None and ticket.team.is_lead(actor):
            return
        raise SlaError(403, SlaRefusal.NOT_ALLOWED, "only the assignee, the team lead or a manager")

    def retarget(self, ticket: Ticket, actor: User | None, at: datetime) -> None:
        """Moves open clocks to the policy now matching, keeping their business time (BR-F1-10)."""
        policy = Policy.objects.matching(ticket.category, ticket.priority)
        if policy is None:
            return
        snapshot = snapshot_of(policy, self.calendar_for(policy, ticket))
        for clock in self.locked(ticket).values():
            if clock.state not in OPEN_CLOCK_STATES:
                continue
            before = clock.target_minutes()
            if clock.state != ClockState.PAUSED.value:
                self.fold(clock, at)
            clock.policy = policy
            clock.policy_snapshot = snapshot
            breached_now = (
                clock.elapsed_business_sec >= clock.target_minutes() * 60
                and clock.breached_at is None
            )
            if clock.state != ClockState.PAUSED.value:
                if breached_now:
                    clock.state = ClockState.BREACHED.value
                    clock.breached_at = at
                self.recompute(clock, at)
            clock.save()
            self.event(clock, ClockEventKind.RETARGET, at, None, actor=actor)
            self.audit(clock, "sla_retargeted", at, before=before, after=clock.target_minutes())
            if breached_now and clock.state == ClockState.BREACHED.value:
                self.notify(clock, NotificationEvent.SLA_BREACHED)
        self.mirror(ticket)

    def override(self, ticket: Ticket, business_hours: float, reason: str) -> Clock:
        """A workflow action's manual resolution target, in business hours (FR-F1-012)."""
        clock = self.locked(ticket).get(ClockKind.RESOLUTION.value)
        if clock is None or clock.state not in OPEN_CLOCK_STATES:
            raise SlaError(409, SlaRefusal.NO_CLOCK, "the ticket has no running SLA clock")
        at = timezone.now()
        before = clock.target_minutes()
        clock.override_minutes = round(business_hours * 60)
        if clock.state != ClockState.PAUSED.value:
            self.recompute(clock, at)
        clock.save()
        self.event(clock, ClockEventKind.OVERRIDE, at, None)
        self.audit(
            clock, "sla_override", at, before=before, after=clock.override_minutes, reason=reason
        )
        self.mirror(ticket)
        return clock

    # ── the sweep ──

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Rebuilds failed clocks, then fires each due warning, breach and escalation once."""
        now = now or timezone.now()
        rebuilt = 0
        for request in Rebuild.objects.select_related("ticket"):
            self.rebuild(request.ticket)
            rebuilt += 1
        counts = {"rebuilt": rebuilt, "warned": 0, "breached": 0, "escalated": 0}
        with transaction.atomic():
            for clock in self.due(
                Q(state=ClockState.RUNNING.value, warn_at__lte=now, warned_at__isnull=True)
            ):
                clock.warned_at = now
                clock.save(update_fields=["warned_at"])
                self.notify(clock, NotificationEvent.SLA_WARNING)
                counts["warned"] += 1
            for clock in self.due(
                Q(state=ClockState.RUNNING.value, due_at__lte=now, breached_at__isnull=True)
            ):
                clock.state = ClockState.BREACHED.value
                clock.breached_at = clock.due_at
                clock.save(update_fields=["state", "breached_at"])
                self.event(clock, ClockEventKind.BREACH, now, None)
                self.audit(clock, "sla_breached", now)
                self.notify(clock, NotificationEvent.SLA_BREACHED)
                counts["breached"] += 1
            for clock in self.due(
                Q(state__in=_COUNTING, escalate_at__lte=now, escalated_at__isnull=True)
            ):
                clock.escalated_at = now
                clock.save(update_fields=["escalated_at"])
                self.audit(clock, "sla_escalated", now)
                self.notify(clock, NotificationEvent.SLA_BREACHED_ESCALATED)
                counts["escalated"] += 1
        return counts

    def due(self, condition: Q) -> list[Clock]:
        return list(
            Clock.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("ticket", "ticket__assigned_to", "ticket__team")
            .filter(condition)
        )

    def notify(self, clock: Clock, event: NotificationEvent) -> None:
        """One notice per clock and level, however often the sweep runs or the clock is rebuilt
        (BR-F1-08)."""
        due = clock.due_at
        zone = ZoneInfo(clock.policy_snapshot["calendar"]["timezone"])
        notifier.emit(
            event,
            clock.ticket,
            Notice(
                reason=clock.kind,
                detail=due.astimezone(zone).strftime("%d/%m %H:%M") if due else "",
                data={"target": clock.kind, "due_at": due.isoformat() if due else None},
            ),
            event_id=uuid.uuid5(
                _SLA_NAMESPACE,
                f"{clock.ticket_id}:{clock.kind}:{clock.started_at.isoformat()}:{event.value}",
            ),
        )

    # ── rebuilding from the transfer log ──

    def rebuild(self, ticket: Ticket, actor: User | None = None) -> list[Clock]:
        """Recreates a ticket's clocks by replaying its status changes and responses (FR-F1-015)."""
        from apps.lifecycle.models import Transfer
        from apps.review.models import ReviewDecision

        with transaction.atomic():
            Clock.objects.filter(ticket=ticket).delete()
            moves = list(
                Transfer.objects.filter(ticket=ticket, committed_at__isnull=False)
                .select_related("before_status__base", "after_status__base", "actor")
                .order_by("committed_at")
            )
            decisions = list(
                ReviewDecision.objects.filter(review_item__ticket=ticket).select_related("reviewer")
            )
            timeline: list[tuple[datetime, Any]] = [
                (m.committed_at, m) for m in moves if m.committed_at
            ]
            timeline += [(d.decided_at, d) for d in decisions]
            for at, item in sorted(timeline, key=lambda pair: pair[0]):
                if isinstance(item, ReviewDecision):
                    self.respond(ticket, item.reviewer, at, None)
                    continue
                manual = item.trigger in ("manual", "force")
                self.apply(
                    ticket,
                    item.before_status,
                    item.after_status,
                    at,
                    transfer=item,
                    actor=item.actor if manual else None,
                )
            now = timezone.now()
            clocks = list(Clock.objects.filter(ticket=ticket))
            for clock in clocks:
                if clock.state in _COUNTING:
                    self.recompute(clock, now)
                    clock.save()
                self.event(clock, ClockEventKind.REBUILD, now, None, actor=actor)
            self.mirror(ticket)
            Rebuild.objects.filter(ticket=ticket).delete()
            AuditLog.objects.record(
                "sla_rebuilt",
                actor_type="human" if actor else "system",
                actor_id=actor.id if actor else None,
                ticket_id=ticket.id,
                payload={"clocks": len(clocks)},
            )
        return clocks

    # ── reading ──

    def view(self, ticket: Ticket, *, staff: bool) -> dict[str, Any]:
        """The ticket's clocks now; a requester sees only the resolution clock's state and due."""
        now = timezone.now()
        clocks = list(Clock.objects.filter(ticket=ticket).order_by("kind"))
        rows = []
        for clock in clocks:
            if not staff and clock.kind != ClockKind.RESOLUTION.value:
                continue
            calendar = clock.calendar(holidays_of(clock.policy_snapshot["calendar"]["id"]))
            elapsed = clock.elapsed_at(now, calendar) // 60
            target = clock.target_minutes()
            rows.append(
                {
                    "kind": clock.kind,
                    "state": clock.state,
                    "target_minutes": target if staff else 0,
                    "elapsed_minutes": elapsed if staff else 0,
                    "remaining_minutes": max(0, target - elapsed) if staff else 0,
                    "due_at": clock.due_at,
                    "warn_at": clock.warn_at if staff else None,
                    "met_at": clock.met_at,
                    "breached_at": clock.breached_at if staff else None,
                    "paused": clock.state == ClockState.PAUSED.value,
                    "breached": clock.breached_at is not None,
                    "warned": clock.warned_at is not None,
                }
            )
        snapshot = clocks[0].policy_snapshot if clocks else None
        return {
            "priority": ticket.priority,
            "policy": snapshot["policy"] if snapshot and staff else None,
            "calendar": snapshot["calendar"]["name"] if snapshot and staff else None,
            "clocks": rows,
        }

    def badge(self, ticket: Ticket) -> Badge | None:
        """The SLA badge: the response clock until it is met, then the resolution clock
        (F1 · SLA badge 8-604), with each clock's use for the tooltip."""
        clocks = {c.kind: c for c in ticket.sla_clocks.all()}
        if not clocks:
            return None
        now = timezone.now()
        lines = []
        for kind in (ClockKind.RESPONSE.value, ClockKind.RESOLUTION.value):
            clock = clocks.get(kind)
            if clock is None:
                continue
            calendar = clock.calendar(holidays_of(clock.policy_snapshot["calendar"]["id"]))
            lines.append(
                BadgeLine(
                    kind=kind,
                    state=clock.state,
                    due_at=clock.due_at,
                    met_at=clock.met_at,
                    elapsed_minutes=clock.elapsed_at(now, calendar) // 60,
                    target_minutes=clock.target_minutes(),
                    warned=clock.warn_at is not None and clock.warn_at <= now,
                )
            )
        shown = next((line for line in lines if line.state in OPEN_CLOCK_STATES), lines[-1])
        if shown.state == ClockState.CANCELLED.value:
            return None
        snapshot = next(iter(clocks.values())).policy_snapshot
        return Badge(
            kind=shown.kind,
            level=shown.level(),
            remaining_minutes=shown.target_minutes - shown.elapsed_minutes,
            due_at=shown.due_at,
            policy=snapshot["policy"],
            calendar=snapshot["calendar"]["name"],
            clocks=lines,
        )

    def breaches(self, *, team: str | None, state: str | None) -> Any:
        """Open clocks that warned or breached, the latest due first (UC-F1-04)."""
        rows = (
            Clock.objects.open()
            .filter(Q(breached_at__isnull=False) | Q(warned_at__isnull=False))
            .select_related("ticket", "ticket__assigned_to")
        )
        if state == "breached":
            rows = rows.filter(breached_at__isnull=False)
        elif state == "warned":
            rows = rows.filter(breached_at__isnull=True)
        if team:
            rows = rows.filter(ticket__assigned_team=team)
        return rows.order_by("due_at")

    def preview(self, category: str | None, priority: Priority, start_at: datetime) -> Preview:
        """Due times a new clock would get, without creating one (FR-F1-014)."""
        policy = Policy.objects.matching(category, priority.value)
        if policy is None:
            raise SlaError(409, SlaRefusal.NO_POLICY, "no active SLA policy matches")
        calendar = self.calendar_for(policy, None)
        business = BusinessCalendar(
            ZoneInfo(calendar.timezone),
            parse_hours(calendar.working_hours),
            holidays_of(calendar.id),
            is_24x7=policy.is_24x7,
        )
        warn = settings.THRESHOLDS.sla.warn_at_percent / 100

        def due(minutes: int) -> Due:
            return Due(
                due_at=business.add(start_at, minutes * 60).astimezone(UTC),
                warn_at=business.add(start_at, warn * minutes * 60).astimezone(UTC),
            )

        return Preview(
            policy=policy.name,
            calendar=calendar.name,
            response=due(policy.response_minutes),
            resolution=due(policy.resolution_minutes),
        )

    # ── the yearly holiday reminder ──

    def holiday_check(self, now: datetime | None = None) -> int:
        """Tells workflow admins about calendars with no holidays for next year (BR-F1-14)."""
        now = now or timezone.now()
        month, day = (
            int(p) for p in settings.THRESHOLDS.sla.holidays_reminder_month_day.split("-")
        )
        sent = 0
        for calendar in Calendar.objects.all():
            today = now.astimezone(ZoneInfo(calendar.timezone)).date()
            if (today.month, today.day) < (month, day):
                continue
            year = today.year + 1
            if calendar.holidays.filter(date__year=year).exists():
                continue
            notifier.emit(
                NotificationEvent.SLA_HOLIDAYS_MISSING,
                None,
                Notice(
                    reason=str(year),
                    detail=f"{calendar.name} has no holidays for {year}",
                    link="/settings/sla/holidays",
                    data={"calendar": calendar.name, "year": year},
                ),
                event_id=uuid.uuid5(_SLA_NAMESPACE, f"holidays:{calendar.id}:{year}"),
            )
            sent += 1
        return sent


# --- the clock service ---

sla_clocks = SlaClocks()
