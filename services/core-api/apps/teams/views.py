"""Team endpoints: teams and members, the team queue and workload, and a person's availability and
leave (F2 §h). Take and reassign are on the ticket routes."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import Prefetch, QuerySet
from ninja import Router, Status
from ninja.pagination import LimitOffsetPagination, paginate

from apps.accounts.models import Capability, User, UserRole
from apps.accounts.permissions import STAFF, AuthedRequest, SessionAuth, require_access
from apps.teams.models import Leave, MembershipRole, Team, TeamMembership
from apps.teams.request_schema import AvailabilityIn, LeaveIn, MemberIn, TeamIn, TeamPatch
from apps.teams.response_schema import (
    LeaveOut,
    MemberOut,
    MembershipOut,
    MyAvailabilityOut,
    TeamDetailOut,
    TeamOut,
    WorkloadRowOut,
)
from apps.teams.utils.assignment import TeamError, assignment
from apps.teams.utils.config import team_config
from apps.teams.utils.people import WorkloadRow, people
from apps.teams.utils.vocabulary import TeamRefusal
from apps.tickets.models import Ticket
from apps.tickets.response_schema import StaffTicketRow

router = Router(tags=["teams"])
me_router = Router(tags=["teams"])

_MANAGER = (UserRole.MANAGER,)
_ADMIN = (Capability.WORKFLOW_ADMIN,)


def _teams() -> QuerySet[Team]:
    return Team.objects.prefetch_related(
        "categories", Prefetch("memberships", TeamMembership.objects.select_related("user"))
    ).order_by("name")


def _user(username: str) -> User:
    found = User.objects.filter(username=username).first()
    if found is None:
        raise TeamError(404, TeamRefusal.USER_NOT_IN_TEAM, f"no user {username!r}")
    return found


# ── teams ──


@router.get("", auth=SessionAuth(), response=list[TeamOut])
@require_access(roles=STAFF)
def teams(request: AuthedRequest) -> QuerySet[Team]:
    return _teams()


@router.post("", auth=SessionAuth(), response={201: TeamDetailOut})
@require_access(roles=_MANAGER, capabilities=_ADMIN)
def create_team(request: AuthedRequest, payload: TeamIn) -> Status:
    team_config.save(request.auth, payload.slug, payload.model_dump(mode="json"), create=True)
    return Status(201, _teams().get(slug=payload.slug))


@router.get("/{slug}", auth=SessionAuth(), response=TeamDetailOut)
@require_access(roles=STAFF)
def team(request: AuthedRequest, slug: str) -> Team:
    return _teams().get(pk=assignment.team(slug).pk)


@router.patch("/{slug}", auth=SessionAuth(), response=TeamDetailOut)
@require_access(roles=_MANAGER, capabilities=_ADMIN)
def update_team(request: AuthedRequest, slug: str, payload: TeamPatch) -> Team:
    team_config.save(request.auth, slug, payload.model_dump(mode="json"), create=False)
    return _teams().get(slug=slug)


@router.post("/{slug}/members", auth=SessionAuth(), response=MemberOut)
@require_access(roles=_MANAGER, capabilities=_ADMIN)
def add_member(request: AuthedRequest, slug: str, payload: MemberIn) -> TeamMembership:
    return team_config.add_member(
        request.auth, assignment.team(slug), _user(payload.username), MembershipRole(payload.role)
    )


@router.delete("/{slug}/members/{username}", auth=SessionAuth(), response={204: None})
@require_access(roles=_MANAGER, capabilities=_ADMIN)
def remove_member(request: AuthedRequest, slug: str, username: str) -> Status:
    team_config.remove_member(request.auth, assignment.team(slug), _user(username))
    return Status(204, None)


@router.put(
    "/{slug}/members/{username}/availability", auth=SessionAuth(), response=list[MembershipOut]
)
@require_access(roles=STAFF)
def set_member_availability(
    request: AuthedRequest, slug: str, username: str, payload: AvailabilityIn
) -> list[TeamMembership]:
    return people.set_availability(
        request.auth, payload.is_available, user=_user(username), team=assignment.team(slug)
    )


# ── the team views ──


@router.get("/{slug}/queue", auth=SessionAuth(), response=list[StaffTicketRow])
@paginate(LimitOffsetPagination)
@require_access(roles=STAFF)
def queue(request: AuthedRequest, slug: str, unassigned: bool = False) -> QuerySet[Ticket]:
    return people.queue(
        assignment.team(slug), request.auth, unassigned=unassigned
    ).prefetch_related("review_items")


@router.get("/{slug}/workload", auth=SessionAuth(), response=list[WorkloadRowOut])
@require_access(roles=STAFF)
def workload(request: AuthedRequest, slug: str) -> list[WorkloadRow]:
    return people.workload(assignment.team(slug), request.auth)


# ── my availability and leave ──


def _mine(user: User) -> dict[str, Any]:
    return {
        "memberships": list(TeamMembership.objects.filter(user=user).select_related("team")),
        "leaves": list(Leave.objects.filter(user=user).select_related("user")),
    }


@me_router.get("/availability", auth=SessionAuth(), response=MyAvailabilityOut)
@require_access(roles=STAFF)
def my_availability(request: AuthedRequest) -> dict[str, Any]:
    return _mine(request.auth)


@me_router.put("/availability", auth=SessionAuth(), response=MyAvailabilityOut)
@require_access(roles=STAFF)
def set_my_availability(request: AuthedRequest, payload: AvailabilityIn) -> dict[str, Any]:
    people.set_availability(request.auth, payload.is_available)
    return _mine(request.auth)


@me_router.post("/leaves", auth=SessionAuth(), response={201: LeaveOut})
@require_access(roles=STAFF)
def add_leave(request: AuthedRequest, payload: LeaveIn) -> Status:
    user = _user(payload.user) if payload.user else None
    leave = people.add_leave(
        request.auth, payload.starts_on, payload.ends_on, payload.note, user=user
    )
    return Status(201, leave)


@me_router.delete("/leaves/{leave_id}", auth=SessionAuth(), response={204: None})
@require_access(roles=STAFF)
def remove_leave(request: AuthedRequest, leave_id: uuid.UUID) -> Status:
    people.remove_leave(request.auth, leave_id)
    return Status(204, None)
