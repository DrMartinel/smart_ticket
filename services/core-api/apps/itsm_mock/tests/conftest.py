"""Runbook fixtures: the phase 2 pack's people, a runbook proposal on Lan's ticket, an approved
catalog, and fakes for Keycloak's admin API and n8n."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
from django.utils import timezone

from apps.accounts.models import Capability, User, UserRole

from apps.accounts.testing import grant_capability
from apps.itsm_mock.models import ExecutorKind, Runbook
from apps.itsm_mock.utils.executors import EXECUTORS
from apps.review.models import ReviewAction, ReviewDecision, ReviewItem
from apps.tickets.models import AiRun, Ticket
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import ReviewQueue
from infrastructure.outbound import OutboundResponse


def person(username: str, role: UserRole, *capabilities: Capability) -> User:
    user = User.objects.create_user(username=username, password="x", role=role.value)
    for capability in capabilities:
        grant_capability(user, capability.value)
    return user


@pytest.fixture
def people(db) -> dict[str, User]:
    return {
        "lan.nt": person("lan.nt", UserRole.EMPLOYEE),
        "ha.vt": person("ha.vt", UserRole.TECHNICIAN),
        "duc.tm": person("duc.tm", UserRole.TECHNICIAN),
        "tu.dv": person("tu.dv", UserRole.TECHNICIAN, Capability.WORKFLOW_ADMIN),
        "huy.pq": person("huy.pq", UserRole.MANAGER),
        "quang.nv": person("quang.nv", UserRole.MANAGER),
    }


def runbook_item(
    reporter: User,
    runbook_id: str = "RB-RESET-PASSWORD",
    draft_payload: dict[str, Any] | None = None,
    queue: ReviewQueue = ReviewQueue.RUNBOOK_APPROVAL,
) -> ReviewItem:
    ticket = Ticket.objects.create(
        public_id=f"TKT-RB-{uuid.uuid4().hex[:6]}",
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )
    ai_run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="test",
        model="test",
        graph_version="test",
        trust_signals={},
        proposed_draft={
            "runbook_id": runbook_id,
            "draft_payload": {"target_username": reporter.username}
            if draft_payload is None
            else draft_payload,
        },
    )
    return ReviewItem.objects.create(ticket=ticket, ai_run=ai_run, queue=queue.value)


def record_decision(item: ReviewItem, reviewer: User, action: ReviewAction) -> None:
    ReviewDecision.objects.create(
        review_item=item,
        reviewer=reviewer,
        action_taken=action.value,
        override_reason=None if action is ReviewAction.APPROVE else "not safe to run",
        time_spent_sec=30,
    )


def approve_catalog(manager: User, *codes: str) -> None:
    """Marks the seeded runbooks approved a minute ago."""
    rows = Runbook.objects.filter(code__in=codes) if codes else Runbook.objects.all()
    rows.update(approved_by=manager, approved_at=timezone.now() - timedelta(minutes=1))


def mock_runbook(code: str, manager: User, **fields: Any) -> Runbook:
    runbook, _ = Runbook.objects.update_or_create(
        code=code,
        defaults={
            "title": "A mock runbook",
            "executor": ExecutorKind.MOCK.value,
            "config": {},
            "required_fields": ["target_username"],
            "target_rule": "reporter",
            "risk": "low",
            "approved_by": manager,
            "approved_at": timezone.now() - timedelta(minutes=1),
            **fields,
        },
    )
    return runbook


@dataclass
class FakeIam:
    """Keycloak's token endpoint and the admin calls the Keycloak executor makes."""

    users: dict[str, str] = field(default_factory=dict)
    groups: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    change_status: int = 204
    change_hangs: bool = False
    down: bool = False
    members: dict[str, set[str]] = field(default_factory=dict)
    sent_actions: dict[str, list[str]] = field(default_factory=dict)
    token_clients: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("keycloak is down", request=request)
        path = urlparse(str(request.url)).path
        self.calls.append(f"{request.method} {path}")
        if path.endswith("/protocol/openid-connect/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_clients.append(form.get("client_id", ""))
            return httpx.Response(200, json={"access_token": "runbook-token"})
        admin = path.split("/admin/realms/", 1)[1].split("/", 1)[1]
        if request.method == "GET" and admin == "users":
            name = parse_qs(urlparse(str(request.url)).query)["username"][0]
            uid = self.users.get(name)
            return httpx.Response(200, json=[{"id": uid, "username": name}] if uid else [])
        if request.method == "GET" and admin.startswith("group-by-path/"):
            gid = self.groups.get("/" + unquote(admin.split("/", 1)[1]))
            return httpx.Response(200, json={"id": gid}) if gid else httpx.Response(404)
        if self.change_hangs:
            raise httpx.ReadTimeout("no answer", request=request)
        if self.change_status >= 300:
            return httpx.Response(self.change_status, text="refused")
        parts = admin.split("/")
        if request.method == "PUT" and parts[-1] == "execute-actions-email":
            self.sent_actions[parts[1]] = json.loads(request.content)
        if request.method == "PUT" and parts[2] == "groups":
            path_of = {v: k for k, v in self.groups.items()}
            self.members.setdefault(path_of[parts[3]], set()).add(parts[1])
        return httpx.Response(204)

    def changes(self) -> list[str]:
        return [c for c in self.calls if not c.startswith("GET") and "/token" not in c]


@pytest.fixture
def iam(monkeypatch) -> FakeIam:
    fake = FakeIam(
        users={"lan.nt": "3f9b2c41-0000-4000-8000-00000000a012", "huy.pq": "u-huy"},
        groups={"/apps/vpn-users": "g-vpn", "/apps/jira-users": "g-jira"},
    )
    keycloak = EXECUTORS[ExecutorKind.KEYCLOAK]
    monkeypatch.setattr(
        keycloak,
        "http",
        # httpx._client.Client: the autouse ai-engine stub replaces httpx.Client.
        lambda: httpx._client.Client(transport=httpx.MockTransport(fake.handle)),
    )
    return fake


@dataclass
class FakeN8n:
    """Records n8n calls; `answer` is the response, or an exception to raise."""

    answer: OutboundResponse | Exception = field(
        default_factory=lambda: OutboundResponse(200, "{}")
    )
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send(self, url: str, *, method: str, json_body: Any = None, **_: Any) -> OutboundResponse:
        self.sent.append({"url": url, "method": method, "body": json_body})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def n8n(monkeypatch, settings) -> FakeN8n:
    from apps.itsm_mock.utils import executors

    settings.LIFECYCLE_WEBHOOK_ALLOWED_HOSTS = ["n8n.congty.vn"]
    fake = FakeN8n()
    monkeypatch.setattr(executors.outbound, "send", fake.send)
    return fake
