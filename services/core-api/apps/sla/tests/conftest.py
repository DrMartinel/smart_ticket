"""A controllable clock, the seeded VN office calendar and P1–P4 policies, people, and tickets moved
through the default workflow (F1)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.lifecycle.models import Workflow, WorkflowStatus
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.tickets.models import Ticket

VN = ZoneInfo("Asia/Ho_Chi_Minh")
_numbers = itertools.count(1)


def vn(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=VN)


@dataclass
class Clock:
    """What `timezone.now()` answers; tests move it forward."""

    now: datetime

    def set(self, *parts: int) -> datetime:
        self.now = vn(*parts)
        return self.now


@pytest.fixture
def clock(monkeypatch) -> Clock:
    current = Clock(vn(2026, 10, 23, 15, 0))
    monkeypatch.setattr(timezone, "now", lambda: current.now)
    return current


@pytest.fixture
def people(db) -> dict[str, User]:
    def person(username: str, role: UserRole) -> User:
        return User.objects.create_user(
            username=username, password="x", role=role.value, email=f"{username}@example.test"
        )

    return {
        "lan": person("lan.nt", UserRole.EMPLOYEE),
        "mai": person("mai.bn", UserRole.TECHNICIAN),
        "ha": person("ha.vt", UserRole.TECHNICIAN),
        "huy": person("huy.pq", UserRole.MANAGER),
        "quang": person("quang.nv", UserRole.MANAGER),
        "tu": person("tu.dv", UserRole.TECHNICIAN),
    }


def submitted(reporter: User, **fields: Any) -> Ticket:
    """A ticket at `new` in the default workflow."""
    ticket = Ticket.objects.create(
        public_id=fields.pop("public_id", f"TKT-SLA-{next(_numbers):06d}"),
        reporter=reporter,
        subject_masked="Laptop không nhận màn hình thứ hai sau update Windows",
        body_masked="Màn hình thứ hai không lên",
        pii_level="routine",
        **fields,
    )
    lifecycle.start(ticket)
    return ticket


def status(key: str) -> WorkflowStatus:
    return Workflow.objects.default().statuses.select_related("base").get(key=key)


def handed_off(reporter: User, **fields: Any) -> Ticket:
    ticket = submitted(reporter, **fields)
    lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)
    ticket.refresh_from_db()
    return ticket


def move(ticket: Ticket, key: str, actor: User) -> Ticket:
    """A person's move in the default (open) workflow."""
    lifecycle.move(ticket.id, status(key).id, actor=actor, force=False, expected_version=None)
    ticket.refresh_from_db()
    return ticket
