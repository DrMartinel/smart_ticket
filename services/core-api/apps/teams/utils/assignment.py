"""Who owns a ticket: the team for its category and a person by the team's strategy, at handoff, on
take and on reassignment (F2). Never changes a routing decision (BR-F2-02)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.teams.models import Reassignment, Team, TeamMembership
from apps.teams.utils.vocabulary import (
    AssignmentFailure,
    AssignmentTrigger,
    ReassignReason,
    TeamRefusal,
)
from infrastructure.dtos import TicketCategory

if TYPE_CHECKING:
    from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


class TeamError(CodedError):
    """A team or assignment request core-api refuses (BR-X-08)."""


@dataclass(frozen=True)
class Pick:
    """Who the strategy chose, if anyone, and from how many eligible members."""

    member: TeamMembership | None
    candidates: int


@dataclass(frozen=True)
class ReassignRequest:
    """A person's reassignment: a target person or team, a reason code and a note."""

    to_user: str | None
    to_team: str | None
    to_category: str | None
    reason_code: ReassignReason
    note: str
    expected_version: int


def today(team: Team | None = None) -> date:
    """Today in the zone of the team's calendar, else the default calendar's: the day leave is
    judged by (BR-F2-03, BR-F1-04)."""
    from apps.sla.models import Calendar

    calendar = (
        team.calendar
        if team is not None and team.calendar_id is not None
        else Calendar.objects.filter(is_default=True).first()
    )
    zone = ZoneInfo(calendar.timezone if calendar else "UTC")
    return timezone.now().astimezone(zone).date()


class Assignment:
    """Every change of a ticket's team and assignee, serialized per team (BR-F2-08)."""

    # ── at handoff ──

    def assign_after_handoff(
        self,
        ticket: Ticket,
        trigger: AssignmentTrigger,
        *,
        category: str | None = None,
        actor: User | None = None,
    ) -> None:
        """Gives a handed-off ticket a team and, when someone is eligible, a person; a failure is
        audited and leaves the ticket's status and decision as they are (BR-X-07)."""
        try:
            with transaction.atomic():
                self.hand_to_team(ticket, trigger, category or ticket.category, actor)
        except Exception as e:  # noqa: BLE001 — assignment never undoes the decision it follows
            logger.exception("assignment of %s failed", ticket.public_id)
            ticket.refresh_from_db(fields=["team", "assigned_team", "assigned_to", "version"])
            self.record_failure(ticket, AssignmentFailure.ERROR, {"error": type(e).__name__})

    def hand_to_team(
        self,
        ticket: Ticket,
        trigger: AssignmentTrigger,
        category: str | None,
        actor: User | None,
    ) -> None:
        team = Team.objects.owning(category) if category else None
        if (
            trigger is AssignmentTrigger.REOPEN
            and ticket.team is not None
            and ticket.team.is_active
        ):
            team = ticket.team
        failure = None
        if team is None:
            failure = (
                AssignmentFailure.NO_TEAM_FOR_CATEGORY
                if category
                else AssignmentFailure.NO_CATEGORY
            )
            team = Team.objects.fallback()
        if team is None:
            self.record_failure(
                ticket, AssignmentFailure.NO_FALLBACK_TEAM, {"category": category, "fallback": None}
            )
            return
        self.lock(team)
        member = self.inherited(ticket, team, trigger)
        if member is not None:
            pick = Pick(member, 1)
            strategy = (
                "previous_assignee" if trigger is AssignmentTrigger.REOPEN else "duplicate_of"
            )
        else:
            pick = self.pick(team)
            strategy = team.strategy
        self.place(
            ticket,
            team,
            pick.member,
            actor=actor,
            event="ticket_assigned",
            payload={"strategy": strategy, "trigger": trigger.value, "candidates": pick.candidates},
        )
        if failure is not None:
            self.record_failure(ticket, failure, {"category": category, "fallback": team.slug})

    def record_failure(
        self, ticket: Ticket, failure: AssignmentFailure, detail: dict[str, Any]
    ) -> None:
        """Audits `assignment_failed` and tells the fallback team's lead (UC-F2-01 2x)."""
        AuditLog.objects.record(
            "assignment_failed",
            actor_type="system",
            ticket_id=ticket.id,
            payload={"ticket_public_id": ticket.public_id, "reason": failure.value, **detail},
        )
        fallback = Team.objects.fallback()
        notifier.emit(
            NotificationEvent.ASSIGNMENT_FAILED,
            ticket,
            Notice(
                reason=failure.value,
                detail=f"category {detail.get('category') or 'none'}",
                team=fallback.slug if fallback else None,
                data={"reason": failure.value, **detail},
            ),
        )

    def inherited(
        self, ticket: Ticket, team: Team, trigger: AssignmentTrigger
    ) -> TeamMembership | None:
        """A reopened ticket's last assignee, or a duplicate's original assignee, when they are
        eligible in `team` now (UC-F3-04 step 4, UC-F2-01 3a)."""
        if trigger is AssignmentTrigger.REOPEN:
            holder_id = ticket.assigned_to_id
        else:
            original = ticket.duplicate_of
            holder_id = original.assigned_to_id if original is not None else None
        if holder_id is None:
            return None
        return TeamMembership.objects.eligible(team, today(team)).filter(user_id=holder_id).first()

    def pick(self, team: Team) -> Pick:
        """The member the team's strategy chooses now, under the team's lock (BR-F2-03)."""
        eligible = list(TeamMembership.objects.eligible(team, today(team)))
        return Pick(eligible[0] if eligible else None, len(eligible))

    def lock(self, team: Team) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"assign:{team.id}"])

    def place(
        self,
        ticket: Ticket,
        team: Team,
        member: TeamMembership | None,
        *,
        actor: User | None,
        event: str,
        payload: dict[str, Any],
        notice: Notice | None = None,
    ) -> None:
        """Writes the team and assignee, audits `event`, and tells the people concerned."""
        previous = ticket.assigned_to
        person = member.user if member else None
        ticket.team = team
        ticket.assigned_team = team.slug
        ticket.assigned_to = person
        ticket.version = F("version") + 1
        ticket.save(update_fields=["team", "assigned_team", "assigned_to", "version"])
        ticket.refresh_from_db(fields=["version"])
        if member is not None:
            TeamMembership.objects.filter(pk=member.pk).update(last_assigned_at=timezone.now())
        AuditLog.objects.record(
            event,
            actor_type="human" if actor else "system",
            actor_id=actor.id if actor else None,
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "team": team.slug,
                "assignee": person.username if person else None,
                "previous": previous.username if previous else None,
                **payload,
            },
        )
        by = actor.username if actor else "system"
        if person is not None:
            notifier.assignment_changed(ticket, previous, by, notice)
        else:
            notifier.left_in_queue(ticket, previous, by)

    def move_to_team(self, ticket: Ticket, team: Team, *, pick_member: bool) -> None:
        """A workflow action's team change: the team, and a person by its strategy when asked;
        otherwise the assignee stays (FR-F2-014)."""
        self.lock(team)
        if pick_member:
            pick = self.pick(team)
            self.place(
                ticket,
                team,
                pick.member,
                actor=None,
                event="ticket_assigned",
                payload={
                    "strategy": team.strategy,
                    "trigger": AssignmentTrigger.ACTION.value,
                    "candidates": pick.candidates,
                },
            )
            return
        ticket.team = team
        ticket.assigned_team = team.slug
        ticket.save(update_fields=["team", "assigned_team"])
        AuditLog.objects.record(
            "ticket_assigned",
            actor_type="system",
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "team": team.slug,
                "trigger": AssignmentTrigger.ACTION.value,
            },
        )

    # ── people ──

    def take(self, public_id: str, actor: User, expected_version: int) -> Ticket:
        """Gives an unowned ticket of the actor's team to the actor (UC-F2-02)."""
        from apps.tickets.models import Ticket

        with transaction.atomic():
            ticket = self.locked(Ticket, public_id)
            team = ticket.team
            if team is None or not (
                actor.role == UserRole.MANAGER.value or team.membership_of(actor) is not None
            ):
                raise TeamError(403, TeamRefusal.NOT_A_MEMBER, "you're not in this ticket's team")
            self.check_category_scope(actor, ticket)
            if ticket.version != expected_version or self.is_owned(ticket, team):
                raise TeamError(
                    409, TeamRefusal.ALREADY_ASSIGNED, "someone took this ticket a moment ago"
                )
            self.lock(team)
            member = team.membership_of(actor)
            if member is None:
                self.place_person(ticket, team, actor)
            else:
                self.place(
                    ticket,
                    team,
                    member,
                    actor=actor,
                    event="ticket_assigned",
                    payload={"trigger": AssignmentTrigger.TAKE.value},
                )
        return ticket

    def place_person(self, ticket: Ticket, team: Team, actor: User) -> None:
        """A manager outside the team takes the ticket: no membership to stamp."""
        previous = ticket.assigned_to
        ticket.assigned_to = actor
        ticket.version = F("version") + 1
        ticket.save(update_fields=["assigned_to", "version"])
        ticket.refresh_from_db(fields=["version"])
        AuditLog.objects.record(
            "ticket_assigned",
            actor_type="human",
            actor_id=actor.id,
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "team": team.slug,
                "assignee": actor.username,
                "previous": previous.username if previous else None,
                "trigger": AssignmentTrigger.TAKE.value,
            },
        )
        notifier.assignment_changed(ticket, previous, actor.username)

    def is_owned(self, ticket: Ticket, team: Team) -> bool:
        """Whether the ticket has an assignee who can work it now; else anyone in the team may take it."""
        if ticket.assigned_to_id is None:
            return False
        holder = (
            TeamMembership.objects.with_load(today(team))
            .filter(team=team, user_id=ticket.assigned_to_id)
            .first()
        )
        if holder is None:
            return ticket.assigned_to is not None and ticket.assigned_to.is_active
        return holder.user.is_active and holder.is_available and not holder.on_leave

    def reassign(self, public_id: str, actor: User, request: ReassignRequest) -> Ticket:
        """Moves a ticket to another person or team with a reason, audited (UC-F2-03)."""
        from apps.review.models import EvalCandidate
        from apps.tickets.models import Ticket
        from apps.tickets.utils.masking import mask_regex_tier

        note = request.note.strip()
        if len(note) < settings.THRESHOLDS.assignment.reassign_note_min_chars:
            raise TeamError(
                422,
                TeamRefusal.REASON_REQUIRED,
                "a reassignment needs a reason code and a note of at least "
                f"{settings.THRESHOLDS.assignment.reassign_note_min_chars} characters",
            )
        with transaction.atomic():
            ticket = self.locked(Ticket, public_id)
            if ticket.version != request.expected_version:
                raise TeamError(
                    409, TeamRefusal.VERSION_CONFLICT, "the ticket changed; reload and try again"
                )
            current = ticket.team
            target = self.team(request.to_team) if request.to_team else current
            if target is None:
                raise TeamError(404, TeamRefusal.TEAM_NOT_FOUND, "the ticket has no team yet")
            self.check_reassigner(actor, ticket, current, target)
            category = self.category_for(ticket, current, target, request.to_category)
            self.lock(target)
            if request.to_user:
                member = (
                    TeamMembership.objects.select_related("user")
                    .filter(team=target, user__username=request.to_user, user__is_active=True)
                    .first()
                )
                if member is None:
                    raise TeamError(
                        422,
                        TeamRefusal.USER_NOT_IN_TEAM,
                        f"{request.to_user} is not an active member of {target.slug}",
                    )
            else:
                member = self.pick(target).member
            masked, _ = mask_regex_tier(note)
            before_category = ticket.category
            Reassignment.objects.create(
                ticket=ticket,
                from_user=ticket.assigned_to,
                to_user=member.user if member else None,
                from_team=current,
                to_team=target,
                from_category=before_category,
                to_category=category,
                reason_code=request.reason_code.value,
                note_masked=masked,
                actor=actor,
            )
            if category != before_category:
                ticket.category = category
                ticket.save(update_fields=["category"])
                EvalCandidate.objects.create(
                    ticket=ticket,
                    source="reroute",
                    ai_prediction={"category": before_category},
                    human_truth={"category": category, "reason_code": request.reason_code.value},
                )
            self.place(
                ticket,
                target,
                member,
                actor=actor,
                event="ticket_reassigned",
                payload={
                    "from_team": current.slug if current else None,
                    "from_category": before_category,
                    "to_category": category,
                    "reason_code": request.reason_code.value,
                    "note_masked": masked,
                },
                notice=Notice(reason=request.reason_code.value, detail=masked),
            )
        return ticket

    def check_reassigner(
        self, actor: User, ticket: Ticket, current: Team | None, target: Team
    ) -> None:
        """BR-F2-04: the assignee within the team, the lead in and out of it, a manager anywhere."""
        if actor.role == UserRole.MANAGER.value:
            return
        self.check_category_scope(actor, ticket)
        is_lead = current is not None and current.is_lead(actor)
        if not is_lead and ticket.assigned_to_id != actor.id:
            raise TeamError(
                403, TeamRefusal.LEAD_REQUIRED, "only the assignee, the team lead or a manager"
            )
        if target != current and not is_lead:
            raise TeamError(
                403, TeamRefusal.LEAD_REQUIRED, "only the team lead moves a ticket to another team"
            )

    def check_category_scope(self, actor: User, ticket: Ticket) -> None:
        """Security staff act only on security tickets (BR-F2-04)."""
        if actor.role == UserRole.SECURITY.value and ticket.category != TicketCategory.SECURITY:
            raise TeamError(403, TeamRefusal.NOT_ALLOWED, "security works security tickets only")

    def category_for(
        self, ticket: Ticket, current: Team | None, target: Team, asked: str | None
    ) -> str | None:
        """The category after a move: kept when the target owns it, else the one it owns or names."""
        if target == current:
            return ticket.category
        owned = list(target.categories.values_list("category", flat=True))
        if ticket.category in owned and asked in (None, ticket.category):
            return ticket.category
        if asked is not None and asked in owned:
            return asked
        if asked is None and len(owned) == 1:
            return owned[0]
        raise TeamError(
            422,
            TeamRefusal.CATEGORY_REQUIRED,
            f"say which of {target.slug}'s categories the ticket moves to",
            {"categories": owned},
        )

    def team(self, slug: str) -> Team:
        found = Team.objects.filter(slug=slug, is_active=True).first()
        if found is None:
            raise TeamError(404, TeamRefusal.TEAM_NOT_FOUND, f"no active team {slug!r}")
        return found

    def locked(self, model: Any, public_id: str) -> Ticket:
        ticket = (
            model.objects.select_for_update(of=("self",))
            .select_related("team", "assigned_to", "workflow_status__base")
            .filter(public_id=public_id)
            .first()
        )
        if ticket is None:
            raise TeamError(404, TeamRefusal.TICKET_NOT_FOUND, "ticket not found")
        status = ticket.workflow_status
        if ticket.resolved_at is not None or (status is not None and status.base.is_completed):
            raise TeamError(409, TeamRefusal.TICKET_COMPLETED, "the ticket is already resolved")
        return ticket


# --- the assignment service ---

assignment = Assignment()
