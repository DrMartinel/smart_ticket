"""People, tickets and fakes for the notification tests: a recording queue, a recording webhook host,
and email relays that refuse."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from typing import Any

import pytest
from django.core.mail.backends.base import BaseEmailBackend

from apps.accounts.models import Capability, User, UserCapability, UserRole
from apps.notifications import tasks
from apps.teams.models import MembershipRole, Team, TeamMembership
from apps.teams.utils.assignment import ReassignRequest, assignment
from apps.teams.utils.vocabulary import ReassignReason
from apps.tickets.models import Ticket
from apps.tickets.utils.patterns import PIILevel
from infrastructure.outbound import OutboundHttp, OutboundResponse


def person(username: str, role: UserRole, **extra: Any) -> User:
    return User.objects.create_user(
        username=username,
        password="x",
        role=role.value,
        email=f"{username}@example.test",
        **extra,
    )


@pytest.fixture
def people(db) -> dict[str, User]:
    tu = person("tu.dv", UserRole.TECHNICIAN)
    UserCapability.objects.create(user=tu, capability=Capability.WORKFLOW_ADMIN.value)
    return {
        "lan": person("lan.nt", UserRole.EMPLOYEE),
        "duc": person("duc.tm", UserRole.TECHNICIAN),
        "ha": person("ha.vt", UserRole.TECHNICIAN),
        "mai": person("mai.bn", UserRole.TECHNICIAN, language="en"),
        "huy": person("huy.pq", UserRole.MANAGER),
        "anh": person("anh.lh", UserRole.SECURITY),
        "tu": tu,
    }


@pytest.fixture
def ticket(people) -> Ticket:
    """TKT-2026-000412, its body masked, in team "network", where the technicians are members
    and huy.pq leads."""
    network = Team.objects.get(slug="network")
    for key in ("duc", "ha", "mai", "tu"):
        TeamMembership.objects.create(team=network, user=people[key], source="local")
    TeamMembership.objects.create(
        team=network, user=people["huy"], role=MembershipRole.LEAD.value, source="local"
    )
    return Ticket.objects.create(
        public_id="TKT-2026-000412",
        reporter=people["lan"],
        subject_masked="Không vào được AWS access portal",
        body_masked="Em là [EMPLOYEE_CODE_1], SĐT [PHONE_VN_1]",
        pii_level=PIILevel.SENSITIVE.value,
        category="network",
        team=network,
        assigned_team="network",
    )


def assign_to(ticket: Ticket, user: User | None, actor: User) -> Ticket:
    """Reassigns `ticket` to `user`, or to whoever the team's strategy picks, as `actor`."""
    ticket.refresh_from_db()
    return assignment.reassign(
        ticket.public_id,
        actor,
        ReassignRequest(
            to_user=user.username if user else None,
            to_team=None,
            to_category=None,
            reason_code=ReassignReason.WORKLOAD,
            note="Chia lại việc trong nhóm",
            expected_version=ticket.version,
        ),
    )


@dataclass
class Queue:
    """What would go to Celery: dispatch calls and their countdowns."""

    sent: list[tuple[str, float | None]] = field(default_factory=list)

    def ids(self) -> list[str]:
        return [message_id for message_id, _ in self.sent]


@pytest.fixture
def queue(monkeypatch) -> Queue:
    recorded = Queue()
    monkeypatch.setattr(tasks.dispatch, "delay", lambda mid: recorded.sent.append((mid, None)))
    monkeypatch.setattr(
        tasks.dispatch,
        "apply_async",
        lambda args, countdown=None: recorded.sent.append((args[0], countdown)),
    )
    return recorded


@dataclass
class FakeHost:
    """Answers every webhook POST with `status`, recording what was sent."""

    status: int = 200
    calls: list[dict[str, Any]] = field(default_factory=list)

    def check_url(self, url: str) -> tuple[str, int | None]:
        return OutboundHttp().check_url(url)

    def send(self, url: str, **kwargs: Any) -> OutboundResponse:
        OutboundHttp().check_url(url)
        self.calls.append({"url": url, **kwargs})
        return OutboundResponse(self.status, "ok")


@pytest.fixture
def host(monkeypatch) -> FakeHost:
    fake = FakeHost()
    monkeypatch.setattr("apps.notifications.utils.dispatcher.outbound", fake)
    return fake


class DownRelay(BaseEmailBackend):
    """An SMTP relay that can't be reached."""

    def send_messages(self, email_messages: Any) -> int:
        raise smtplib.SMTPServerDisconnected("relay refused the connection")


class RejectingRelay(BaseEmailBackend):
    """An SMTP relay that refuses the recipient for good."""

    def send_messages(self, email_messages: Any) -> int:
        raise smtplib.SMTPRecipientsRefused({"x@example.test": (550, b"no such user")})
