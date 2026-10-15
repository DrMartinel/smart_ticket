"""Fakes and builders for the lifecycle tests: a recording Celery queue, a recording webhook client,
and tickets placed in a workflow."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.lifecycle import tasks
from apps.lifecycle.models import Workflow, WorkflowStatus
from apps.lifecycle.request_schema import ActionIn, StatusIn, TransitionIn, WorkflowIn
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.vocabulary import PipelineStatus, TransitionPolicy
from apps.tickets.models import Ticket
from apps.tickets.utils.patterns import PIILevel
from infrastructure.outbound import OutboundHttp, OutboundResponse

_numbers = itertools.count(1)


@dataclass
class CeleryQueue:
    """Records what the lifecycle sends to Celery; `step` and `drain` run it in order."""

    sent: list[tuple[str, tuple[Any, ...], float | None]] = field(default_factory=list)

    def phase(self, args: tuple[Any, ...], countdown: float | None = None) -> None:
        self.sent.append(("run_phase", tuple(args), countdown))

    def events(self, args: tuple[Any, ...], countdown: float | None = None) -> None:
        self.sent.append(("run_event_actions", tuple(args), countdown))

    def step(self) -> float | None:
        """Runs the oldest message; returns the countdown it was sent with."""
        name, args, countdown = self.sent.pop(0)
        getattr(tasks, name).run(*args)
        return countdown

    def drain(self, limit: int = 50) -> None:
        for _ in range(limit):
            if not self.sent:
                return
            self.step()
        raise AssertionError("the queue never emptied")


@pytest.fixture
def celery(monkeypatch) -> CeleryQueue:
    """Sends what would go to Celery on commit straight to a `CeleryQueue`: a test's
    transaction never commits."""
    queue = CeleryQueue()
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, *a, **kw: func())
    monkeypatch.setattr(
        tasks.run_phase, "apply_async", lambda args, countdown=None: queue.phase(args, countdown)
    )
    monkeypatch.setattr(
        tasks.run_event_actions,
        "apply_async",
        lambda args, countdown=None: queue.events(args, countdown),
    )
    monkeypatch.setattr(tasks.run_event_actions, "delay", lambda ids: queue.events((ids,)))
    return queue


@dataclass
class FakeOutbound:
    """Answers every webhook call with `status`, recording each one."""

    status: int = 200
    text: str = "ok"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def check_url(self, url: str) -> tuple[str, int | None]:
        return OutboundHttp().check_url(url)

    def send(self, url: str, *, method: str, json_body: Any = None) -> OutboundResponse:
        self.calls.append({"url": url, "method": method, "body": json_body})
        return OutboundResponse(self.status, self.text)


@pytest.fixture
def webhooks(monkeypatch) -> FakeOutbound:
    fake = FakeOutbound()
    monkeypatch.setattr("apps.lifecycle.utils.actions.outbound", fake)
    return fake


def make_ticket(reporter: Any, *, at: PipelineStatus = PipelineStatus.PENDING_REVIEW) -> Ticket:
    """A submitted ticket the pipeline has put at `at` in the default workflow."""
    ticket = Ticket.objects.create(
        public_id=f"TKT-LC-{next(_numbers):06d}",
        reporter=reporter,
        subject_masked="VPN drops every hour",
        body_masked="Since Monday the VPN disconnects every hour.",
        pii_level=PIILevel.ROUTINE.value,
    )
    lifecycle.start(ticket)
    if at is not PipelineStatus.NEW:
        lifecycle.system_move(ticket, at)
    return ticket


@pytest.fixture
def ticket(employee_user) -> Ticket:
    return make_ticket(employee_user)


def status_of(workflow: Workflow, key: str) -> WorkflowStatus:
    return workflow.statuses.select_related("base").get(key=key)


@dataclass
class StrictFlow:
    """A strict workflow: pending_review → working → done, with `hold` ↔ working."""

    workflow: Workflow
    review: WorkflowStatus
    working: WorkflowStatus
    hold: WorkflowStatus
    done: WorkflowStatus


@pytest.fixture
def strict(manager_user) -> StrictFlow:
    workflow = workflow_config.create_workflow(
        WorkflowIn(name="Strict", transition_policy=TransitionPolicy.STRICT), actor=manager_user
    )
    bases = {
        s.base.name: s.base for s in Workflow.objects.default().statuses.select_related("base")
    }
    working = workflow_config.add_status(
        workflow, StatusIn(name="Working", base_id=bases["In progress"].id)
    )
    hold = workflow_config.add_status(workflow, StatusIn(name="Hold", base_id=bases["On hold"].id))
    done = workflow_config.add_status(workflow, StatusIn(name="Done", base_id=bases["Resolved"].id))
    review = status_of(workflow, "pending_review")
    for a, b, both in [(review, working, False), (working, hold, True), (working, done, False)]:
        workflow_config.add_transition(
            workflow,
            TransitionIn(
                from_status_id=a.id,
                to_status_id=b.id,
                name=f"{a.key}->{b.key}",
                is_bidirectional=both,
            ),
        )
    return StrictFlow(workflow, review, status_of(workflow, working.key), hold, done)


def put_in(ticket: Ticket, status: WorkflowStatus) -> Ticket:
    """Places a ticket at `status` (any workflow) the way an admin migration would."""
    ticket.workflow_status = status
    ticket.status = status.key
    ticket.save(update_fields=["workflow_status", "status"])
    return ticket


def actions(*items: dict[str, Any]) -> list[ActionIn]:
    return [ActionIn(**item) for item in items]
