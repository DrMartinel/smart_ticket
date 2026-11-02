"""Who is around and how loaded: availability, leave, the team queue and the workload view (F2)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Case, F, Min, QuerySet, Value, When

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.teams.models import Leave, MembershipRole, Team, TeamMembership
from apps.teams.utils.assignment import TeamError, today
from apps.teams.utils.vocabulary import TeamRefusal

if TYPE_CHECKING:
    from apps.tickets.models import Ticket


@dataclass(frozen=True)
class WorkloadRow:
    """One member's load (UC-F2-04); `flagged` marks open work held by someone away (BR-F2-07)."""

    user: str
    role: str
    available: bool
    on_leave: bool
    open: int
    cap: int | None
    oldest_due: datetime | None
    last_assigned_at: datetime | None
    next_pick: bool
    flagged: bool


class People:
    """Availability, leave and the team views, each scoped to who asks (BR-F2-04)."""

    # ── availability and leave ──

    def set_availability(
        self, actor: User, is_available: bool, *, user: User | None = None, team: Team | None = None
    ) -> list[TeamMembership]:
        """Sets availability on every team of `user` (default: the actor), or one team as its lead.
        Tickets already assigned stay where they are (BR-F2-07)."""
        user = user or actor
        if user != actor:
            self.check_lead_of(actor, user, team)
        with transaction.atomic():
            rows = TeamMembership.objects.filter(user=user)
            if team is not None:
                rows = rows.filter(team=team)
            changed = rows.exclude(is_available=is_available).update(is_available=is_available)
            AuditLog.objects.record(
                "availability_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "user": user.username,
                    "is_available": is_available,
                    "team": team.slug if team else None,
                    "memberships": changed,
                },
            )
        return list(TeamMembership.objects.filter(user=user).select_related("team"))

    def add_leave(
        self, actor: User, starts_on: date, ends_on: date, note: str, *, user: User | None = None
    ) -> Leave:
        """Records whole days away; a lead may add them for a member of their team."""
        from apps.tickets.utils.masking import mask_regex_tier

        user = user or actor
        if user != actor:
            self.check_lead_of(actor, user, None)
        if ends_on < starts_on:
            raise TeamError(422, TeamRefusal.BAD_DATES, "the leave ends before it starts")
        masked, _ = mask_regex_tier(note.strip())
        with transaction.atomic():
            leave = Leave.objects.create(
                user=user, starts_on=starts_on, ends_on=ends_on, note=masked, created_by=actor
            )
            self.audit_leave("added", actor, leave)
        return leave

    def remove_leave(self, actor: User, leave_id: uuid.UUID) -> None:
        leave = Leave.objects.select_related("user").filter(pk=leave_id).first()
        if leave is None:
            raise TeamError(404, TeamRefusal.LEAVE_NOT_FOUND, "no such leave")
        if leave.user != actor:
            self.check_lead_of(actor, leave.user, None)
        with transaction.atomic():
            self.audit_leave("removed", actor, leave)
            leave.delete()

    def audit_leave(self, change: str, actor: User, leave: Leave) -> None:
        AuditLog.objects.record(
            "leave_changed",
            actor_type="human",
            actor_id=actor.id,
            payload={
                "change": change,
                "user": leave.user.username,
                "starts_on": leave.starts_on.isoformat(),
                "ends_on": leave.ends_on.isoformat(),
            },
        )

    def check_lead_of(self, actor: User, user: User, team: Team | None) -> None:
        """A manager edits anyone; a lead edits members of a team they lead."""
        if actor.role == UserRole.MANAGER.value:
            return
        led = TeamMembership.objects.filter(user=actor, role=MembershipRole.LEAD.value)
        if team is not None:
            led = led.filter(team=team)
        if not TeamMembership.objects.filter(user=user, team__in=led.values("team")).exists():
            raise TeamError(
                403, TeamRefusal.LEAD_REQUIRED, "only their team lead or a manager can change that"
            )

    # ── the team views ──

    def queue(self, team: Team, actor: User, *, unassigned: bool) -> QuerySet[Ticket]:
        """The team's open tickets: unowned first, then the earliest due (FR-F2-012)."""
        from apps.tickets.models import Ticket

        self.check_member_or_manager(actor, team)
        rows = (
            Ticket.objects.filter(team=team, resolved_at__isnull=True)
            .exclude(workflow_status__base__is_completed=True)
            .select_related("reporter", "assigned_to", "workflow_status__base", "team")
        )
        if unassigned:
            rows = rows.filter(assigned_to__isnull=True)
        owned = Case(When(assigned_to__isnull=True, then=Value(0)), default=Value(1))
        return rows.annotate(owned=owned).order_by(
            "owned", F("sla_due_at").asc(nulls_last=True), "created_at"
        )

    def workload(self, team: Team, actor: User) -> list[WorkloadRow]:
        """Each member's load; a member who isn't the lead sees their own row only (UC-F2-04)."""
        from apps.tickets.models import Ticket

        self.check_member_or_manager(actor, team)
        rows = (
            TeamMembership.objects.with_load(today(team))
            .filter(team=team)
            .order_by("user__username")
        )
        if actor.role != UserRole.MANAGER.value and not team.is_lead(actor):
            rows = rows.filter(user=actor)
        due = dict(
            Ticket.objects.filter(
                assigned_to__in=[m.user_id for m in rows], resolved_at__isnull=True
            )
            .exclude(workflow_status__base__is_completed=True)
            .values("assigned_to")
            .annotate(oldest=Min("sla_due_at"))
            .values_list("assigned_to", "oldest")
        )
        nxt = (
            TeamMembership.objects.eligible(team, today(team))
            .values_list("user_id", flat=True)
            .first()
        )
        return [
            WorkloadRow(
                user=m.user.username,
                role=m.role,
                available=m.is_available and m.user.is_active,
                on_leave=m.on_leave,
                open=m.open_count,
                cap=team.max_open_per_member,
                oldest_due=due.get(m.user_id),
                last_assigned_at=m.last_assigned_at,
                next_pick=m.user_id == nxt,
                flagged=m.open_count > 0 and (not m.is_available or m.on_leave),
            )
            for m in rows
        ]

    def check_member_or_manager(self, actor: User, team: Team) -> None:
        if actor.role == UserRole.MANAGER.value or team.membership_of(actor) is not None:
            return
        raise TeamError(403, TeamRefusal.NOT_A_MEMBER, f"you're not in team {team.slug}")


# --- the people service ---

people = People()
