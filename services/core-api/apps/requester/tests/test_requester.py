"""The requester's tickets (F3): what goes wrong quietly here is another person's ticket shown, a
reply stored before masking, a reopen or rating outside its window, or a stale wait never closed."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditLog
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.vocabulary import FailureCode
from apps.metrics.utils import quality_metrics
from apps.requester.tests.conftest import (
    auto_replied,
    move,
    notices,
    reported,
    resolved,
    status,
    with_support,
)
from apps.requester.utils.tickets import requester_tickets
from apps.review.models import EvalCandidate, ReviewItem
from apps.sla.models import Clock as SlaClock
from apps.tickets.models import Ticket, TicketComment, TicketRating, TicketSource

pytestmark = pytest.mark.django_db


def reply(client, public_id: str, body: str):
    return client.post(
        f"/api/requester/tickets/{public_id}/replies",
        {"body": body},
        content_type="application/json",
    )


def reopen(client, public_id: str, reason: str):
    return client.post(
        f"/api/requester/tickets/{public_id}/reopen",
        {"reason": reason},
        content_type="application/json",
    )


def rate(client, public_id: str, score: int, comment: str | None = None):
    return client.put(
        f"/api/requester/tickets/{public_id}/rating",
        {"score": score, "comment": comment},
        content_type="application/json",
    )


def waiting_ticket(desk, clock):
    """TKT … assigned to khoa.lv, in progress, then waiting on lan.nt."""
    people = desk.people
    ticket = with_support(people["lan"], people["khoa"])
    move(ticket, "in_progress", people["khoa"])
    clock.set(2026, 10, 26, 10, 0)
    return move(ticket, "waiting_on_requester", people["khoa"])


class TestMyTickets:
    def test_form_and_chat_tickets_both_appear_open_first(self, desk, clock, api_as):
        """AC-F3-05."""
        lan = desk.people["lan"]
        form = with_support(lan, public_id="TKT-2026-000412")
        chat = with_support(lan, public_id="TKT-2026-000432", source=TicketSource.CHAT.value)
        done = resolved(lan, clock, days_ago=2, public_id="TKT-2026-000431")

        body = api_as(lan).get("/api/requester/tickets").json()

        assert {r["public_id"] for r in body["open"]} == {form.public_id, chat.public_id}
        assert [r["public_id"] for r in body["recent"]] == [done.public_id]
        assert body["recent"][0]["status_label"] == "Đã giải quyết"
        assert body["recent"][0]["can_reopen_until"] is not None

    def test_a_ticket_completed_before_the_list_window_is_left_for_xem_them(
        self, desk, clock, api_as
    ):
        lan = desk.people["lan"]
        old = resolved(lan, clock, days_ago=40)

        first = api_as(lan).get("/api/requester/tickets").json()
        assert first["recent"] == []
        assert first["more_before"] is not None

        more = api_as(lan).get("/api/requester/tickets", {"before": first["more_before"]}).json()
        assert [r["public_id"] for r in more["recent"]] == [old.public_id]

    def test_someone_elses_ticket_is_not_found(self, desk, api_as):
        """BR-F3-04: a 404, so it doesn't say the ticket exists."""
        theirs = with_support(desk.people["khoa"])
        client = api_as(desk.people["lan"])

        assert client.get(f"/api/requester/tickets/{theirs.public_id}").status_code == 404
        assert reply(client, theirs.public_id, "xin chào").status_code == 404
        assert [r["public_id"] for r in client.get("/api/requester/tickets").json()["open"]] == []

    def test_a_renamed_workflow_status_keeps_the_requester_label(self, desk, api_as):
        """AC-F3-12 (BR-F3-05)."""
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        in_progress = status("in_progress")
        in_progress.name = "Đang cấp quyền"
        in_progress.save(update_fields=["name"])
        ticket = move(with_support(lan, khoa, public_id="TKT-2026-000412"), "in_progress", khoa)

        row = api_as(lan).get("/api/requester/tickets").json()["open"][0]

        assert row["public_id"] == ticket.public_id
        assert row["status_label"] == "Đang xử lý"

    def test_the_label_follows_the_requesters_language(self, desk, clock, api_as):
        lan = desk.people["lan"]
        lan.language = "en"
        lan.save(update_fields=["language"])
        waiting_ticket(desk, clock)

        row = api_as(lan).get("/api/requester/tickets").json()["open"][0]

        assert row["status_label"] == "Waiting for you"
        assert row["sla_paused"] is True
        assert row["resolution_due_at"] is None


class TestReply:
    def test_reply_resumes_the_sla_and_tells_the_assignee(self, desk, clock, api_as):
        """AC-F3-06 (BR-F3-07)."""
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = waiting_ticket(desk, clock)
        clock.set(2026, 10, 26, 11, 0)

        response = reply(
            api_as(lan), ticket.public_id, "Em gửi log ạ: user lan.nt@congty.vn lỗi ở bước TLS"
        )

        assert response.status_code == 200
        stored = TicketComment.objects.get(ticket=ticket, author=lan)
        assert stored.body_masked == "Em gửi log ạ: user [EMAIL_1] lỗi ở bước TLS"
        ticket.refresh_from_db()
        assert ticket.status == "in_progress"
        resolution = SlaClock.objects.get(ticket=ticket, kind="resolution")
        assert resolution.state == "running"
        assert len(notices(khoa, "ticket.requester_replied")) == 1

    def test_reply_masked_before_store(self, desk, clock, api_as):
        """BR-F3-06: no raw value reaches a comment row."""
        lan = desk.people["lan"]
        ticket = waiting_ticket(desk, clock)

        reply(api_as(lan), ticket.public_id, "Liên hệ lan.nt@congty.vn hoặc 0912345678")

        bodies = " ".join(TicketComment.objects.values_list("body_masked", flat=True))
        assert "lan.nt@congty.vn" not in bodies
        assert "0912345678" not in bodies
        ticket.refresh_from_db()
        assert "[EMAIL_1]" in ticket.pii_map

    def test_a_reply_with_a_password_is_contained(self, desk, clock, api_as):
        """AC-F3-07."""
        lan = desk.people["lan"]
        ticket = waiting_ticket(desk, clock)

        body = reply(api_as(lan), ticket.public_id, "mật khẩu: Abc@12345").json()

        stored = TicketComment.objects.get(ticket=ticket, author=lan)
        assert "[PASSWORD_1]" in stored.body_masked
        assert "Abc@12345" not in stored.body_masked
        assert AuditLog.objects.filter(event="security_alert", ticket_id=ticket.id).count() == 1
        ticket.refresh_from_db()
        assert ticket.pii_level == "critical"
        assert body["credential_masked"] is True

    def test_reply_mask_failed_hidden_and_queued(self, desk, clock, api_as, ner_fails):
        """UC-F3-03 3y: staff never read it until a reviewer shows it."""
        lan = desk.people["lan"]
        ticket = waiting_ticket(desk, clock)

        body = reply(api_as(lan), ticket.public_id, "Tên em là Nguyễn Thị Lan").json()

        stored = TicketComment.objects.get(ticket=ticket, author=lan)
        assert stored.hidden_for_review is True
        assert body["state"] == "checking"
        assert body["body_masked"] == ""
        item = ReviewItem.objects.get(comment=stored)
        assert item.queue == "mask_failed"
        staff = api_as(desk.people["khoa"]).get(f"/api/tickets/{ticket.public_id}/comments").json()
        held = next(c for c in staff if c["id"] == str(stored.id))
        assert held["body_masked"] == ""
        assert held["hidden_for_review"] is True

    def test_a_held_reply_shown_by_a_reviewer_reaches_staff(self, desk, clock, api_as, ner_fails):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = waiting_ticket(desk, clock)
        reply(api_as(lan), ticket.public_id, "Tên em là Nguyễn Thị Lan")
        item = ReviewItem.objects.get(ticket=ticket, comment__isnull=False)

        refused = api_as(khoa).post(
            f"/api/review/items/{item.id}/decide",
            {"action_taken": "approve", "time_spent_sec": 1},
            content_type="application/json",
        )
        assert refused.status_code == 422

        shown = api_as(khoa).post(
            f"/api/review/items/{item.id}/comment-decision",
            {"choice": "show"},
            content_type="application/json",
        )

        assert shown.status_code == 200
        assert shown.json()["state"] == "resolved"
        assert item.comment is not None
        item.comment.refresh_from_db()
        assert item.comment.hidden_for_review is False
        assert len(notices(khoa, "ticket.requester_replied")) == 1

    def test_a_discarded_reply_stays_hidden_and_the_requester_sees_it_was(
        self, desk, clock, api_as, ner_fails
    ):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = waiting_ticket(desk, clock)
        reply(api_as(lan), ticket.public_id, "Tên em là Nguyễn Thị Lan")
        item = ReviewItem.objects.get(ticket=ticket, comment__isnull=False)

        api_as(khoa).post(
            f"/api/review/items/{item.id}/comment-decision",
            {"choice": "discard"},
            content_type="application/json",
        )

        thread = api_as(lan).get(f"/api/requester/tickets/{ticket.public_id}").json()["thread"]
        assert [c["state"] for c in thread if c["mine"]] == ["discarded"]
        assert notices(khoa, "ticket.requester_replied") == []

    def test_a_reply_on_a_closed_ticket_is_ticket_closed(self, desk, clock, api_as):
        """UC-F3-03 1x."""
        lan = desk.people["lan"]
        done = resolved(lan, clock, days_ago=1)

        response = reply(api_as(lan), done.public_id, "Vẫn lỗi")

        assert response.status_code == 409
        assert response.json()["code"] == "ticket_closed"
        assert not TicketComment.objects.filter(ticket=done).exists()

    def test_a_reply_while_the_question_is_in_triage_is_refused(self, desk, api_as):
        lan = desk.people["lan"]
        ticket = reported(lan)

        response = reply(api_as(lan), ticket.public_id, "Vẫn lỗi")

        assert response.status_code == 409
        assert response.json()["code"] == "ticket_in_triage"

    def test_a_reply_the_workflow_refuses_keeps_the_comment(self, desk, clock, api_as, monkeypatch):
        """BR-F3-07: the comment stays and the assignee is still told."""
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = waiting_ticket(desk, clock)

        def refuse(*a, **kw):
            raise LifecycleError(422, FailureCode.TRANSITION_NOT_ALLOWED, "no way back")

        monkeypatch.setattr("apps.lifecycle.utils.engine.lifecycle.automatic_move", refuse)

        assert reply(api_as(lan), ticket.public_id, "Em gửi log ạ").status_code == 200

        ticket.refresh_from_db()
        assert ticket.status == "waiting_on_requester"
        assert TicketComment.objects.filter(ticket=ticket, author=lan).count() == 1
        assert AuditLog.objects.filter(
            event="requester_reply_move_refused", ticket_id=ticket.id
        ).exists()
        assert len(notices(khoa, "ticket.requester_replied")) == 1

    def test_a_wait_entered_from_a_pipeline_status_resumes_in_progress(self, desk, api_as):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = move(with_support(lan, khoa), "waiting_on_requester", khoa)

        reply(api_as(lan), ticket.public_id, "Em gửi log ạ")

        ticket.refresh_from_db()
        assert ticket.status == "in_progress"


class TestReopen:
    def test_reopen_autoreply_creates_eval_candidate(self, desk, clock, api_as):
        """AC-F3-08 (BR-F3-08, BR-F3-09)."""
        lan = desk.people["lan"]
        ticket = auto_replied(lan, clock, days_ago=2)

        response = reopen(api_as(lan), ticket.public_id, "Vẫn lỗi sau khi cài lại client")

        assert response.json() == {"reopened": True, "new_ticket": None}
        ticket.refresh_from_db()
        assert ticket.status == "reopened"
        assert ticket.reopened_count == 1
        candidate = EvalCandidate.objects.get(ticket=ticket)
        assert candidate.source == "reopen"
        assert candidate.ai_prediction["kb_slug"] == "client-vpn-user.windows"
        assert quality_metrics()["reopen_rate_after_autoreply"] == 1.0

    def test_a_reopen_resumes_the_old_resolution_clock(self, desk, clock, api_as):
        """AC-F1-11 (BR-F1-13): elapsed time is kept and no response clock is added."""
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = move(with_support(lan, khoa), "in_progress", khoa)  # Mon 09:00
        clock.set(2026, 10, 26, 10, 0)
        move(ticket, "resolved", khoa)
        clock.set(2026, 10, 27, 9, 0)

        reopen(api_as(lan), ticket.public_id, "Vẫn lỗi")

        resolution = SlaClock.objects.get(ticket=ticket, kind="resolution")
        assert resolution.state == "running"
        assert resolution.elapsed_business_sec == 60 * 60
        response = SlaClock.objects.filter(ticket=ticket, kind="response")
        assert [c.state for c in response] == ["met"]

    def test_reopen_after_window_creates_linked_ticket(self, desk, clock, api_as, enqueued):
        """AC-F3-09."""
        lan = desk.people["lan"]
        old = resolved(lan, clock, days_ago=9, public_id="TKT-2026-000431")

        body = reopen(api_as(lan), old.public_id, "Lại lỗi TLS như lần trước").json()

        assert body["reopened"] is False
        new = Ticket.objects.get(public_id=body["new_ticket"])
        assert new.reopened_from == old
        assert "Liên quan đến TKT-2026-000431" in new.body_masked
        old.refresh_from_db()
        assert old.status == "resolved"
        assert old.reopened_count == 0

    def test_reopen_without_a_reason_is_refused(self, desk, clock, api_as):
        lan = desk.people["lan"]
        done = resolved(lan, clock, days_ago=1)

        response = reopen(api_as(lan), done.public_id, "   ")

        assert response.status_code == 422
        assert response.json()["code"] == "reason_required"

    def test_an_open_ticket_cannot_be_reopened(self, desk, api_as):
        lan = desk.people["lan"]
        ticket = with_support(lan)

        response = reopen(api_as(lan), ticket.public_id, "Vẫn lỗi")

        assert response.status_code == 409
        assert response.json()["code"] == "not_resolved"

    def test_the_reopen_task_refuses_an_open_ticket(self, desk):
        """`reopen_ticket` used to reopen whatever it was handed."""
        ticket = with_support(desk.people["lan"])

        with pytest.raises(Exception, match="still open"):
            requester_tickets.reopen_now(ticket.id, None)
        ticket.refresh_from_db()
        assert ticket.reopened_count == 0

    def test_a_reopened_ticket_goes_back_to_its_eligible_assignee(self, desk, clock, api_as):
        lan, khoa, duc = desk.people["lan"], desk.people["khoa"], desk.people["duc"]
        done = resolved(lan, clock, days_ago=1, assignee=khoa)

        reopen(api_as(lan), done.public_id, "Vẫn lỗi")

        done.refresh_from_db()
        assert done.assigned_to == khoa
        assert len(notices(khoa, "ticket.reopened")) == 1
        assert len(notices(duc, "ticket.reopened")) == 1

    def test_a_reopened_ticket_whose_assignee_left_goes_by_strategy(self, desk, clock, api_as):
        lan, vy = desk.people["lan"], desk.people["vy"]
        done = resolved(lan, clock, days_ago=1, assignee=vy)

        reopen(api_as(lan), done.public_id, "Vẫn lỗi")

        done.refresh_from_db()
        assert done.assigned_to is not None
        assert done.assigned_to != vy


class TestRating:
    def test_one_rating_per_resolution_low_alerts_the_lead(self, desk, clock, api_as):
        """AC-F3-10 (BR-F3-10)."""
        lan, duc = desk.people["lan"], desk.people["duc"]
        ticket = resolved(lan, clock, days_ago=1, public_id="TKT-2026-000432")

        assert rate(api_as(lan), ticket.public_id, 2, "Phải chờ lâu").status_code == 200
        assert rate(api_as(lan), ticket.public_id, 1, "Phải chờ rất lâu").status_code == 200

        rating = TicketRating.objects.get(ticket=ticket)
        assert (rating.resolution_seq, rating.score) == (1, 1)
        assert len(notices(duc, "ticket.rated_low")) == 1
        ticket.refresh_from_db()
        assert ticket.status == "resolved"

    def test_a_low_rated_auto_reply_becomes_an_eval_candidate(self, desk, clock, api_as):
        lan = desk.people["lan"]
        ticket = auto_replied(lan, clock, days_ago=1)

        rate(api_as(lan), ticket.public_id, 1)
        rate(api_as(lan), ticket.public_id, 2)

        assert EvalCandidate.objects.filter(ticket=ticket, source="low_rating").count() == 1

    def test_a_good_rating_tells_nobody(self, desk, clock, api_as):
        lan, duc = desk.people["lan"], desk.people["duc"]
        ticket = resolved(lan, clock, days_ago=1)

        rate(api_as(lan), ticket.public_id, 5, "Anh hỗ trợ nhanh")

        assert notices(duc, "ticket.rated_low") == []
        assert TicketRating.objects.get(ticket=ticket).comment_masked == "Anh hỗ trợ nhanh"

    def test_a_rating_after_the_window_is_refused(self, desk, clock, api_as):
        lan = desk.people["lan"]
        ticket = resolved(lan, clock, days_ago=8)

        response = rate(api_as(lan), ticket.public_id, 4)

        assert response.status_code == 409
        assert response.json()["code"] == "rating_window_closed"

    @pytest.mark.parametrize("score", [0, 6])
    def test_a_score_outside_1_to_5_is_refused(self, desk, clock, api_as, score):
        lan = desk.people["lan"]
        ticket = resolved(lan, clock, days_ago=1)

        response = rate(api_as(lan), ticket.public_id, score)

        assert response.status_code == 422
        assert response.json()["code"] == "bad_score"

    def test_a_new_resolution_takes_a_new_rating(self, desk, clock, api_as):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = resolved(lan, clock, days_ago=1, assignee=khoa)
        rate(api_as(lan), ticket.public_id, 3)
        reopen(api_as(lan), ticket.public_id, "Vẫn lỗi")
        move(Ticket.objects.get(pk=ticket.pk), "resolved", khoa)

        rate(api_as(lan), ticket.public_id, 5)

        assert sorted(
            TicketRating.objects.filter(ticket=ticket).values_list("resolution_seq", "score")
        ) == [
            (1, 3),
            (2, 5),
        ]


class TestAutoClose:
    def test_stale_waits_close_themselves(self, desk, clock):
        """AC-F3-11 (BR-F3-11)."""
        lan = desk.people["lan"]
        ticket = waiting_ticket(desk, clock)  # Mon 26 Oct 10:00

        clock.set(2026, 10, 30, 18, 0)  # four working days after Monday
        assert requester_tickets.sweep()["closed"] == 0

        clock.set(2026, 11, 2, 18, 0)  # Tue … Fri and Mon: five
        assert requester_tickets.sweep()["closed"] == 1
        assert requester_tickets.sweep()["closed"] == 0

        ticket.refresh_from_db()
        assert ticket.status == "resolved"
        system = TicketComment.objects.get(ticket=ticket, author_kind="system")
        assert system.body_masked == "Đóng tự động do không có phản hồi"
        assert len(notices(lan, "ticket.resolved")) == 1
        assert AuditLog.objects.filter(event="ticket_auto_closed", ticket_id=ticket.id).count() == 1

    def test_an_auto_close_the_workflow_refuses_is_audited_once(self, desk, clock, monkeypatch):
        ticket = waiting_ticket(desk, clock)

        def refuse(*a, **kw):
            raise LifecycleError(422, FailureCode.TRANSITION_NOT_ALLOWED, "no way to resolved")

        monkeypatch.setattr("apps.lifecycle.utils.engine.lifecycle.automatic_move", refuse)
        clock.set(2026, 11, 9, 18, 0)
        requester_tickets.sweep()
        requester_tickets.sweep()

        assert (
            AuditLog.objects.filter(event="ticket_auto_close_refused", ticket_id=ticket.id).count()
            == 1
        )
        ticket.refresh_from_db()
        assert ticket.status == "waiting_on_requester"


class TestStaffComments:
    def comment(self, client, ticket, **body):
        return client.post(
            f"/api/tickets/{ticket.public_id}/comments",
            {"visibility": "public", **body},
            content_type="application/json",
        )

    def test_a_public_comment_meets_the_response_and_tells_the_requester(self, desk, api_as):
        """UC-F3-06: the first public comment meets F1's response clock (AC-F1-10)."""
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = with_support(lan, khoa)

        response = self.comment(
            api_as(khoa), ticket, body="Chị cho em xin ảnh lỗi trong AWS VPN Client > Show logs ạ"
        )

        assert response.status_code == 200
        assert SlaClock.objects.get(ticket=ticket, kind="response").state == "met"
        told = notices(lan, "ticket.public_comment")
        assert len(told) == 1
        assert "Show logs" in told[0].body

    def test_a_rebuild_keeps_a_public_comment_as_the_response(self, desk, clock, api_as):
        """FR-F1-015: replaying the ticket counts the staff reply as its response."""
        from apps.sla.utils.clocks import sla_clocks

        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = with_support(lan, khoa)
        clock.set(2026, 10, 26, 9, 12)
        self.comment(api_as(khoa), ticket, body="Chị gửi log giúp em")
        clock.set(2026, 10, 26, 11, 0)

        sla_clocks.rebuild(ticket)

        response = SlaClock.objects.get(ticket=ticket, kind="response")
        assert response.state == "met"
        assert response.met_at == clock.set(2026, 10, 26, 9, 12)

    def test_a_comment_can_also_put_the_ticket_waiting_on_the_requester(self, desk, api_as):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = move(with_support(lan, khoa), "in_progress", khoa)

        self.comment(api_as(khoa), ticket, body="Chị gửi log giúp em", move_to_waiting=True)

        ticket.refresh_from_db()
        assert ticket.status == "waiting_on_requester"
        assert SlaClock.objects.get(ticket=ticket, kind="resolution").state == "paused"
        assert len(notices(lan, "ticket.status_changed")) == 1

    def test_an_internal_note_never_reaches_the_requester(self, desk, api_as):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = with_support(lan, khoa)

        self.comment(
            api_as(khoa), ticket, body="Có thể do firewall chi nhánh", visibility="internal"
        )

        thread = api_as(lan).get(f"/api/requester/tickets/{ticket.public_id}").json()["thread"]
        assert thread == []
        assert notices(lan, "ticket.public_comment") == []
        assert SlaClock.objects.get(ticket=ticket, kind="response").state == "running"

    def test_a_stale_version_is_refused(self, desk, api_as):
        khoa = desk.people["khoa"]
        ticket = with_support(desk.people["lan"], khoa)

        response = self.comment(api_as(khoa), ticket, body="xin log", expected_version=0)

        assert response.status_code == 409
        assert response.json()["code"] == "version_conflict"
        assert not TicketComment.objects.filter(ticket=ticket).exists()

    def test_a_requester_cannot_use_the_staff_endpoint(self, desk, api_as):
        lan = desk.people["lan"]
        ticket = with_support(lan)

        assert self.comment(api_as(lan), ticket, body="hello").status_code == 403


class TestStatusNotices:
    def test_the_requester_is_told_once_when_support_receives_the_ticket(self, desk):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = with_support(lan, khoa)
        move(ticket, "in_progress", khoa)

        received = notices(lan, "ticket.received")
        assert len(received) == 1
        assert received[0].link.endswith(f"/tickets/{ticket.public_id}")
        assert received[0].link.startswith("http")

    def test_the_requester_is_told_once_when_the_ticket_is_resolved(self, desk):
        lan, khoa = desk.people["lan"], desk.people["khoa"]
        ticket = move(with_support(lan, khoa), "resolved", khoa)
        move(ticket, "closed", khoa)

        assert len(notices(lan, "ticket.resolved")) == 1
        assert notices(lan, "ticket.status_changed") == []
