"""The security inbox (F8). What goes wrong quietly here: a security event written but never
raised, a secret queue shown to technicians, a released ticket sent back through the AI, or an
overdue alert paging twice."""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest
from django.apps import apps as django_apps

from apps.accounts.models import RefreshSession, RefusedCall, User, UserRole
from apps.audit.models import AuditLog
from apps.lifecycle.tests.conftest import make_ticket
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.notifications.models import Message
from apps.review.models import EvalCandidate, ReviewDecision, ReviewItem
from apps.security.models import SecurityAlert
from apps.security.utils.alerts import security_alerts
from apps.security.utils.vocabulary import AlertKind
from apps.tickets.models import AiRun, IncidentVerdict, Ticket
from apps.tickets.utils.pipeline import _degraded_signals, ticket_process
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import AIRunResponse, EngineSignals

pytestmark = pytest.mark.django_db

CORE_API = Path(__file__).resolve().parents[3]


def person(username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username, password="x", role=role.value, email=f"{username}@example.test"
    )


@pytest.fixture
def people(db) -> dict[str, User]:
    return {
        "lan": person("lan.nt", UserRole.EMPLOYEE),
        "duc": person("duc.tm", UserRole.TECHNICIAN),
        "anh": person("anh.lh", UserRole.SECURITY),
        "phong": person("phong.vq", UserRole.SECURITY),
        "huy": person("huy.pq", UserRole.MANAGER),
    }


@pytest.fixture
def engine(monkeypatch) -> dict[str, bool]:
    """ai-engine with every check failed; `injection` flags the ticket."""
    flags = {"injection": False}
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(Ticket, "classify_similarity", lambda *a: IncidentVerdict(kind="unique"))

    def analyze(masked, request_id):
        d = _degraded_signals()
        return AIRunResponse(
            request_id=request_id,
            graph_version="test",
            prompt_version="test",
            model="test",
            proposal=None,
            signals=EngineSignals(
                retrieval=d.retrieval,
                generation=d.generation,
                classification=d.classification,
                injection_detected=flags["injection"],
            ),
        )

    monkeypatch.setattr(ai_engine, "analyze", analyze)
    return flags


@pytest.fixture
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@pytest.fixture
def enqueued(monkeypatch) -> list[str]:
    ids: list[str] = []

    class Fake:
        def delay(self, ticket_id: str) -> None:
            ids.append(ticket_id)

    monkeypatch.setattr("apps.tickets.tasks.process_ticket", Fake())
    return ids


def submit(client, subject: str, body: str):
    return client.post(
        "/api/tickets/submit",
        {"subject": subject, "body": body},
        content_type="application/json",
    )


def blocked(people, clock, engine, *, injection: bool) -> Ticket:
    """A ticket the router blocked, with its security review item and alert."""
    engine["injection"] = injection
    ticket = make_ticket(people["lan"], at=PipelineStatus.NEW)
    if not injection:
        Ticket.objects.filter(pk=ticket.pk).update(pii_level="critical")
    ticket_process(str(ticket.id))
    ticket.refresh_from_db()
    assert ticket.status == "blocked"
    return ticket


def notices(user: User, event: str) -> list[Message]:
    return list(Message.objects.filter(user=user, event=event, channel="in_app"))


class TestRaising:
    def test_a_pasted_password_raises_a_critical_alert(
        self, people, clock, engine, api_as, ner_finds_nothing, enqueued
    ):
        """AC-F8-01 (BR-F8-02, BR-F8-04)."""
        clock.set(2026, 10, 26, 14, 5)  # Monday
        response = submit(
            api_as(people["lan"]),
            "Không đăng nhập được AWS console",
            "Không đăng nhập được AWS console. mật khẩu: Hn@2026xyz, user lan.nt",
        )
        ticket_process(enqueued[0])

        ticket = Ticket.objects.get(public_id=response.json()["ticket_public_id"])
        assert ticket.status == "blocked"
        assert ticket.routing_decisions.get().reason_code == "pii_critical"
        (alert,) = SecurityAlert.objects.all()
        assert (alert.kind, alert.severity, alert.ticket_id) == (
            "pii_critical",
            "critical",
            ticket.id,
        )
        assert alert.ack_due_at == clock.set(2026, 10, 26, 15, 5)
        assert len(notices(people["anh"], "security.alert")) == 1

    def test_every_security_alert_audit_raises_an_alert(self):
        """BR-F8-02: nothing outside the security service writes a `security_alert` audit row."""
        writers = []
        for path in (CORE_API / "apps").rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts or "security" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "record"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "security_alert"
                ):
                    writers.append(str(path.relative_to(CORE_API)))
        assert writers == []

    def test_repeat_alerts_group(self, people, clock):
        """AC-F8-03 (BR-F8-03)."""
        duc = people["duc"]
        security_alerts.raise_(AlertKind.REFRESH_TOKEN_REUSED, subject_user=duc)
        clock.now += timedelta(minutes=10)
        security_alerts.raise_(AlertKind.REFRESH_TOKEN_REUSED, subject_user=duc)

        (alert,) = SecurityAlert.objects.all()
        assert alert.count == 2
        assert len(notices(people["anh"], "security.alert")) == 1

    def test_an_alert_after_the_window_is_a_new_one(self, people, clock):
        duc = people["duc"]
        security_alerts.raise_(AlertKind.REFRESH_TOKEN_REUSED, subject_user=duc)
        clock.now += timedelta(minutes=61)
        security_alerts.raise_(AlertKind.REFRESH_TOKEN_REUSED, subject_user=duc)

        assert SecurityAlert.objects.count() == 2


class TestQueues:
    def test_technicians_dont_see_the_secret_queues(self, people, api_as):
        """AC-F8-02 (BR-F8-07)."""
        secret = make_ticket(people["lan"])
        normal = make_ticket(people["lan"])
        ReviewItem.objects.create(ticket=secret, queue="pii_verify", priority=1)
        kept = ReviewItem.objects.create(ticket=normal, queue="low_confidence", priority=3)

        rows = api_as(people["duc"]).get("/api/review/queue").json()
        assert [r["id"] for r in rows] == [str(kept.id)]
        assert len(api_as(people["anh"]).get("/api/review/queue").json()) == 2

    def test_a_secret_queue_item_is_refused_to_technicians(self, people, api_as):
        item = ReviewItem.objects.create(
            ticket=make_ticket(people["lan"]), queue="injection", priority=1
        )

        assert api_as(people["duc"]).get(f"/api/review/items/{item.id}").status_code == 403
        assert api_as(people["anh"]).get(f"/api/review/items/{item.id}").status_code == 200

    def test_the_review_view_hides_blocked_tickets_from_technicians(self, people, api_as):
        secret = make_ticket(people["lan"])
        ReviewItem.objects.create(ticket=secret, queue="pii_verify", priority=1)

        rows = api_as(people["duc"]).get("/api/tickets?view=review").json()
        items = rows["items"] if isinstance(rows, dict) else rows
        assert secret.public_id not in {r["public_id"] for r in items}


class TestTicketActions:
    def test_release_goes_to_a_person_not_the_ai(self, people, clock, engine, api_as):
        """AC-F8-04 (BR-F8-06)."""
        ticket = blocked(people, clock, engine, injection=True)
        alert = SecurityAlert.objects.get(ticket=ticket)
        runs = AiRun.objects.filter(ticket=ticket).count()

        response = api_as(people["anh"]).post(
            f"/api/security/alerts/{alert.id}/release-ticket",
            {"reason": "Câu hỏi hợp lệ về đổi thiết bị MFA"},
            content_type="application/json",
        )

        assert response.status_code == 200
        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ticket.review_items.filter(queue="low_confidence", state="pending").count() == 1
        decision = ReviewDecision.objects.get(review_item__ticket=ticket)
        assert decision.action_taken == "reject"
        assert decision.override_reason == "Câu hỏi hợp lệ về đổi thiết bị MFA"
        assert EvalCandidate.objects.filter(ticket=ticket).count() == 1
        assert AiRun.objects.filter(ticket=ticket).count() == runs

    def test_release_needs_a_reason_and_a_blocked_ticket(self, people, clock, engine, api_as):
        ticket = blocked(people, clock, engine, injection=True)
        alert = SecurityAlert.objects.get(ticket=ticket)
        client = api_as(people["anh"])

        empty = client.post(
            f"/api/security/alerts/{alert.id}/release-ticket",
            {"reason": " "},
            content_type="application/json",
        )
        assert (empty.status_code, empty.json()["code"]) == (422, "reason_required")
        client.post(
            f"/api/security/alerts/{alert.id}/release-ticket",
            {"reason": "hợp lệ"},
            content_type="application/json",
        )
        again = client.post(
            f"/api/security/alerts/{alert.id}/release-ticket",
            {"reason": "hợp lệ"},
            content_type="application/json",
        )
        assert (again.status_code, again.json()["code"]) == (409, "not_blocked")

    def test_a_true_positive_keeps_the_ticket_blocked_and_assigns_nobody(
        self, people, clock, engine, api_as
    ):
        ticket = blocked(people, clock, engine, injection=False)
        alert = SecurityAlert.objects.get(ticket=ticket)

        response = api_as(people["anh"]).post(
            f"/api/security/alerts/{alert.id}/close",
            {"resolution": "true_positive", "note": "Mật khẩu thật, đã nhắc đổi"},
            content_type="application/json",
        )

        assert response.json()["state"] == "closed"
        ticket.refresh_from_db()
        assert ticket.status == "blocked"
        assert ticket.assigned_to is None and ticket.team is None
        assert ReviewDecision.objects.get(review_item__ticket=ticket).action_taken == "approve"
        assert not EvalCandidate.objects.filter(ticket=ticket).exists()

    def test_credential_alert_notifies_requester(self, people, clock, engine, api_as):
        """BR-F8-05."""
        ticket = blocked(people, clock, engine, injection=False)
        alert = SecurityAlert.objects.get(ticket=ticket)

        response = api_as(people["anh"]).post(f"/api/security/alerts/{alert.id}/notify-requester")

        assert response.status_code == 204
        (notice,) = notices(people["lan"], "security.credential_exposed")
        assert "Hãy đổi mật khẩu ngay" in notice.body

    def test_an_injection_alert_has_no_requester_notice(self, people, clock, engine, api_as):
        ticket = blocked(people, clock, engine, injection=True)
        alert = SecurityAlert.objects.get(ticket=ticket)

        response = api_as(people["anh"]).post(f"/api/security/alerts/{alert.id}/notify-requester")

        assert (response.status_code, response.json()["code"]) == (409, "not_a_credential")


class TestTriage:
    def test_acknowledge_assign_note_close_reopen(self, people, api_as):
        alert = security_alerts.raise_(AlertKind.AMBIGUOUS_ROLE, subject_user=people["duc"])
        client = api_as(people["anh"])
        base = f"/api/security/alerts/{alert.id}"

        assert client.post(f"{base}/ack").json()["state"] == "acknowledged"
        assert client.post(f"{base}/ack").json()["code"] == "not_new"
        assigned = client.post(
            f"{base}/assign", {"user": "phong.vq"}, content_type="application/json"
        )
        assert (assigned.json()["state"], assigned.json()["assignee"]) == (
            "investigating",
            "phong.vq",
        )
        refused = client.post(f"{base}/assign", {"user": "duc.tm"}, content_type="application/json")
        assert refused.json()["code"] == "not_security"
        note = client.post(
            f"{base}/notes", {"note": "Gọi cho lan.nt@congty.vn"}, content_type="application/json"
        ).json()
        assert "lan.nt@congty.vn" not in note["note_masked"]
        no_note = client.post(
            f"{base}/close",
            {"resolution": "false_positive", "note": ""},
            content_type="application/json",
        )
        assert no_note.json()["code"] == "note_required"
        closed = client.post(
            f"{base}/close",
            {"resolution": "false_positive", "note": "Vai trò đã sửa trong Keycloak"},
            content_type="application/json",
        ).json()
        assert (closed["state"], closed["resolution"]) == ("closed", "false_positive")
        reopened = client.post(
            f"{base}/reopen", {"note": "Lại xảy ra"}, content_type="application/json"
        ).json()
        assert (reopened["state"], reopened["resolution"]) == ("investigating", None)
        events = [e["kind"] for e in reopened["events"]]
        assert events[:2] == ["raised", "ack"]
        for name in (
            "security_alert_acknowledged",
            "security_alert_closed",
            "security_alert_reopened",
        ):
            assert AuditLog.objects.filter(event=name).count() == 1

    def test_a_duplicate_names_its_original(self, people, api_as):
        alert = security_alerts.raise_(AlertKind.AMBIGUOUS_ROLE, subject_user=people["duc"])
        response = api_as(people["anh"]).post(
            f"/api/security/alerts/{alert.id}/close",
            {"resolution": "duplicate", "note": "trùng"},
            content_type="application/json",
        )
        assert response.json()["code"] == "duplicate_required"

    def test_end_sessions_revokes_the_users_sign_ins(self, people, api_as):
        alert = security_alerts.raise_(AlertKind.REFRESH_TOKEN_REUSED, subject_user=people["duc"])
        api_as(people["duc"])  # a live sign-in

        detail = api_as(people["anh"]).post(f"/api/security/alerts/{alert.id}/end-sessions").json()

        assert detail["sessions"] == []
        assert not RefreshSession.objects.filter(
            user=people["duc"], revoked_at__isnull=True
        ).exists()

    def test_managers_see_counts_only(self, people, api_as):
        """AC-F8-06 (BR-F8-01)."""
        security_alerts.raise_(AlertKind.AMBIGUOUS_ROLE, subject_user=people["duc"])
        client = api_as(people["huy"])

        assert client.get("/api/security/alerts").status_code == 403
        summary = client.get("/api/security/summary")
        assert summary.status_code == 200
        assert summary.json()["cells"] == [{"kind": "ambiguous_role", "state": "new", "count": 1}]
        assert "duc" not in summary.content.decode()

    def test_the_inbox_is_most_severe_first_then_oldest(self, people, clock, api_as):
        security_alerts.raise_(AlertKind.AMBIGUOUS_ROLE, subject_user=people["duc"])
        clock.now += timedelta(minutes=1)
        security_alerts.raise_(AlertKind.BREAK_GLASS_SIGN_IN, subject_user=people["huy"])

        rows = api_as(people["anh"]).get("/api/security/alerts").json()
        assert [r["kind"] for r in rows] == ["break_glass_sign_in", "ambiguous_role"]


class TestSweep:
    def test_overdue_acknowledgement_is_escalated_once(self, people, clock):
        """AC-F8-05 (BR-F8-04)."""
        clock.set(2026, 10, 26, 14, 5)
        security_alerts.raise_(AlertKind.PII_CRITICAL, subject_user=people["lan"])

        clock.set(2026, 10, 26, 15, 6)
        security_alerts.sweep()
        clock.set(2026, 10, 26, 15, 30)
        security_alerts.sweep()

        assert len(notices(people["anh"], "security.ack_overdue")) == 1

    def test_an_acknowledged_alert_is_never_overdue(self, people, clock):
        clock.set(2026, 10, 26, 14, 5)
        alert = security_alerts.raise_(AlertKind.PII_CRITICAL, subject_user=people["lan"])
        security_alerts.acknowledge(alert.id, people["anh"])

        clock.set(2026, 10, 26, 16, 0)
        security_alerts.sweep()

        assert notices(people["anh"], "security.ack_overdue") == []

    def test_a_burst_of_refusals_raises_one_alert(self, people, clock):
        """AC-F8-07 (BR-F8-08)."""
        contractor = person("tmp.contractor3", UserRole.EMPLOYEE)
        for minute in range(20):
            clock.set(2026, 10, 26, 10, minute // 2 * 1)
            RefusedCall.objects.create(user=contractor, route="api/review/queue")

        clock.set(2026, 10, 26, 10, 10)
        security_alerts.sweep()
        security_alerts.sweep()

        (alert,) = SecurityAlert.objects.filter(kind="access_denied_burst")
        assert alert.subject_user == contractor

    def test_nineteen_refusals_raise_nothing(self, people, clock):
        contractor = person("tmp.contractor4", UserRole.EMPLOYEE)
        for _ in range(19):
            RefusedCall.objects.create(user=contractor, route="api/review/queue")

        security_alerts.sweep()

        assert not SecurityAlert.objects.filter(kind="access_denied_burst").exists()

    def test_a_refused_call_is_recorded_for_burst_detection(self, people, api_as):
        api_as(people["lan"]).get("/api/security/alerts")

        assert RefusedCall.objects.filter(user=people["lan"]).count() == 1


class TestBackfill:
    def test_last_months_audit_rows_become_grouped_alerts_without_paging(
        self,
        people,
        clock,
    ):
        """§g migration: history becomes alerts; nobody is paged for it."""
        from importlib import import_module

        backfill = import_module("apps.security.migrations.0002_backfill_alerts").backfill
        for _ in range(2):
            AuditLog.objects.record(
                "security_alert",
                actor_type="system",
                actor_id=people["duc"].id,
                payload={"reason": "refresh_token_reused"},
            )
        now = clock.now
        clock.now = now - timedelta(days=40)
        AuditLog.objects.record(
            "security_alert", actor_type="system", payload={"reason": "ambiguous_role"}
        )
        clock.now = now

        backfill(django_apps, None)

        (alert,) = SecurityAlert.objects.all()
        assert (alert.kind, alert.count, alert.subject_user) == (
            "refresh_token_reused",
            2,
            people["duc"],
        )
        assert alert.ack_overdue_notified_at is not None
