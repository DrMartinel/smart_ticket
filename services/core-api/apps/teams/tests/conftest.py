"""The F2 Background: team "network" (least_loaded) with duc.tm (lead, 6 open), khoa.lv (4 open),
nam.pt (2 open, on leave today) and vy.tt (unavailable, 3 open); plus a reviewer and a manager."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from apps.accounts.models import User, UserRole
from apps.lifecycle.tests.conftest import make_ticket
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.teams.models import Leave, MembershipRole, Team, TeamMembership
from apps.teams.utils.assignment import today
from apps.tickets.models import Ticket

_numbers = itertools.count(1)


def person(username: str, role: UserRole = UserRole.TECHNICIAN) -> User:
    return User.objects.create_user(
        username=username, password="x", role=role.value, email=f"{username}@example.test"
    )


def open_tickets(user: User, count: int, reporter: User) -> None:
    for _ in range(count):
        Ticket.objects.create(
            public_id=f"TKT-OPEN-{next(_numbers):06d}",
            reporter=reporter,
            subject_masked="earlier work",
            body_masked="earlier work",
            pii_level="routine",
            assigned_to=user,
        )


@dataclass
class Network:
    team: Team
    people: dict[str, User]


@pytest.fixture
def network(db) -> Network:
    team = Team.objects.get(slug="network")
    people = {
        "duc": person("duc.tm"),
        "khoa": person("khoa.lv"),
        "nam": person("nam.pt"),
        "vy": person("vy.tt"),
        "ha": person("ha.vt"),
        "huy": person("huy.pq", UserRole.MANAGER),
        "lan": person("lan.nt", UserRole.EMPLOYEE),
        "anh": person("anh.lh", UserRole.SECURITY),
    }
    roles = {"duc": MembershipRole.LEAD, "khoa": None, "nam": None, "vy": None}
    for key, role in roles.items():
        TeamMembership.objects.create(
            team=team,
            user=people[key],
            role=(role or MembershipRole.MEMBER).value,
            is_available=key != "vy",
            source="local",
        )
    access = Team.objects.get(slug="access")
    TeamMembership.objects.create(
        team=access, user=people["ha"], role=MembershipRole.LEAD.value, source="local"
    )
    for key, count in (("duc", 6), ("khoa", 4), ("nam", 2), ("vy", 3)):
        open_tickets(people[key], count, people["lan"])
    Leave.objects.create(
        user=people["nam"],
        starts_on=today(),
        ends_on=today() + timedelta(days=1),
        created_by=people["nam"],
    )
    return Network(team, people)


def handed_off(reporter: User, **fields: Any) -> Ticket:
    """A ticket the pipeline has put at `pending_review`, with `fields` set."""
    ticket = make_ticket(reporter, at=PipelineStatus.PENDING_REVIEW)
    if fields:
        for name, value in fields.items():
            setattr(ticket, name, value)
        ticket.save(update_fields=list(fields))
    return ticket
