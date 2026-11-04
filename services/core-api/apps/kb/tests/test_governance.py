"""KB drafts, review, authority and gaps (F6, ADR-0036). What goes wrong quietly here: a draft
reaching retrieval, an approval of old text covering new text, or one person both writing and
approving what the model may quote."""

from __future__ import annotations

import math
from datetime import timedelta

import httpx
import pytest
from django.db import connection
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import Capability, User, UserCapability, UserRole
from apps.audit.models import AuditLog
from apps.kb.models import KbArticle, KbAuthorityLog, KbChunk, KbGapCluster, KbGapReport
from apps.kb.utils.authority import kb_authority
from apps.kb.utils.gaps import kb_gaps
from apps.notifications.models import Message
from apps.review.models import ReviewDecision, ReviewItem
from apps.tickets.models import RoutingDecision, Ticket
from apps.tickets.tests.test_router import TH, auto_reply_proposal, good_signals
from apps.tickets.utils.pipeline import _kb_meta
from apps.tickets.utils.router import ReasonCode, Router

pytestmark = pytest.mark.django_db

SLUG = "identity-center.resetpassword-accessportal"
BODY = "Choose Forgot password on the sign-in page.\n\nFollow the email link."
SSO = BODY + "\n\nNhân viên công ty: dùng cổng SSO nội bộ thay vì liên kết 'Forgot password'."


def person(username: str, role: UserRole, *, editor: bool = False) -> User:
    user = User.objects.create_user(username=username, password="x", role=role.value)
    if editor:
        UserCapability.objects.create(user=user, capability=Capability.KB_EDITOR.value)
    return user


@pytest.fixture
def team() -> dict[str, User]:
    return {
        "mai": person("mai.bn", UserRole.TECHNICIAN, editor=True),
        "ha": person("ha.vt", UserRole.TECHNICIAN, editor=True),
        "huy": person("huy.pq", UserRole.MANAGER),
        "tech": person("tuan.nv", UserRole.TECHNICIAN),
        "sec": person("an.sec", UserRole.SECURITY),
    }


@pytest.fixture
def clients(team, api_as) -> dict:
    return {name: api_as(user) for name, user in team.items()}


@pytest.fixture
def ingest_now(monkeypatch):
    """Runs the publish task's ingest in place of queueing it."""
    from apps.kb.tasks import publish_draft
    from apps.kb.utils.drafts import kb_drafts

    monkeypatch.setattr(publish_draft, "delay", lambda draft_id: kb_drafts.ingest(draft_id))


@pytest.fixture
def live(team) -> KbArticle:
    """The page in F6 §g: version 3, low risk, allowed for the text it has."""
    article = KbArticle.objects.create(
        slug=SLUG,
        title="Resetting your AWS access portal user password",
        body=BODY,
        category="access",
        risk_tier="low",
        version=2,
    )
    article.set_auto_reply_allowed(allowed=True, actor=team["huy"], reason="reviewed")
    return article


def draft(client, **body):
    return client.post("/api/kb/drafts", body, content_type="application/json")


def act(client, draft_id: str, action: str, **body):
    return client.post(f"/api/kb/drafts/{draft_id}/{action}", body, content_type="application/json")


def write_and_submit(client, **body) -> str:
    created = draft(client, **body)
    assert created.status_code == 201, created.json()
    draft_id = created.json()["id"]
    assert act(client, draft_id, "submit").status_code == 200
    return draft_id


def approve(client, draft_id: str, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return act(client, draft_id, "review", decision="approve", comment="ok")


class TestDrafts:
    def test_draft_invisible_to_ai_engine_queries(self, clients):
        """AC-F6-01 (BR-F6-01): a draft writes no page and no chunk, and ai-engine's role can't
        read drafts."""
        created = draft(
            clients["mai"],
            kind="create",
            slug="printer-floor5-hp",
            title="Máy in tầng 5",
            body="Máy in tầng 5 báo offline: khởi động lại.",
            category="hardware",
        )

        assert created.status_code == 201
        assert not KbArticle.objects.filter(slug="printer-floor5-hp").exists()
        assert not KbChunk.objects.filter(content__contains="tầng 5").exists()
        with connection.cursor() as cursor:
            cursor.execute("SELECT has_table_privilege('ai_engine_ro', 'kb_drafts', 'SELECT')")
            assert cursor.fetchone() == (False,)

    def test_post_kb_creates_a_draft_not_a_live_page(self, clients):
        """FR-F6-014."""
        made = clients["huy"].post(
            "/api/kb",
            {
                "slug": "KB-TEST-001",
                "title": "Reset VPN",
                "body": "Open the portal.",
                "category": "network",
            },
            content_type="application/json",
        )

        assert made.status_code == 201
        assert made.json()["state"] == "draft"
        assert not KbArticle.objects.filter(slug="KB-TEST-001").exists()

    def test_people_without_kb_rights_cannot_draft(self, clients, employee_user, api_as):
        body = {"kind": "create", "slug": "x", "title": "x", "body": "x", "category": "other"}
        assert draft(clients["tech"], **body).status_code == 403
        assert draft(api_as(employee_user), **body).status_code == 403

    def test_an_empty_body_is_refused(self, clients):
        refused = draft(
            clients["mai"], kind="create", slug="x", title="x", body="  ", category="other"
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "title_and_body_required"

    def test_a_new_page_slug_that_exists_is_refused(self, clients, live):
        refused = draft(
            clients["mai"], kind="create", slug=SLUG, title="t", body="b", category="access"
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "slug_taken"

    def test_an_edit_of_a_page_that_does_not_exist_is_refused(self, clients):
        refused = draft(clients["mai"], kind="edit", slug="nope", body="b")
        assert refused.status_code == 404
        assert refused.json()["code"] == "article_not_found"

    def test_submit_tells_reviewers(self, clients, team, live):
        write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        assert Message.objects.filter(user=team["ha"], event="kb.review_requested").exists()
        assert AuditLog.objects.filter(event="kb_draft_submitted").count() == 1

    def test_a_draft_in_review_cannot_be_edited(self, clients, live):
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        refused = clients["mai"].patch(
            f"/api/kb/drafts/{draft_id}", {"body": "x"}, content_type="application/json"
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "not_editable"

    def test_diff_shows_the_change_and_the_chunks(self, clients, live):
        made = draft(clients["mai"], kind="edit", slug=SLUG, body=SSO).json()

        diff = clients["ha"].get(f"/api/kb/drafts/{made['id']}/diff").json()

        assert any("cổng SSO" in line and line.startswith("+") for line in diff["body_diff"])
        assert diff["chunks_preview"]


class TestReview:
    def test_self_review_refused(self, clients, live):
        """AC-F6-02 (BR-F6-02)."""
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        refused = act(clients["mai"], draft_id, "review", decision="approve", comment="")

        assert refused.status_code == 403
        assert refused.json()["code"] == "self_review"
        assert KbArticle.objects.get(slug=SLUG).body == BODY

    def test_request_changes_needs_a_comment(self, clients, live):
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        refused = act(clients["ha"], draft_id, "review", decision="request_changes", comment=" ")
        assert refused.status_code == 422
        assert refused.json()["code"] == "comment_required"

        sent_back = act(
            clients["ha"], draft_id, "review", decision="request_changes", comment="thêm ảnh"
        )
        assert sent_back.json()["state"] == "changes_requested"
        assert act(clients["mai"], draft_id, "submit").json()["state"] == "in_review"

    def test_edit_revokes_authority_with_log_row(
        self, clients, team, live, ingest_now, django_capture_on_commit_callbacks
    ):
        """AC-F6-03 (BR-F6-03, BR-F6-04)."""
        assert live.version == 3
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        published = approve(clients["ha"], draft_id, django_capture_on_commit_callbacks)

        assert published.json()["state"] == "published"
        page = KbArticle.objects.get(slug=SLUG)
        assert (page.version, page.auto_reply_allowed, page.body) == (4, False, SSO)
        revoked = KbAuthorityLog.objects.filter(article=page, new_value="False")
        assert [(r.old_value, r.actor) for r in revoked] == [("True", team["ha"])]
        assert f"bản nháp {draft_id}" in revoked[0].reason
        assert [(i.article.slug, i.reason) for i in kb_authority.queue()] == [(SLUG, "regrant")]
        shown = clients["huy"].get("/api/kb/authority-queue").json()
        assert [(i["article"]["slug"], i["reason"], i["draft_id"]) for i in shown] == [
            (SLUG, "regrant", draft_id)
        ]
        assert any("cổng SSO" in line for line in shown[0]["body_diff"])
        assert KbChunk.objects.filter(article=page, content__contains="cổng SSO").exists()
        assert Message.objects.filter(user=team["huy"], event="kb.authority_needed").exists()

    def test_the_authority_notice_opens_the_admin_queue(
        self, clients, team, live, ingest_now, django_capture_on_commit_callbacks
    ):
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        approve(clients["ha"], draft_id, django_capture_on_commit_callbacks)

        notice = Message.objects.get(
            user=team["huy"], event="kb.authority_needed", channel="in_app"
        )
        assert notice.link == "/admin/kb/authority"

    def test_publish_never_grants_authority(
        self, clients, ingest_now, django_capture_on_commit_callbacks
    ):
        """BR-F6-03: a new page goes live high-risk with no authority, waiting for a manager."""
        draft_id = write_and_submit(
            clients["mai"],
            kind="create",
            slug="vpn.reset",
            title="Reset VPN",
            body="Open the portal.",
            category="network",
            proposed_risk_tier="low",
        )

        approve(clients["ha"], draft_id, django_capture_on_commit_callbacks)

        page = KbArticle.objects.get(slug="vpn.reset")
        assert (page.auto_reply_allowed, page.risk_tier, page.is_active) == (False, "high", True)
        assert not page.is_authorized()
        assert not KbAuthorityLog.objects.filter(article=page).exists()
        assert [(i.article.slug, i.reason) for i in kb_authority.queue()] == [("vpn.reset", "new")]
        assert KbChunk.objects.filter(article=page).exists()

    def test_a_stale_draft_is_caught(
        self, clients, team, live, ingest_now, django_capture_on_commit_callbacks
    ):
        """AC-F6-07: a draft started before another edit was published conflicts."""
        stale = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)
        first = write_and_submit(clients["ha"], kind="edit", slug=SLUG, body=BODY + "\n\nThêm.")
        approve(clients["mai"], first, django_capture_on_commit_callbacks)
        before = KbArticle.objects.get(slug=SLUG)

        caught = approve(clients["ha"], stale, django_capture_on_commit_callbacks)

        assert caught.json()["state"] == "conflict"
        after = KbArticle.objects.get(slug=SLUG)
        assert (after.version, after.body) == (before.version, before.body)
        rebased = act(clients["mai"], stale, "rebase").json()
        assert (rebased["state"], rebased["base_version"]) == ("draft", after.version)

    def test_a_grant_alone_is_not_a_conflict(
        self, clients, team, live, ingest_now, django_capture_on_commit_callbacks
    ):
        """A grant bumps `version` without changing the text; the draft still publishes."""
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)
        live.set_auto_reply_allowed(allowed=False, actor=team["huy"], reason="tạm dừng")

        assert (
            approve(clients["ha"], draft_id, django_capture_on_commit_callbacks).json()["state"]
            == "published"
        )

    def test_retire_revokes_and_hides_the_page(
        self, clients, team, live, django_capture_on_commit_callbacks
    ):
        """UC-F6-07."""
        draft_id = write_and_submit(
            clients["mai"], kind="retire", slug=SLUG, change_note="đã lỗi thời"
        )

        approve(clients["ha"], draft_id, django_capture_on_commit_callbacks)

        page = KbArticle.objects.get(slug=SLUG)
        assert (page.is_active, page.auto_reply_allowed) == (False, False)
        assert KbAuthorityLog.objects.filter(article=page, new_value="False").count() == 1
        assert AuditLog.objects.filter(event="kb_retired").count() == 1
        assert kb_authority.queue() == []

    def test_a_failed_ingest_keeps_the_old_chunks(
        self, clients, live, serve_ai_engine, django_capture_on_commit_callbacks, ingest_now
    ):
        """UC-F6-02 3y."""
        from apps.kb.utils.indexing import indexer

        indexer.ingest(live)
        old = set(KbChunk.objects.filter(article=live).values_list("content", flat=True))
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)

        def unreachable(request):
            raise httpx.ConnectError("ai-engine unreachable")

        serve_ai_engine(unreachable)
        approve(clients["ha"], draft_id, django_capture_on_commit_callbacks)

        assert KbArticle.objects.get(slug=SLUG).body == SSO
        assert set(KbChunk.objects.filter(article=live).values_list("content", flat=True)) == old
        assert AuditLog.objects.filter(event="kb_ingest_failed").count() == 1


class TestAuthority:
    def test_hash_mismatch_means_not_authorized(self, live):
        """AC-F6-04 (BR-F6-05): text changed outside a draft loses authority everywhere."""
        KbArticle.objects.filter(pk=live.pk).update(body=SSO)
        page = KbArticle.objects.get(pk=live.pk)

        assert page.auto_reply_allowed and not page.is_authorized()
        assert not KbArticle.objects.authorized().filter(pk=page.pk).exists()
        meta = _kb_meta(auto_reply_proposal(kb_slug=SLUG))
        assert meta is not None and meta.auto_reply_allowed is False
        signals = good_signals(**{"policy.kb_auto_reply_allowed": meta.auto_reply_allowed})
        decision = Router(TH).route(signals, auto_reply_proposal(kb_slug=SLUG), meta)
        assert decision.reason_code is ReasonCode.KB_NOT_AUTHORIZED
        assert [i.article.slug for i in kb_authority.queue()] == [SLUG]

    def test_the_database_hash_matches_the_python_hash(self, live):
        assert KbArticle.objects.authorized().filter(pk=live.pk).exists()

    def test_a_grant_pins_the_text_and_settles_the_queue(
        self, clients, team, live, ingest_now, django_capture_on_commit_callbacks
    ):
        """UC-F6-04."""
        draft_id = write_and_submit(clients["mai"], kind="edit", slug=SLUG, body=SSO)
        approve(clients["ha"], draft_id, django_capture_on_commit_callbacks)

        granted = clients["huy"].post(
            f"/api/kb/{SLUG}/auto-reply-allowed",
            {"allowed": True, "reason": "Tôi đã đọc nội dung này"},
            content_type="application/json",
        )

        assert granted.status_code == 200
        page = KbArticle.objects.get(slug=SLUG)
        assert page.is_authorized() and page.approved_text_sha256 == page.text_sha256()
        assert kb_authority.queue() == []

    def test_only_a_manager_grants(self, clients, live):
        for who in ("mai", "tech"):
            refused = clients[who].post(
                f"/api/kb/{SLUG}/auto-reply-allowed",
                {"allowed": True, "reason": "x"},
                content_type="application/json",
            )
            assert refused.status_code == 403

    def test_bulk_refuses_high_risk(self, clients):
        """AC-F6-05 (BR-F6-06, ADR-0027)."""
        for slug, tier in (("a", "low"), ("b", "medium"), ("c", "high")):
            KbArticle.objects.create(
                slug=slug, title=slug, body=slug, category="other", risk_tier=tier
            )

        refused = clients["huy"].post(
            "/api/kb/auto-reply-allowed/bulk",
            {"slugs": ["a", "b", "c"], "allowed": True, "reason": "đợt duyệt"},
            content_type="application/json",
        )

        assert refused.status_code == 422
        assert refused.json()["code"] == "high_risk_needs_single_review"
        assert not KbArticle.objects.filter(auto_reply_allowed=True).exists()
        assert not KbAuthorityLog.objects.exists()

    def test_bulk_writes_one_log_row_per_page(self, clients):
        for slug, tier in (("a", "low"), ("b", "medium")):
            KbArticle.objects.create(
                slug=slug, title=slug, body=slug, category="other", risk_tier=tier
            )

        done = clients["huy"].post(
            "/api/kb/auto-reply-allowed/bulk",
            {"slugs": ["a", "b"], "allowed": True, "reason": "đợt duyệt"},
            content_type="application/json",
        )

        assert done.json() == {"updated": 2}
        assert KbAuthorityLog.objects.filter(new_value="True").count() == 2
        assert KbArticle.objects.authorized().count() == 2

    def test_the_log_is_readable_and_its_export_audited(self, clients, live):
        """UC-F6-05."""
        rows = clients["sec"].get("/api/kb/authority-log", {"slug": SLUG}).json()
        assert [(r["field"], r["new_value"], r["actor"]) for r in rows["items"]] == [
            ("auto_reply_allowed", "True", "huy.pq")
        ]
        assert clients["mai"].get("/api/kb/authority-log").status_code == 200
        assert clients["tech"].get("/api/kb/authority-log").status_code == 403

        csv = clients["huy"].get("/api/kb/authority-log.csv", {"slug": SLUG})

        assert csv["Content-Type"].startswith("text/csv")
        assert SLUG in csv.content.decode()
        assert AuditLog.objects.filter(event="kb_authority_log_exported").count() == 1


def unit(*parts: tuple[int, float]) -> list[float]:
    vector = [0.0] * 1024
    for axis, value in parts:
        vector[axis] = value
    return vector


PRINTER, MFA, ELSEWHERE = 1, 2, 3
_refused = iter(range(1, 100))


def refused_ticket(user: User, subject: str, vector: list[float], *, days_ago: int = 2) -> Ticket:
    n = next(_refused)
    ticket = Ticket.objects.create(
        public_id=f"TKT-2026-{n:06d}",
        reporter=user,
        subject_masked=subject,
        body_masked=subject,
        pii_level="routine",
        status="pending_review",
    )
    Ticket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    ticket.store_embedding(vector, "test")
    RoutingDecision.objects.create(
        ticket=ticket,
        branch="hitl",
        reason_code=ReasonCode.RETRIEVAL_FLOOR.value,
        reason_detail="",
        thresholds_used={},
    )
    return ticket


def page_with_chunk(slug: str, vector: list[float]) -> KbArticle:
    article = KbArticle.objects.create(slug=slug, title=slug, body=slug, category="other")
    KbChunk.objects.create(
        article=article, chunk_index=0, content=slug, token_count=1, embedding=vector
    )
    return article


@pytest.fixture
def refused_six(employee_user) -> list[Ticket]:
    """The six refused tickets in F6 §g, and the two nearest live pages."""
    page_with_chunk(
        "workspaces-user.client_troubleshooting",
        unit((PRINTER, 0.41), (ELSEWHERE, math.sqrt(1 - 0.41**2))),
    )
    page_with_chunk(
        "iam.id_credentials_mfa_lost-or-broken",
        unit((MFA, 0.72), (ELSEWHERE + 1, math.sqrt(1 - 0.72**2))),
    )
    printer = [
        "Không in được ra máy in tầng 5 sau khi đổi mật khẩu",
        "Printer HP tầng 5 báo offline",
        "Máy in tầng 5 không nhận lệnh in từ laptop [EMPLOYEE_CODE_1]",
    ]
    mfa = [
        "Mất thiết bị MFA, không đăng nhập được AWS console",
        "Lost my MFA phone, cannot sign in to the IAM user",
        "Điện thoại có app MFA bị hỏng màn hình",
    ]
    return [
        refused_ticket(employee_user, s, unit((PRINTER, 0.99), (500 + i, 0.14)))
        for i, s in enumerate(printer)
    ] + [
        refused_ticket(employee_user, s, unit((MFA, 0.99), (600 + i, 0.14)))
        for i, s in enumerate(mfa)
    ]


class TestGaps:
    def test_the_gap_report_separates_gaps_from_updates(self, refused_six, team):
        """AC-F6-06 (BR-F6-07, BR-F6-08)."""
        report = kb_gaps.build()

        clusters = {c.label: c for c in report.clusters.select_related("nearest_article")}
        assert report.tickets_considered == 6
        assert set(clusters) == {"gap", "update"}
        assert clusters["gap"].size == 3
        gap, update = clusters["gap"].nearest_article, clusters["update"].nearest_article
        assert gap is not None and gap.slug == "workspaces-user.client_troubleshooting"
        assert clusters["update"].size == 3
        assert update is not None and update.slug == "iam.id_credentials_mfa_lost-or-broken"
        assert clusters["update"].nearest_similarity == pytest.approx(0.72, abs=0.02)
        assert Message.objects.filter(user=team["mai"], event="kb.gaps_ready").exists()

    def test_only_refused_or_wrong_kb_tickets_count(self, refused_six, employee_user, team):
        """BR-F6-07: a ticket routed for any other reason is not a gap; a wrong KB verdict is."""
        other = refused_ticket(employee_user, "Máy in tầng 5", unit((PRINTER, 1.0)))
        RoutingDecision.objects.filter(ticket=other).update(reason_code="category_low_confidence")
        wrong = refused_ticket(employee_user, "Máy in tầng 5 kẹt giấy", unit((PRINTER, 1.0)))
        RoutingDecision.objects.filter(ticket=wrong).update(reason_code="category_low_confidence")
        item = ReviewItem.objects.create(ticket=wrong, queue="low_confidence")
        ReviewDecision.objects.create(
            review_item=item, reviewer=team["tech"], kb_verdict="wrong", time_spent_sec=1
        )

        report = kb_gaps.build()

        assert report.tickets_considered == 7
        gap = report.clusters.get(label="gap")
        assert wrong in gap.tickets.all() and other not in gap.tickets.all()

    def test_tickets_outside_the_window_are_ignored(self, employee_user, settings):
        days = settings.THRESHOLDS.kb_gaps.window_days + 2
        for _ in range(3):
            refused_ticket(employee_user, "cũ", unit((PRINTER, 1.0)), days_ago=days)

        assert kb_gaps.build().tickets_considered == 0

    def test_a_rerun_replaces_the_report(self, refused_six):
        first = kb_gaps.build()
        old = set(first.clusters.values_list("id", flat=True))
        second = kb_gaps.build()

        assert second.pk == first.pk
        assert second.clusters.count() == 2
        assert not KbGapCluster.objects.filter(id__in=old).exists()

    def test_a_dismissed_topic_is_hidden_from_later_reports(self, refused_six, clients):
        """UC-F6-06 2a."""
        gap = kb_gaps.build().clusters.get(label="gap")

        refused = clients["mai"].post(
            f"/api/kb/gaps/{gap.id}/dismiss", {"reason": ""}, content_type="application/json"
        )
        assert refused.status_code == 422
        dismissed = clients["mai"].post(
            f"/api/kb/gaps/{gap.id}/dismiss",
            {"reason": "ngoài phạm vi IT"},
            content_type="application/json",
        )
        assert dismissed.json()["state"] == "dismissed"
        assert AuditLog.objects.filter(event="kb_gap_dismissed").count() == 1

        same_day = kb_gaps.build()
        assert sorted(c.state for c in same_day.clusters.all()) == ["dismissed", "open"]
        week = timedelta(days=7)
        KbGapReport.objects.update(
            window_start=F("window_start") - week, window_end=F("window_end") - week
        )
        next_week = kb_gaps.build()
        assert next_week.pk != same_day.pk
        assert [c.label for c in next_week.clusters.all()] == ["update"]
        assert "ngoài phạm vi IT" not in str(clients["mai"].get("/api/kb/gaps").json())

    def test_a_draft_started_from_a_gap_marks_it_drafted(self, refused_six, clients):
        gap = kb_gaps.build().clusters.get(label="gap")

        made = draft(
            clients["mai"],
            kind="create",
            slug="printer-floor5-hp",
            title="Máy in tầng 5",
            body="Khởi động lại máy in.",
            category="hardware",
            gap_cluster_id=str(gap.id),
        )

        assert made.json()["gap_cluster_id"] == str(gap.id)
        shown = clients["mai"].get("/api/kb/gaps").json()
        drafted = next(c for c in shown["clusters"] if c["id"] == str(gap.id))
        assert (drafted["state"], drafted["draft_id"]) == ("drafted", made.json()["id"])
        assert {t["public_id"] for t in drafted["tickets"]} == {
            t.public_id for t in refused_six[:3]
        }
