"""Builds `report_ticket_facts` (F10 FR-F10-001): one row per ticket, upserted for tickets that
changed since the last build."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.reports.models import FactState, TicketFacts
from apps.review.models import ReviewDecision
from apps.sla.models import Calendar, Clock, ClockKind, ClockState
from apps.sla.utils.clocks import holidays_of
from apps.tickets.models import Ticket


def report_zone() -> ZoneInfo:
    """The zone report days and months are counted in: the default business calendar's."""
    calendar = Calendar.objects.filter(is_default=True).first()
    return ZoneInfo(calendar.timezone if calendar else "UTC")


def clock_state(clock: Clock | None) -> FactState:
    """A clock as a report reads it; a met clock that breached first counts as breached."""
    if clock is None or clock.state == ClockState.CANCELLED.value:
        return FactState.NONE
    if clock.state == ClockState.MET.value:
        return FactState.BREACHED if clock.breached_at else FactState.MET
    if clock.state == ClockState.BREACHED.value:
        return FactState.BREACHED
    if clock.state == ClockState.PAUSED.value:
        return FactState.PAUSED
    return FactState.RUNNING


def warned_in_time(clock: Clock | None) -> bool | None:
    """For a breached clock, whether its warning came before the breach (K3)."""
    if clock is None or clock.breached_at is None:
        return None
    return clock.warned_at is not None and clock.warned_at <= clock.breached_at


class ReportFacts:
    """The nightly facts build."""

    def changed_since(self, since: datetime | None) -> list[Any]:
        """Tickets with no facts row, or with a status move, clock, rating, reassignment, review
        decision, routing decision or incident link newer than `since`."""
        missing = Ticket.objects.filter(facts__isnull=True).values_list("id", flat=True)
        ids = set(missing)
        if since is None:
            return list(Ticket.objects.values_list("id", flat=True))
        ids |= set(
            Ticket.objects.filter(
                Q(transfers__created_at__gt=since)
                | Q(sla_clocks__elapsed_as_of__gt=since)
                | Q(ratings__updated_at__gt=since)
                | Q(reassignments__created_at__gt=since)
                | Q(review_items__decisions__decided_at__gt=since)
                | Q(routing_decisions__decided_at__gt=since)
                | Q(incident_links__linked_at__gt=since)
                | Q(incident_links__unlinked_at__gt=since)
            )
            .distinct()
            .values_list("id", flat=True)
        )
        return list(ids)

    def build(self, *, full: bool = False) -> int:
        """Upserts the facts of every ticket changed since the last build; returns how many."""
        last = None if full else TicketFacts.objects.aggregate(at=Max("built_at"))["at"]
        now = timezone.now()
        zone = report_zone()
        ids = self.changed_since(last)
        for ticket in Ticket.objects.filter(id__in=ids).select_related("team"):
            with transaction.atomic():
                TicketFacts.objects.update_or_create(
                    ticket=ticket, defaults=self.facts_of(ticket, zone, now)
                )
        AuditLog.objects.record(
            "report_facts_built", actor_type="system", payload={"tickets": len(ids)}
        )
        return len(ids)

    def latest_clocks(self, ticket: Ticket) -> dict[str, Clock]:
        clocks: dict[str, Clock] = {}
        for clock in Clock.objects.filter(ticket=ticket).order_by("started_at"):
            clocks[clock.kind] = clock
        return clocks

    def first_assigned_at(self, ticket: Ticket) -> datetime | None:
        row = (
            AuditLog.objects.filter(
                ticket_id=ticket.id,
                event__in=("ticket_assigned", "ticket_reassigned"),
                payload__assignee__isnull=False,
            )
            .exclude(payload__assignee=None)
            .order_by("occurred_at")
            .first()
        )
        return row.occurred_at if row else None

    def business_minutes(self, clock: Clock, start: datetime, end: datetime) -> float:
        snapshot: dict[str, Any] = clock.policy_snapshot
        calendar_id = snapshot.get("calendar", {}).get("id")
        calendar = clock.calendar(holidays_of(calendar_id) if calendar_id else frozenset())
        return calendar.elapsed(start, end) / 60

    def facts_of(self, ticket: Ticket, zone: ZoneInfo, now: datetime) -> dict[str, Any]:
        clocks = self.latest_clocks(ticket)
        response = clocks.get(ClockKind.RESPONSE.value)
        resolution = clocks.get(ClockKind.RESOLUTION.value)
        started = response or resolution
        handed_off_at = started.started_at if started else None
        first_assigned_at = self.first_assigned_at(ticket)
        time_to_assign = (
            self.business_minutes(started, handed_off_at, first_assigned_at)
            if started and handed_off_at and first_assigned_at and first_assigned_at > handed_off_at
            else None
        )
        reassignments = list(ticket.reassignments.values_list("from_team_id", "to_team_id"))
        rating = ticket.ratings.order_by("-resolution_seq").first()
        shadow = ticket.routing_decisions.filter(shadow_mode=True).order_by("-decided_at").first()
        decision = (
            ReviewDecision.objects.filter(review_item__ticket=ticket)
            .order_by("-decided_at")
            .first()
        )
        corrected = decision.corrected_category if decision else None
        return {
            "created_day": ticket.created_at.astimezone(zone).date(),
            "team": ticket.team.slug if ticket.team else ticket.assigned_team,
            "category": ticket.category,
            "priority": ticket.priority,
            "source": ticket.source or "",
            "handed_off_at": handed_off_at,
            "first_assigned_at": first_assigned_at,
            "first_response_at": response.met_at if response else None,
            "resolved_at": ticket.resolved_at,
            "time_to_assign_business_min": time_to_assign,
            "response_state": clock_state(response).value,
            "resolution_state": clock_state(resolution).value,
            "response_met_at": response.met_at if response else None,
            "resolution_met_at": resolution.met_at if resolution else None,
            "response_warned_in_time": warned_in_time(response),
            "resolution_warned_in_time": warned_in_time(resolution),
            "reassign_count": len(reassignments),
            "cross_team_reassign_count": sum(1 for a, b in reassignments if a != b),
            "auto_replied": ticket.routing_decisions.filter(
                branch="auto_reply", shadow_mode=False
            ).exists(),
            "reopened": ticket.reopened_count > 0,
            "linked_incident": ticket.incident_links.filter(unlinked_at__isnull=True).exists(),
            "csat_score": rating.score if rating else None,
            "csat_seq": rating.resolution_seq if rating else None,
            "csat_at": rating.updated_at if rating else None,
            "shadow_branch": shadow.branch if shadow else None,
            "review_action": decision.action_taken if decision else None,
            "category_corrected": bool(corrected) and corrected != ticket.category,
            "built_at": now,
        }


# --- the facts builder ---

report_facts = ReportFacts()
