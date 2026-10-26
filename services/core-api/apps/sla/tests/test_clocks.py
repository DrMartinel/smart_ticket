"""SLA clocks driven by status events: start at handoff, pause, response, resolution, sweep (F1)."""

from __future__ import annotations

import json

from apps.audit.models import AuditLog
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.notifications.models import Message
from apps.review.models import ReviewItem
from apps.sla.models import Clock, ClockState, Policy, Rebuild
from apps.sla.tests.conftest import handed_off, move, submitted, vn
from apps.sla.utils.clocks import SlaClocks, sla_clocks
from apps.sla.utils.config import sla_config
from apps.tickets.models import Incident, Ticket
from apps.tickets.utils.router import ReviewQueue

JSON = "application/json"


def clocks(ticket: Ticket) -> dict[str, Clock]:
    return {c.kind: c for c in Clock.objects.filter(ticket=ticket)}


def minutes(clock: Clock) -> int:
    return clock.elapsed_business_sec // 60


# ── starting ──


def test_clocks_start_at_handoff_not_at_submit(clock, people):
    """AC-F1-01: P3, response due Mon 10:00, resolution due Wed 15:30 (+07)."""
    ticket = submitted(people["lan"], public_id="TKT-2026-000418", category="hardware")
    clock.set(2026, 10, 23, 15, 30)

    lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)

    ticket.refresh_from_db()
    assert ticket.priority == "P3"
    both = clocks(ticket)
    assert both["response"].due_at == vn(2026, 10, 26, 10, 0)
    assert both["resolution"].due_at == vn(2026, 10, 28, 15, 30)
    assert both["resolution"].warn_at == vn(2026, 10, 28, 8, 22, 30)
    assert ticket.sla_due_at == vn(2026, 10, 28, 15, 30)
    assert AuditLog.objects.filter(event="sla_started").count() == 1


def test_no_clock_time_in_triage_statuses(clock, people):
    """BR-F1-01: time at `new` and `awaiting_requester` never counts."""
    ticket = submitted(people["lan"], category="hardware")
    lifecycle.system_move(ticket, PipelineStatus.AWAITING_REQUESTER)
    assert not clocks(ticket)

    clock.set(2026, 10, 23, 15, 30)
    lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)

    assert clocks(ticket)["response"].started_at == vn(2026, 10, 23, 15, 30)


def test_security_is_p2_and_an_open_incident_is_p1(clock, people):
    security = handed_off(people["lan"], category="security")
    incident = Incident.objects.create(
        public_id="INC-2026-0007",
        title="VPN down",
        category="network",
        severity="high",
        detected_by="human",
    )
    outage = handed_off(people["lan"], category="network", incident=incident)

    assert Ticket.objects.get(pk=security.pk).priority == "P2"
    assert Ticket.objects.get(pk=outage.pk).priority == "P1"


def test_p1_counts_around_the_clock(clock, people):
    """AC-F1-05: handed off Sat 22:00 (+07), resolution due Sun 02:00."""
    incident = Incident.objects.create(
        public_id="INC-2026-0008",
        title="Outage",
        category="network",
        severity="high",
        detected_by="human",
    )
    ticket = submitted(people["lan"], category="network", incident=incident)
    clock.set(2026, 10, 24, 22, 0)

    lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)

    assert clocks(ticket)["resolution"].due_at == vn(2026, 10, 25, 2, 0)


def test_a_ticket_answered_straight_away_gets_no_clock(clock, people):
    ticket = submitted(people["lan"], category="hardware")

    lifecycle.system_move(ticket, PipelineStatus.AUTO_REPLIED)

    assert not clocks(ticket)


# ── pausing and responding ──


def test_pause_resume_keeps_elapsed(clock, people):
    """AC-F1-03 and §g's worked example: paused at 810 minutes, due Thu 15:00 after the reply."""
    ticket = submitted(people["lan"], category="hardware")
    clock.set(2026, 10, 23, 15, 30)
    lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)

    clock.set(2026, 10, 26, 9, 12)
    move(ticket, "in_progress", people["mai"])
    assert clocks(ticket)["response"].state == ClockState.MET.value
    assert clocks(ticket)["response"].met_at == vn(2026, 10, 26, 9, 12)

    clock.set(2026, 10, 27, 10, 0)
    move(ticket, "waiting_on_requester", people["mai"])
    paused = clocks(ticket)["resolution"]
    assert (paused.state, minutes(paused), paused.due_at) == ("paused", 810, None)
    assert Ticket.objects.get(pk=ticket.pk).sla_due_at is None

    clock.set(2026, 10, 28, 9, 30)
    move(ticket, "in_progress", people["mai"])
    resumed = clocks(ticket)["resolution"]
    assert (resumed.state, minutes(resumed)) == ("running", 810)
    assert resumed.due_at == vn(2026, 10, 29, 15, 0)
    assert resumed.warn_at == vn(2026, 10, 28, 17, 22, 30)

    clock.set(2026, 10, 29, 11, 40)
    move(ticket, "resolved", people["mai"])
    met = clocks(ticket)["resolution"]
    assert (met.state, minutes(met), met.breached_at) == ("met", 1510, None)
    events = list(met.events.values_list("event", flat=True))
    assert events == ["start", "pause", "resume", "met"]


def test_an_assignment_is_not_a_response_but_a_review_decision_is(clock, people, api_as):
    """AC-F1-10 (the response half; a staff public comment arrives with F3)."""
    ticket = handed_off(people["lan"], category="hardware")
    Ticket.objects.filter(pk=ticket.pk).update(assigned_to=people["mai"])
    assert clocks(ticket)["response"].state == "running"
    item = ReviewItem.objects.create(ticket=ticket, queue=ReviewQueue.LOW_CONFIDENCE.value)

    clock.set(2026, 10, 26, 9, 12)
    api_as(people["mai"]).post(
        f"/api/review/items/{item.id}/decide",
        json.dumps({"action_taken": "approve", "time_spent_sec": 30}),
        content_type=JSON,
    )

    response = clocks(ticket)["response"]
    assert (response.state, response.met_at) == ("met", vn(2026, 10, 26, 9, 12))


def test_a_reopen_resumes_the_old_resolution_clock(clock, people):
    """BR-F1-13 (AC-F1-11's reopen arrives with F3; a person's move back does the same)."""
    ticket = handed_off(people["lan"], category="hardware")
    clock.set(2026, 10, 26, 10, 0)
    move(ticket, "resolved", people["mai"])
    elapsed = minutes(clocks(ticket)["resolution"])

    clock.set(2026, 10, 27, 9, 0)
    move(ticket, "in_progress", people["mai"])

    reopened = clocks(ticket)["resolution"]
    assert (reopened.state, minutes(reopened)) == ("running", elapsed)
    assert clocks(ticket)["response"].state == "met"
    assert Clock.objects.filter(ticket=ticket).count() == 2


# ── failure ──


def test_system_move_succeeds_when_sla_hook_raises(clock, people, monkeypatch):
    """AC-F1-06: the move stands, sla_update_failed is audited, the sweep rebuilds the clocks."""

    def broken(*args, **kwargs):
        raise RuntimeError("calendar unreadable")

    ticket = submitted(people["lan"], category="network")
    start = SlaClocks.start
    monkeypatch.setattr(SlaClocks, "start", broken)

    lifecycle.system_move(ticket, PipelineStatus.AUTO_ROUTED)

    ticket.refresh_from_db()
    assert ticket.status == "auto_routed"
    assert AuditLog.objects.filter(event="sla_update_failed").count() == 1
    assert Rebuild.objects.filter(ticket=ticket).exists()

    monkeypatch.setattr(SlaClocks, "start", start)
    sla_clocks.sweep()

    assert {c.state for c in clocks(ticket).values()} == {"running"}
    assert not Rebuild.objects.exists()


# ── the sweep ──


def test_each_sla_level_fires_once(clock, people):
    """AC-F1-04: P2 resolution (480): warn at 360, breach at 480, escalate at 600, once each."""
    clock.set(2026, 10, 26, 8, 0)
    ticket = handed_off(people["lan"], category="security", assigned_to=people["mai"])
    Ticket.objects.filter(pk=ticket.pk).update(assigned_to=people["mai"])

    for at in ((14, 0), (14, 0), (16, 0), (16, 0)):
        clock.set(2026, 10, 26, *at)
        sla_clocks.sweep()
    for _ in range(2):
        clock.set(2026, 10, 27, 8, 30)
        sla_clocks.sweep()

    def count(event: str) -> int:
        return (
            Message.objects.filter(event=event, channel="in_app")
            .values("event_id")
            .distinct()
            .count()
        )

    resolution = clocks(ticket)["resolution"]
    assert resolution.state == "breached"
    assert resolution.breached_at == vn(2026, 10, 26, 16, 0)
    # One per clock and level: the response clock (P2: 30 min) also warned, breached, escalated.
    assert count("sla.warning") == 2
    assert count("sla.breached") == 2
    assert count("sla.breached_escalated") == 2
    assert Message.objects.filter(user=people["huy"], event="sla.breached_escalated").exists()


def test_a_paused_clock_never_breaches(clock, people):
    clock.set(2026, 10, 26, 8, 0)
    ticket = handed_off(people["lan"], category="hardware")
    move(ticket, "waiting_on_requester", people["mai"])

    clock.set(2026, 11, 30, 8, 0)
    sla_clocks.sweep()

    assert clocks(ticket)["resolution"].state == "paused"
    assert not Message.objects.filter(event="sla.breached").exists()


# ── policies, priority and overrides ──


def test_policy_edit_does_not_change_running_clock(clock, people):
    """AC-F1-07."""
    clock.set(2026, 10, 23, 15, 30)
    running = handed_off(people["lan"], category="hardware")
    old = Policy.objects.get(name="P3 — normal")
    draft = sla_config.draft(
        people["quang"],
        {
            "name": "P3 — normal (faster)",
            "order": 30,
            "category": None,
            "priority": "P3",
            "response_minutes": 240,
            "resolution_minutes": 1140,
            "calendar_id": old.calendar_id,
            "is_24x7": False,
            "replaces_id": old.id,
        },
    )
    sla_config.approve(people["huy"], draft.id, "Cam kết mới với khối kinh doanh")

    assert clocks(running)["resolution"].due_at == vn(2026, 10, 28, 15, 30)
    later = handed_off(people["lan"], category="hardware")
    assert clocks(later)["resolution"].target_minutes() == 1140
    assert Policy.objects.get(pk=old.pk).state == "retired"


def test_priority_change_keeps_elapsed(clock, people, api_as):
    """AC-F1-09: 600 minutes into P3, a change to P2 (480) is breached at once."""
    clock.set(2026, 10, 26, 8, 0)
    ticket = handed_off(people["lan"], category="hardware")
    Ticket.objects.filter(pk=ticket.pk).update(assigned_to=people["ha"])
    clock.set(2026, 10, 27, 8, 30)
    ticket.refresh_from_db()

    response = api_as(people["ha"]).patch(
        f"/api/tickets/{ticket.public_id}/priority",
        json.dumps(
            {
                "priority": "P2",
                "reason": "Cả phòng kế toán bị ảnh hưởng",
                "expected_version": ticket.version,
            }
        ),
        content_type=JSON,
    )

    assert response.status_code == 200
    resolution = clocks(ticket)["resolution"]
    assert (resolution.target_minutes(), resolution.state, minutes(resolution)) == (
        480,
        "breached",
        600,
    )
    assert AuditLog.objects.filter(event="sla_retargeted").exists()
    assert AuditLog.objects.filter(event="ticket_priority_changed").count() == 1


def test_a_priority_change_needs_a_reason_and_a_right(clock, people, api_as):
    ticket = handed_off(people["lan"], category="hardware")
    url = f"/api/tickets/{ticket.public_id}/priority"
    body = {"priority": "P1", "expected_version": ticket.version}

    no_reason = api_as(people["huy"]).patch(
        url, json.dumps({**body, "reason": " "}), content_type=JSON
    )
    stranger = api_as(people["tu"]).patch(
        url, json.dumps({**body, "reason": "gấp"}), content_type=JSON
    )
    requester = api_as(people["lan"]).patch(
        url, json.dumps({**body, "reason": "gấp"}), content_type=JSON
    )

    assert no_reason.json()["code"] == "reason_required"
    assert stranger.json()["code"] == "not_allowed"
    assert requester.status_code == 403


def test_set_sla_overrides_the_resolution_target_in_business_hours(clock, people):
    """FR-F1-012."""
    clock.set(2026, 10, 23, 15, 30)
    ticket = handed_off(people["lan"], category="hardware")

    sla_clocks.override(ticket, 4, "Hợp đồng VIP")

    resolution = clocks(ticket)["resolution"]
    assert resolution.override_minutes == 240
    assert resolution.due_at == vn(2026, 10, 26, 10, 0)
    assert AuditLog.objects.get(event="sla_override").payload["reason"] == "Hợp đồng VIP"


def test_holidays_missing_for_next_year_tells_admins_once(clock, people):
    from apps.accounts.models import Capability, UserCapability

    UserCapability.objects.create(user=people["tu"], capability=Capability.WORKFLOW_ADMIN.value)
    clock.set(2027, 12, 1, 9, 0)

    sent = [sla_clocks.holiday_check(), sla_clocks.holiday_check()]

    assert sent == [1, 1]
    assert (
        Message.objects.filter(
            user=people["tu"], event="sla.holidays_missing", channel="in_app"
        ).count()
        == 1
    )


def test_a_rebuild_keeps_the_time_a_clock_fell_due(clock, people):
    """A clock past its target keeps the due time it passed, not the time of the recompute."""
    clock.set(2026, 10, 23, 15, 30)
    ticket = handed_off(people["lan"], category="hardware")
    clock.set(2026, 11, 3, 9, 0)

    sla_clocks.rebuild(ticket)

    assert clocks(ticket)["resolution"].due_at == vn(2026, 10, 28, 15, 30)


def test_a_rebuild_does_not_send_a_breach_again(clock, people):
    clock.set(2026, 10, 26, 8, 0)
    ticket = handed_off(people["lan"], category="security", assigned_to=people["mai"])
    clock.set(2026, 10, 27, 9, 0)
    sla_clocks.sweep()

    sla_clocks.rebuild(ticket)
    sla_clocks.sweep()

    breaches = Message.objects.filter(user=people["mai"], event="sla.breached", channel="in_app")
    assert breaches.count() == 2  # one per clock: response and resolution
