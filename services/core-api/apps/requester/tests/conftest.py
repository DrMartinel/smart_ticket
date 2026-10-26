"""The F3 Background: Lan (employee) reports tickets the Network team works; a controllable clock
on the seeded VN office calendar; masking with the NER tier finding nothing, or failing."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from apps.accounts.models import User
from apps.lifecycle.models import Workflow, WorkflowStatus
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.notifications.models import Message
from apps.sla.tests.conftest import Clock, clock  # noqa: F401 — the fixture
from apps.teams.tests.conftest import Network, network  # noqa: F401 — the fixture
from apps.tickets.models import Ticket
from apps.tickets.utils.masking import NERError

_numbers = iter(range(1, 10_000))


@pytest.fixture
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a: Any, **kw: Any) -> list[str]:
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@pytest.fixture
def ner_fails(monkeypatch):
    async def fake_ner(*a: Any, **kw: Any) -> list[str]:
        raise NERError("ner down")

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@pytest.fixture
def enqueued(monkeypatch) -> list[str]:
    """Stands in for the Celery task; nothing runs the pipeline."""
    ids: list[str] = []

    class Fake:
        def delay(self, ticket_id: str) -> None:
            ids.append(ticket_id)

    monkeypatch.setattr("apps.tickets.tasks.process_ticket", Fake())
    return ids


@pytest.fixture
def desk(clock: Clock, network: Network, ner_finds_nothing) -> Network:  # noqa: F811
    """Monday 26 Oct 2026, 09:00 in Hà Nội, with the Network team in place; the team's earlier
    work was reported by someone other than Lan."""
    from apps.teams.tests.conftest import person

    clock.set(2026, 10, 26, 9, 0)
    Ticket.objects.filter(reporter=network.people["lan"]).update(reporter=person("binh.tt"))
    return network


def status(key: str) -> WorkflowStatus:
    return Workflow.objects.default().statuses.select_related("base").get(key=key)


def reported(reporter: User, **fields: Any) -> Ticket:
    """A ticket of `reporter` at `new` in the default workflow."""
    ticket = Ticket.objects.create(
        public_id=fields.pop("public_id", f"TKT-RQ-{next(_numbers):06d}"),
        reporter=reporter,
        subject_masked=fields.pop("subject_masked", "VPN báo lỗi TLS handshake failed"),
        body_masked=fields.pop(
            "body_masked", "VPN báo lỗi TLS handshake failed khi kết nối từ nhà"
        ),
        pii_level="routine",
        **fields,
    )
    lifecycle.start(ticket)
    return ticket


def with_support(reporter: User, assignee: User | None = None, **fields: Any) -> Ticket:
    """A Network ticket handed to support, optionally assigned."""
    from apps.teams.models import Team

    team = Team.objects.get(slug="network")
    ticket = reported(reporter, category="network", **fields)
    lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)
    Ticket.objects.filter(pk=ticket.pk).update(
        team=team, assigned_team=team.slug, assigned_to=assignee
    )
    ticket.refresh_from_db()
    return ticket


def move(ticket: Ticket, key: str, actor: User) -> Ticket:
    """A person's move in the default (open) workflow."""
    lifecycle.move(ticket.id, status(key).id, actor=actor, force=False, expected_version=None)
    ticket.refresh_from_db()
    return ticket


def resolved(reporter: User, clock: Clock, days_ago: int, **fields: Any) -> Ticket:  # noqa: F811
    """A ticket support resolved `days_ago` days before the clock's now."""
    now = clock.now
    clock.now = now - timedelta(days=days_ago)
    ticket = with_support(reporter, **fields)
    lifecycle.automatic_move(ticket, "resolved")
    clock.now = now
    ticket.refresh_from_db()
    return ticket


def auto_replied(reporter: User, clock: Clock, days_ago: int) -> Ticket:  # noqa: F811
    """A live auto-reply `days_ago` days before the clock's now, with its routing decision."""
    from apps.tickets.models import AiRun, RoutingDecision

    now = clock.now
    clock.now = now - timedelta(days=days_ago)
    ticket = reported(reporter, category="network")
    run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        graph_version="test",
        prompt_version="test",
        model="test",
        trust_signals={},
        proposed_draft={"proposed_intent": "auto_reply", "kb_slug": "client-vpn-user.windows"},
    )
    RoutingDecision.objects.create(
        ticket=ticket,
        ai_run=run,
        branch="auto_reply",
        reason_code="auto_reply_ok",
        reason_detail="",
        thresholds_used={},
        shadow_mode=False,
    )
    lifecycle.system_move(ticket, PipelineStatus.AUTO_REPLIED)
    clock.now = now
    ticket.refresh_from_db()
    return ticket


def notices(user: User, event: str) -> list[Message]:
    return list(Message.objects.filter(user=user, event=event, channel="in_app"))
