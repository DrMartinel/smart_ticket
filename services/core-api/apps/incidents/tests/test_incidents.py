"""Mass incidents (F7): what goes wrong quietly here is two outages merging into one incident, a
ticket counted twice, an incident manager's confirm teaching the eval set, a linked ticket
auto-replied, a requester told forty times, or one refused ticket stopping the rest."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.audit.models import AuditLog
from apps.incidents.models import IncidentLink
from apps.incidents.tests.conftest import PRINTER, VPN, Engine, arrive, near
from apps.incidents.utils.incidents import IncidentError, incidents
from apps.lifecycle.request_schema import StatusIn
from apps.lifecycle.tests.conftest import StrictFlow, put_in
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.vocabulary import StatusKind
from apps.notifications.models import Message
from apps.review.models import EvalCandidate, ReviewDecision, ReviewItem
from apps.rollout.testing import all_live
from apps.sla.models import Clock, ClockKind
from apps.sla.tests.conftest import submitted, vn
from apps.tickets.models import Incident, RoutingDecision, Ticket, TicketComment

pytestmark = pytest.mark.django_db


def outage(desk, engine: Engine, axis: int = VPN, count: int = 5) -> tuple[Incident, list[Ticket]]:
    """`count` similar tickets from different requesters: the detector proposes an incident."""
    reporters = [desk["lan"], desk["binh"], desk["chi"]]
    tickets = [arrive(reporters[n % 3], engine, axis) for n in range(count)]
    incident = Incident.objects.get(links__ticket=tickets[-1])
    return incident, tickets


def confirmed(desk, engine: Engine, count: int = 5) -> tuple[Incident, list[Ticket]]:
    incident, tickets = outage(desk, engine, count=count)
    incidents.confirm(incident.public_id, desk["duc"], "VPN công ty gián đoạn", "network", "VPN")
    incident.refresh_from_db()
    return incident, tickets


def resolution_clock(ticket: Ticket) -> Clock:
    return Clock.objects.get(ticket=ticket, kind=ClockKind.RESOLUTION.value)


def say(desk, incident: Incident, text: str = "VPN đang gián đoạn, đang xử lý.", **kw):
    return incidents.broadcast(incident.public_id, desk["duc"], body_vi=text, **kw)


class TestDetection:
    def test_unrelated_outages_get_separate_incidents(self, desk, engine, clock):
        """AC-F7-01 (BR-F7-01, BR-F7-02): defect 1, every incident keyed to `other`."""
        vpn, _ = outage(desk, engine, VPN)
        printers = [arrive(desk["lan"], engine, PRINTER) for _ in range(6)]

        assert Incident.objects.count() == 2
        printer_incident = Incident.objects.exclude(pk=vpn.pk).get()
        assert printer_incident.status == "proposed"
        assert {t.incident_id for t in printers[4:]} == {printer_incident.id}
        assert not IncidentLink.objects.filter(incident=vpn, ticket__in=printers).exists()

    def test_ticket_count_counts_each_ticket_once(self, desk, engine, clock):
        """Defect 2: the triggering ticket was in `similar` as well as the `+ 1`."""
        incident, tickets = outage(desk, engine)

        assert incident.ticket_count == 5
        assert incident.detector["count"] == 5
        assert IncidentLink.objects.filter(incident=incident).count() == 5

    def test_a_ticket_matching_the_centroid_joins_without_the_detector(self, desk, engine, clock):
        incident, _ = outage(desk, engine)

        late = arrive(desk["lan"], engine, VPN)

        assert late.incident_id == incident.id
        assert IncidentLink.objects.get(ticket=late).linked_by == "matcher"
        assert Incident.objects.count() == 1

    def test_proposing_tells_incident_managers(self, desk, engine, clock):
        incident, _ = outage(desk, engine)

        assert Message.objects.filter(user=desk["duc"], event="incident.proposed").exists()
        assert AuditLog.objects.filter(event="incident_proposed").count() == 1
        assert incident.status == "proposed" and incident.category is None

    def test_ticket_count_comes_from_the_links(self, desk, clock):
        """AC-F7-09 (BR-F7-09)."""
        incident = Incident.objects.create(
            public_id="INC-2026-0007", title="VPN", severity="high", detected_by="human"
        )
        tickets = [submitted(desk["lan"]) for _ in range(24)]
        for ticket in tickets[:23]:
            incidents.link(incident, ticket, "duc.tm", None)

        incidents.unlink(incident.public_id, tickets[0].public_id, desk["duc"], "khác sự cố")
        incidents.link(incident, tickets[23], "duc.tm", None)
        incidents.link(incident, tickets[23], "duc.tm", None)

        incident.refresh_from_db()
        assert incident.ticket_count == 23


class TestConfirmAndDismiss:
    def test_confirm_approves_without_eval_candidates(self, desk, engine, clock):
        """AC-F7-02 (BR-F7-03)."""
        incident, tickets = outage(desk, engine)
        items = ReviewItem.objects.filter(ticket__in=tickets)
        assert items.count() == 5 and {i.state for i in items} == {"pending"}
        routed = list(RoutingDecision.objects.filter(ticket__in=tickets).values())

        incidents.confirm(incident.public_id, desk["duc"], "VPN công ty gián đoạn", "network", "")

        decided = {
            (d.review_item.state, d.action_taken, d.reviewer.username)
            for d in ReviewDecision.objects.filter(review_item__in=items)
        }
        assert decided == {("resolved", "approve", "duc.tm")}
        assert len(ReviewDecision.objects.filter(review_item__in=items)) == 5
        assert not EvalCandidate.objects.exists()
        assert list(RoutingDecision.objects.filter(ticket__in=tickets).values()) == routed
        incident.refresh_from_db()
        assert (incident.status, incident.category) == ("confirmed", "network")

    def test_dismiss_returns_tickets_to_normal_review(self, desk, engine, clock):
        """AC-F7-06 (BR-F7-01)."""
        incident, tickets = outage(desk, engine)

        incidents.dismiss(incident.public_id, desk["duc"], "Trùng hợp, không cùng nguyên nhân")

        assert not IncidentLink.objects.active().filter(incident=incident).exists()
        assert not Ticket.objects.filter(pk__in=[t.pk for t in tickets], incident__isnull=False)
        assert set(
            ReviewItem.objects.filter(ticket__in=tickets).values_list("state", flat=True)
        ) == {"pending"}
        incident.refresh_from_db()
        assert (incident.status, incident.ticket_count) == ("dismissed", 0)

    def test_dismiss_needs_a_reason(self, desk, engine, clock):
        incident, _ = outage(desk, engine)

        with pytest.raises(IncidentError) as refused:
            incidents.dismiss(incident.public_id, desk["duc"], "  ")
        assert refused.value.code == "reason_required"

    def test_only_incident_managers_confirm(self, desk, engine, clock, api_as):
        incident, _ = outage(desk, engine)
        body = {"title": "VPN công ty gián đoạn", "category": "network"}

        refused = api_as(desk["huy"]).post(
            f"/api/incidents/{incident.public_id}/confirm", body, content_type="application/json"
        )
        done = api_as(desk["duc"]).post(
            f"/api/incidents/{incident.public_id}/confirm", body, content_type="application/json"
        )

        assert refused.status_code == 403
        assert done.status_code == 200 and done.json()["status"] == "confirmed"

    def test_confirming_twice_is_refused(self, desk, engine, clock):
        incident, _ = confirmed(desk, engine)

        with pytest.raises(IncidentError) as refused:
            incidents.confirm(incident.public_id, desk["duc"], "again", None, "")
        assert refused.value.code == "not_proposed"


class TestRouting:
    def test_linked_ticket_never_auto_replied(self, desk, engine, clock, settings):
        """AC-F7-07 (BR-F7-08): a linked ticket never reaches ai-engine, so no proposal can cite
        an approved page."""
        all_live(settings)
        incident, tickets = outage(desk, engine)
        late = arrive(desk["lan"], engine, VPN)

        for ticket in [*tickets[-1:], late]:
            decision = RoutingDecision.objects.get(ticket=ticket)
            assert (decision.branch, decision.reason_code) == ("escalate", "mass_incident")
        assert late.public_id not in engine.analysed
        assert not RoutingDecision.objects.filter(branch="auto_reply").exists()

    def test_late_joiner_sees_the_latest_update_at_once(
        self, desk, engine, clock, settings, api_as
    ):
        """AC-F7-04 (BR-F7-04, BR-F7-05)."""
        all_live(settings)
        incident, _ = confirmed(desk, engine)
        eta = vn(2026, 10, 23, 17, 30)
        say(desk, incident, eta=eta)
        newcomer = desk["chi"]

        late = arrive(newcomer, engine, VPN)

        assert late.incident_id == incident.id
        assert not ReviewItem.objects.filter(ticket=late).exists()
        assert TicketComment.objects.filter(ticket=late, broadcast__isnull=False).count() == 1
        banner = api_as(newcomer).get(f"/api/requester/tickets/{late.public_id}").json()["incident"]
        assert banner["title"] == "VPN công ty gián đoạn"
        assert banner["last_update"] == "VPN đang gián đoạn, đang xử lý."
        assert banner["eta"].startswith("2026-10-23T10:30")

    def test_in_shadow_mode_a_late_joiner_still_reaches_a_reviewer(
        self, desk, engine, clock, settings
    ):
        settings.SHADOW_MODE = True
        incident, _ = confirmed(desk, engine)

        late = arrive(desk["lan"], engine, VPN)

        assert ReviewItem.objects.filter(ticket=late, state="pending").exists()
        assert resolution_clock(late).state == "paused"


class TestBroadcast:
    def test_broadcast_once_per_requester(self, desk, engine, clock):
        """AC-F7-03 (BR-F7-05): lan.nt has two linked tickets."""
        incident, tickets = confirmed(desk, engine)
        lans = [t for t in tickets if t.reporter_id == desk["lan"].id]
        assert len(lans) == 2

        sent = say(desk, incident, eta=vn(2026, 10, 23, 17, 30))

        lan_notices = Message.objects.filter(user=desk["lan"], event="incident.broadcast")
        assert sorted(lan_notices.values_list("channel", flat=True)) == ["email", "in_app"]
        assert sent.requesters_count == 3
        for ticket in lans:
            (comment,) = TicketComment.objects.filter(ticket=ticket, broadcast=sent)
            assert (comment.author_kind, comment.visibility) == ("system", "public")

    def test_the_first_broadcast_meets_response_clocks(self, desk, engine, clock):
        incident, tickets = confirmed(desk, engine)

        say(desk, incident)

        states = Clock.objects.filter(ticket__in=tickets, kind=ClockKind.RESPONSE.value)
        assert set(states.values_list("state", flat=True)) == {"met"}

    def test_broadcast_text_is_masked(self, desk, engine, clock):
        incident, tickets = confirmed(desk, engine)

        sent = say(desk, incident, text="Gọi 0912345678 nếu cần hỗ trợ")

        assert "0912345678" not in sent.body_vi_masked
        assert not TicketComment.objects.filter(body_masked__contains="0912345678").exists()

    def test_a_masking_failure_sends_nothing(self, desk, engine, clock, monkeypatch):
        """BR-F7-05: never toward "no PII found"."""
        from apps.incidents.models import IncidentBroadcast
        from apps.tickets.utils.masking import NERError

        incident, _ = confirmed(desk, engine)

        async def ner_down(*a, **kw):
            raise NERError("ner down")

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", ner_down)
        with pytest.raises(IncidentError) as refused:
            say(desk, incident)

        assert refused.value.code == "mask_failed"
        assert not IncidentBroadcast.objects.exists()
        assert not Message.objects.filter(event="incident.broadcast").exists()

    def test_a_proposed_incident_cannot_broadcast(self, desk, engine, clock):
        incident, _ = outage(desk, engine)

        with pytest.raises(IncidentError) as refused:
            say(desk, incident)
        assert refused.value.code == "not_confirmed"

    def test_delivery_counts_per_broadcast(self, desk, engine, clock, api_as):
        incident, _ = confirmed(desk, engine)
        say(desk, incident)

        detail = api_as(desk["khoa"]).get(f"/api/incidents/{incident.public_id}").json()

        (shown,) = detail["broadcasts"]
        assert shown["delivery"]["requesters"] == 3
        assert len(detail["links"]) == 5


class TestResolve:
    def test_close_all_continues_after_refusal(self, desk, engine, clock, strict: StrictFlow):
        """AC-F7-05 (BR-F7-06): one ticket sits in a strict workflow with no way to `resolved`."""
        incident, tickets = confirmed(desk, engine, count=7)
        workflow_config.add_status(
            strict.workflow, StatusIn(name="Resolved", kind=StatusKind.COMPLETED)
        )
        stuck = put_in(tickets[3], strict.working)
        Ticket.objects.filter(pk=stuck.pk).update(assigned_to=desk["khoa"])

        result = incidents.resolve(
            incident.public_id, desk["duc"], "Đã thay chứng chỉ, VPN hoạt động lại.", True
        )

        assert len(result.closed) == 6
        assert result.failed == [{"ticket": stuck.public_id, "code": "transition_not_allowed"}]
        assert Message.objects.filter(
            user=desk["khoa"], event="incident.ticket_not_closed"
        ).exists()
        assert AuditLog.objects.filter(event="incident_ticket_closed").count() == 6
        for ticket in tickets:
            ticket.refresh_from_db()
        assert sum(t.resolved_at is not None for t in tickets) == 6

    def test_close_all_sends_no_per_ticket_resolved_notice(self, desk, engine, clock):
        incident, tickets = confirmed(desk, engine)

        incidents.resolve(incident.public_id, desk["duc"], "VPN hoạt động lại.", True)

        assert not Message.objects.filter(event="ticket.resolved").exists()
        assert Message.objects.filter(user=desk["lan"], event="incident.broadcast").exists()

    def test_resolve_needs_a_note(self, desk, engine, clock):
        incident, _ = confirmed(desk, engine)

        with pytest.raises(IncidentError) as refused:
            incidents.resolve(incident.public_id, desk["duc"], " ", True)
        assert refused.value.code == "reason_required"


class TestClocks:
    def test_linked_clock_paused_while_confirmed(self, desk, engine, clock):
        """AC-F7-10 (BR-F7-07)."""
        incident, tickets = outage(desk, engine)
        ticket = tickets[0]
        assert resolution_clock(ticket).state == "running"

        incidents.confirm(incident.public_id, desk["duc"], "VPN công ty gián đoạn", "network", "")
        assert resolution_clock(ticket).state == "paused"

        clock.now += timedelta(minutes=30)
        incidents.resolve(incident.public_id, desk["duc"], "VPN hoạt động lại.", False)
        assert resolution_clock(ticket).state == "running"

    def test_unlink_resumes_the_clock_and_returns_to_review(self, desk, engine, clock):
        """UC-F7-05 (BR-F7-07)."""
        incident, tickets = confirmed(desk, engine)
        ticket = tickets[0]

        incidents.unlink(incident.public_id, ticket.public_id, desk["duc"], "Không liên quan")

        assert resolution_clock(ticket).state == "running"
        assert ReviewItem.objects.filter(
            ticket=ticket, state="pending", queue="low_confidence"
        ).exists()

    def test_the_incident_has_its_own_p1_clock(self, desk, engine, clock):
        """AC-F7-08 (BR-F7-10): confirmed on a Saturday, counted 24×7."""
        clock.set(2026, 10, 24, 8, 50)
        incident, _ = outage(desk, engine)
        clock.set(2026, 10, 24, 8, 55)
        incidents.confirm(incident.public_id, desk["duc"], "VPN công ty gián đoạn", "network", "")
        incident.refresh_from_db()
        assert incident.target_resolve_at == vn(2026, 10, 24, 12, 55)

        clock.set(2026, 10, 24, 12, 56)
        assert incidents.sweep()["breached"] == 1
        assert incidents.sweep()["breached"] == 0
        assert Message.objects.filter(user=desk["huy"], event="incident.sla_breached").count() == 2


class TestApi:
    def test_declare_by_hand_is_confirmed(self, desk, engine, clock, api_as):
        """UC-F7-02."""
        ticket = arrive(desk["lan"], engine, VPN)

        made = api_as(desk["duc"]).post(
            "/api/incidents",
            {
                "title": "Mất kết nối VPN",
                "category": "network",
                "service": "VPN",
                "ticket_ids": [ticket.public_id],
                "broadcast": {"body_vi": "Đang kiểm tra VPN.", "eta_unknown": True},
            },
            content_type="application/json",
        )

        assert made.status_code == 201
        body = made.json()
        assert (body["status"], body["detected_by"], body["ticket_count"]) == (
            "confirmed",
            "human",
            1,
        )
        assert body["broadcasts"][0]["eta_unknown"] is True
        assert AuditLog.objects.filter(event="incident_declared").count() == 1

    def test_unlink_by_the_assignee_through_the_api(self, desk, engine, clock, api_as):
        incident, tickets = confirmed(desk, engine)
        Ticket.objects.filter(pk=tickets[0].pk).update(assigned_to=desk["khoa"])

        refused = api_as(desk["khoa"]).delete(
            f"/api/incidents/{incident.public_id}/links/{tickets[1].public_id}",
            {"reason": "khác"},
            content_type="application/json",
        )
        done = api_as(desk["khoa"]).delete(
            f"/api/incidents/{incident.public_id}/links/{tickets[0].public_id}",
            {"reason": "Không liên quan"},
            content_type="application/json",
        )

        assert refused.status_code == 403
        assert done.status_code == 204

    def test_requesters_cannot_read_incidents(self, desk, api_as):
        assert api_as(desk["lan"]).get("/api/incidents").status_code == 403

    def test_reopen_holds_clocks_again(self, desk, engine, clock):
        incident, tickets = confirmed(desk, engine)
        incidents.resolve(incident.public_id, desk["duc"], "VPN hoạt động lại.", False)
        assert resolution_clock(tickets[0]).state == "running"

        incidents.reopen(incident.public_id, desk["duc"], "Lỗi quay lại")

        assert resolution_clock(tickets[0]).state == "paused"

    def test_resolved_incidents_close_after_a_week(self, desk, engine, clock):
        incident, _ = confirmed(desk, engine)
        incidents.resolve(incident.public_id, desk["duc"], "VPN hoạt động lại.", True)

        clock.now += timedelta(days=8)
        assert incidents.sweep()["closed"] == 1

        incident.refresh_from_db()
        assert incident.status == "closed"


def test_near_vectors_are_similar_and_axes_are_not():
    from math import sqrt

    a, b, c = near(VPN), near(VPN), near(PRINTER)
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = sqrt(sum(x * x for x in a)) * sqrt(sum(x * x for x in b))
    assert dot / norm > 0.85
    assert sum(x * y for x, y in zip(a, c, strict=True)) == 0
