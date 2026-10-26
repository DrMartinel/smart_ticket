"""Response shapes of the team, assignment and availability endpoints (F2)."""

from __future__ import annotations

import datetime
import uuid

from ninja import Schema

from apps.teams.models import Leave, Reassignment, Team, TeamMembership
from apps.tickets.models import Ticket


class TeamOut(Schema):
    slug: str
    name: str
    categories: list[str]
    strategy: str
    max_open_per_member: int | None
    keycloak_group: str | None
    is_fallback: bool
    is_active: bool
    members_count: int
    leads: list[str]

    @staticmethod
    def resolve_categories(team: Team) -> list[str]:
        return sorted(c.category for c in team.categories.all())

    @staticmethod
    def resolve_members_count(team: Team) -> int:
        return len(team.memberships.all())

    @staticmethod
    def resolve_leads(team: Team) -> list[str]:
        return sorted(m.user.username for m in team.memberships.all() if m.role == "lead")


class MemberOut(Schema):
    username: str
    role: str
    is_available: bool
    source: str

    @staticmethod
    def resolve_username(member: TeamMembership) -> str:
        return member.user.username


class TeamDetailOut(TeamOut):
    members: list[MemberOut]

    @staticmethod
    def resolve_members(team: Team) -> list[TeamMembership]:
        return sorted(team.memberships.all(), key=lambda m: (m.role != "lead", m.user.username))


class WorkloadRowOut(Schema):
    user: str
    role: str
    available: bool
    on_leave: bool
    open: int
    cap: int | None
    oldest_due: datetime.datetime | None
    last_assigned_at: datetime.datetime | None
    next_pick: bool
    flagged: bool


class ReassignmentOut(Schema):
    reason_code: str
    note_masked: str
    actor: str
    created_at: datetime.datetime

    @staticmethod
    def resolve_actor(row: Reassignment) -> str:
        return row.actor.username


class AssignedTicketOut(Schema):
    public_id: str
    team: str | None
    assigned_to: str | None
    category: str | None
    version: int
    last_reassignment: ReassignmentOut | None

    @staticmethod
    def resolve_team(ticket: Ticket) -> str | None:
        return ticket.team.slug if ticket.team else None

    @staticmethod
    def resolve_assigned_to(ticket: Ticket) -> str | None:
        return ticket.assigned_to.username if ticket.assigned_to else None

    @staticmethod
    def resolve_last_reassignment(ticket: Ticket) -> Reassignment | None:
        return ticket.reassignments.select_related("actor").first()


class MembershipOut(Schema):
    team: str
    team_name: str
    role: str
    is_available: bool

    @staticmethod
    def resolve_team(member: TeamMembership) -> str:
        return member.team.slug

    @staticmethod
    def resolve_team_name(member: TeamMembership) -> str:
        return member.team.name


class LeaveOut(Schema):
    id: uuid.UUID
    user: str
    starts_on: datetime.date
    ends_on: datetime.date
    note: str

    @staticmethod
    def resolve_user(leave: Leave) -> str:
        return leave.user.username


class MyAvailabilityOut(Schema):
    memberships: list[MembershipOut]
    leaves: list[LeaveOut]
