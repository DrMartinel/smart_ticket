"""F10 reporting: the facts build, every report's numbers and scope, exports and the weekly email
(AC-F10-01…10 and the §i regressions)."""

from __future__ import annotations

import csv
import io
import itertools
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from django.utils import timezone

from apps.accounts.models import Capability, User, UserCapability, UserRole
from apps.audit.models import AuditLog
from apps.incidents.models import IncidentLink
from apps.kb.models import DraftState, KbDraft, KbGapCluster, KbGapReport
from apps.notifications.models import Message
from apps.reports.models import FactState, TicketFacts
from apps.reports.utils.facts import report_facts
from apps.reports.utils.weekly import weekly_report
from apps.review.models import ReviewDecision, ReviewItem
from apps.rollout.utils.gates import rollout_metrics
from apps.security.models import SecurityAlert
from apps.sla.models import Calendar, Clock, Policy
from apps.sla.utils.clocks import snapshot_of
from apps.teams.models import Reassignment, Team, TeamMembership
from apps.tickets.models import (
    AiRun,
    Incident,
    RoutingDecision,
    Ticket,
    TicketEmbedding,
    TicketRating,
)

pytestmark = pytest.mark.django_db

VN = ZoneInfo("Asia/Ho_Chi_Minh")
_numbers = itertools.count(1)


def vn(month: int, day: int, hour: int = 10) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=VN)


def person(username: str, role: UserRole, *caps: Capability) -> User:
    user = User.objects.create_user(username=username, password="x", role=role.value)
    for cap in caps:
        UserCapability.objects.create(user=user, capability=cap.value, source="local")
    return user


def member(user: User, slug: str, role: str = "member") -> None:
    TeamMembership.objects.create(
        team=Team.objects.get(slug=slug), user=user, role=role, source="local"
    )


def ticket(reporter: User, team: str = "access", **fields: Any) -> Ticket:
    return Ticket.objects.create(
        public_id=fields.pop("public_id", f"TKT-RPT-{next(_numbers):06d}"),
        reporter=reporter,
        subject_masked="VPN không kết nối",
        body_masked="VPN báo lỗi 809",
        pii_level="routine",
        team=Team.objects.get(slug=team),
        assigned_team=team,
        **fields,
    )


def facts(t: Ticket, **fields: Any) -> TicketFacts:
    values: dict[str, Any] = {
        "created_day": t.created_at.astimezone(VN).date(),
        "team": t.assigned_team,
        "category": "access",
        "priority": "P3",
        "built_at": timezone.now(),
    }
    values.update(fields)
    return TicketFacts.objects.create(ticket=t, **values)


def decision(t: Ticket, branch: str, *, shadow: bool = True) -> tuple[AiRun, RoutingDecision]:
    run = AiRun.objects.create(
        ticket=t,
        idempotency_key=f"{t.id}:{next(_numbers)}",
        prompt_version="t",
        model="t",
        graph_version="t",
        trust_signals={},
    )
    routed = RoutingDecision.objects.create(
        ticket=t,
        ai_run=run,
        branch=branch,
        reason_code="all_checks_passed",
        reason_detail="",
        thresholds_used={},
        shadow_mode=shadow,
    )
    return run, routed


def review(
    t: Ticket,
    reviewer: User,
    action: str = "approve",
    seconds: int = 30,
    run: AiRun | None = None,
    corrected: str | None = None,
) -> ReviewDecision:
    item = ReviewItem.objects.create(ticket=t, ai_run=run, queue="low_confidence")
    return ReviewDecision.objects.create(
        review_item=item,
        reviewer=reviewer,
        action_taken=action,
        corrected_category=corrected,
        override_reason=None if action == "approve" else "x",
        time_spent_sec=seconds,
    )


@pytest.fixture
def staff() -> dict[str, User]:
    people = {
        "huy": person("huy.pq", UserRole.MANAGER),
        "quang": person("quang.nv", UserRole.MANAGER),
        "ha": person("ha.vt", UserRole.TECHNICIAN, Capability.KB_EDITOR),
        "mai": person("mai.bn", UserRole.TECHNICIAN),
        "duc": person("duc.tm", UserRole.TECHNICIAN, Capability.INCIDENT_MANAGER),
        "anh": person("anh.lh", UserRole.SECURITY),
        "tu": person("tu.dv", UserRole.TECHNICIAN, Capability.WORKFLOW_ADMIN),
        "lan": person("lan.nt", UserRole.EMPLOYEE),
    }
    member(people["ha"], "access", "lead")
    member(people["mai"], "access")
    member(people["duc"], "network", "lead")
    return people


@pytest.fixture
def october(staff: dict[str, User]) -> dict[str, Ticket]:
    """The six Access tickets of F10 §g's worked example."""
    lan = staff["lan"]
    met = vn(10, 14)
    rows = {
        "412": ("P3", FactState.MET, False, {}),
        "415": ("P3", FactState.BREACHED, False, {"resolution_warned_in_time": True}),
        "431": ("P3", FactState.MET, False, {"auto_replied": True}),
        "447": ("P2", FactState.MET, False, {}),
        "442": ("P1", FactState.MET, True, {}),
    }
    out = {}
    for number, (priority, state, linked, extra) in rows.items():
        t = ticket(lan, public_id=f"TKT-2026-000{number}", priority=priority)
        facts(
            t,
            priority=priority,
            response_state=FactState.MET.value,
            response_met_at=met,
            resolution_state=state.value,
            resolution_met_at=met + timedelta(hours=2),
            resolved_at=met + timedelta(hours=2),
            linked_incident=linked,
            **extra,
        )
        out[number] = t
    old = ticket(lan, public_id="TKT-2026-000301")
    facts(old, created_day=vn(10, 2).date(), resolved_at=vn(10, 3), priority=None)
    out["301"] = old
    return out


# ── SLA (UC-F10-01) ──


def test_ac_f10_01_sla_compliance_from_clocks(api_as, staff, october):
    response = api_as(staff["huy"]).get("/api/reports/sla?month=2026-10&team=access")

    assert response.status_code == 200
    body = response.json()
    assert body["resolution"] == {"met": 3, "breached": 1, "compliance": 0.75}
    assert body["response"] == {"met": 4, "breached": 0, "compliance": 1.0}
    assert body["breaches_warned_in_time"] == {"warned": 1, "breached": 1, "rate": 1.0}
    assert body["excluded"] == {"linked_incident": 1, "no_sla_data": 1}
    assert body["open_overdue_now"] == 0


def test_sla_compliance_uses_clocks_not_sla_due_at(api_as, staff):
    now = timezone.now()
    t = ticket(
        staff["lan"],
        sla_due_at=now - timedelta(days=4),
        resolved_at=now - timedelta(days=2),
    )
    facts(
        t,
        resolution_state=FactState.MET.value,
        resolution_met_at=now - timedelta(days=2),
        resolved_at=now - timedelta(days=2),
    )

    business = api_as(staff["huy"]).get("/api/metrics/dashboard").json()["business"]

    assert business["sla_compliance"] == 1.0


def test_an_open_breached_clock_is_only_open_overdue(api_as, staff):
    t = ticket(staff["lan"])
    calendar = Calendar.objects.get(is_default=True)
    policy = Policy.objects.filter(state="active").order_by("order").first()
    assert policy is not None
    started = timezone.now() - timedelta(days=3)
    Clock.objects.create(
        ticket=t,
        kind="resolution",
        policy=policy,
        policy_snapshot=snapshot_of(policy, calendar),
        state="breached",
        started_at=started,
        elapsed_as_of=started,
        breached_at=started + timedelta(days=1),
    )
    report_facts.build()

    body = api_as(staff["huy"]).get("/api/reports/sla?team=access").json()

    assert TicketFacts.objects.get(ticket=t).resolution_state == FactState.BREACHED.value
    assert body["resolution"] == {"met": 0, "breached": 0, "compliance": None}
    assert body["open_overdue_now"] == 1


def test_sla_drill_down_lists_the_cells_tickets(api_as, staff, october):
    client = api_as(staff["huy"])

    breached = client.get(
        "/api/reports/sla/tickets?month=2026-10&team=access&state=breached"
    ).json()
    excluded = client.get(
        "/api/reports/sla/tickets?month=2026-10&team=access&state=excluded"
    ).json()

    assert [t["public_id"] for t in breached["items"]] == ["TKT-2026-000415"]
    assert sorted(t["public_id"] for t in excluded["items"]) == [
        "TKT-2026-000301",
        "TKT-2026-000442",
    ]


def test_a_technician_who_leads_no_team_cannot_read_sla(api_as, staff):
    response = api_as(staff["mai"]).get("/api/reports/sla")

    assert response.status_code == 403
    assert response.json()["code"] == "report_scope_denied"


def test_a_lead_reads_sla_for_their_own_team_only(api_as, staff, october):
    client = api_as(staff["ha"])

    own = client.get("/api/reports/sla?month=2026-10")
    other = client.get("/api/reports/sla?month=2026-10&team=network")

    assert own.status_code == 200
    assert [c["key"] for c in own.json()["by_team"]] == ["access"]
    assert other.status_code == 403


# ── AC-F10-06 export ──


def test_ac_f10_06_export_matches_the_screen(api_as, staff, october):
    client = api_as(staff["huy"])
    shown = client.get("/api/reports/sla?month=2026-10&team=access").json()

    exported = client.get("/api/reports/sla.csv?month=2026-10&team=access")

    assert exported.status_code == 200
    assert exported["Content-Type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode())))
    total = next(r for r in rows if r["dimension"] == "total")
    assert int(total["resolution_met"]) == shown["resolution"]["met"]
    assert int(total["resolution_breached"]) == shown["resolution"]["breached"]
    assert float(total["resolution_compliance"]) == shown["resolution"]["compliance"]
    assert int(total["response_met"]) == shown["response"]["met"]
    audit = AuditLog.objects.filter(event="report_exported")
    assert audit.count() == 1
    assert audit.get().payload["report"] == "sla"


# ── AC-F10-07 incidents ──


def test_incident_tickets_excluded_from_team_sla(api_as, staff):
    incident = Incident.objects.create(
        public_id="INC-2026-0007",
        title="VPN gateway down",
        severity="high",
        detected_by="density_detector",
        status="confirmed",
        confirmed_at=timezone.now(),
    )
    now = timezone.now()
    for n in range(23):
        t = ticket(staff["lan"], team="network")
        IncidentLink.objects.create(incident=incident, ticket=t, linked_by="detector")
        facts(
            t,
            team="network",
            resolution_state=FactState.BREACHED.value,
            resolution_met_at=now - timedelta(minutes=n + 1),
            linked_incident=True,
        )
    for n in range(2):
        t = ticket(staff["lan"], team="network")
        facts(
            t,
            team="network",
            resolution_state=FactState.MET.value,
            resolution_met_at=now - timedelta(minutes=n + 1),
        )

    sla = api_as(staff["huy"]).get("/api/reports/sla?team=network").json()
    incidents = api_as(staff["duc"]).get("/api/reports/incidents").json()

    assert sla["resolution"] == {"met": 2, "breached": 0, "compliance": 1.0}
    assert sla["excluded"]["linked_incident"] == 23
    assert incidents["linked_tickets"] == 23
    assert incidents["confirmed"] == 1


def test_unlink_rate_counts_links_removed(api_as, staff):
    incident = Incident.objects.create(
        public_id="INC-2026-0008", title="t", severity="high", detected_by="density_detector"
    )
    for n in range(4):
        IncidentLink.objects.create(
            incident=incident,
            ticket=ticket(staff["lan"]),
            linked_by="detector",
            unlinked_at=timezone.now() if n == 0 else None,
        )

    body = api_as(staff["huy"]).get("/api/reports/incidents").json()

    assert body["unlink_rate"] == 0.25
    assert api_as(staff["mai"]).get("/api/reports/incidents").status_code == 403


# ── teams (UC-F10-02) ──


def test_lead_cannot_read_other_team(api_as, staff):
    client = api_as(staff["ha"])

    assert client.get("/api/reports/teams/network").status_code == 403
    assert client.get("/api/reports/teams/network.csv").status_code == 403
    assert client.get("/api/reports/teams/access").status_code == 200


def test_a_member_sees_only_their_own_row(api_as, staff):
    body = api_as(staff["mai"]).get("/api/reports/teams/access").json()

    assert [m["username"] for m in body["members"]] == ["mai.bn"]


def test_team_report_counts_workload_and_cross_team_reassignment(api_as, staff):
    now = timezone.now()
    held = ticket(staff["lan"], assigned_to=staff["mai"])
    moved = ticket(staff["lan"], assigned_to=staff["mai"])
    Reassignment.objects.create(
        ticket=moved,
        from_user=staff["ha"],
        to_user=staff["mai"],
        from_team=Team.objects.get(slug="network"),
        to_team=Team.objects.get(slug="access"),
        reason_code="wrong_team",
        note_masked="sai nhóm",
        actor=staff["ha"],
    )
    facts(held, first_assigned_at=now - timedelta(hours=1), time_to_assign_business_min=10)
    facts(
        moved,
        first_assigned_at=now - timedelta(hours=1),
        time_to_assign_business_min=30,
        cross_team_reassign_count=1,
        reassign_count=1,
    )
    ticket(staff["lan"])

    body = api_as(staff["ha"]).get("/api/reports/teams/access").json()

    mai = next(m for m in body["members"] if m["username"] == "mai.bn")
    assert mai["open_now"] == 2
    assert mai["age_buckets"]["0-1"] == 2
    assert mai["reassigned_in"] == 1
    assert body["tickets_assigned"] == 2
    assert body["reassignment_rate"] == 0.5
    assert body["unassigned_now"] == 1
    assert body["time_to_assign_median_min"] == 20


# ── reviewers (UC-F10-03) ──


@pytest.fixture
def reviewed(staff) -> None:
    """F10 §g's reviewers, scaled down: duc.tm 25 at 96 % in 7 s, ha.vt 25 at 80 % in 34 s,
    mai.bn 12 at 100 % in 6 s."""
    t = ticket(staff["lan"])
    for name, total, approved, seconds in (
        ("duc", 25, 24, 7),
        ("ha", 25, 20, 34),
        ("mai", 12, 12, 6),
    ):
        for n in range(total):
            review(t, staff[name], "approve" if n < approved else "reroute", seconds)


def test_reviewer_flag_needs_min_decisions(api_as, staff, reviewed):
    body = api_as(staff["huy"]).get("/api/reports/reviewers?days=30").json()

    flagged = {r["username"]: r["flagged"] for r in body["rows"]}
    assert flagged == {"duc.tm": True, "ha.vt": False, "mai.bn": False}
    assert body["min_decisions_for_flag"] == 20


def test_ac_f10_04_a_reviewer_sees_only_themself(api_as, staff, reviewed):
    client = api_as(staff["ha"])

    own = client.get("/api/reports/reviewers").json()
    other = client.get("/api/reports/reviewers?reviewer=duc.tm")

    assert [r["username"] for r in own["rows"]] == ["ha.vt"]
    assert other.status_code == 403


# ── KB (UC-F10-04) ──


def test_ac_f10_08_gap_closure_compares_four_weeks_before_and_after(api_as, staff):
    now = timezone.now()
    published = now - timedelta(weeks=5)
    vector = np.zeros(1024)
    vector[0] = 1.0
    gap_report = KbGapReport.objects.create(window_start=now, window_end=now)
    cluster = KbGapCluster.objects.create(
        report=gap_report, label="gap", size=9, centroid=vector.tolist(), state="drafted"
    )
    KbDraft.objects.create(
        kind="create",
        slug="vpn-error-809",
        title="VPN error 809",
        body="b",
        category="network",
        author=staff["ha"],
        state=DraftState.PUBLISHED.value,
        gap_cluster=cluster,
        published_at=published,
    )
    for n, at in enumerate(
        [published - timedelta(days=d + 1) for d in range(9)]
        + [published + timedelta(days=d + 1) for d in range(3)]
    ):
        t = ticket(staff["lan"])
        Ticket.objects.filter(pk=t.pk).update(created_at=at)
        TicketEmbedding.objects.create(ticket=t, model="t", embedding=vector.tolist())
        RoutingDecision.objects.create(
            ticket=t,
            branch="hitl",
            reason_code="retrieval_below_floor",
            reason_detail="",
            thresholds_used={},
        )

    body = api_as(staff["ha"]).get("/api/reports/kb").json()

    closure = body["closures"][0]
    assert (closure["before"], closure["after"]) == (9, 3)
    assert round(closure["closure"], 2) == 0.67
    assert closure["complete"] is True
    assert api_as(staff["mai"]).get("/api/reports/kb").status_code == 403


# ── CSAT (UC-F10-05) ──


def test_ac_f10_09_csat_splits_auto_and_person(api_as, staff):
    at = timezone.now() - timedelta(minutes=5)
    for score, auto in ((4, True), (4, True), (5, True), (5, False), (4, False)):
        facts(
            ticket(staff["lan"]),
            auto_replied=auto,
            csat_score=score,
            csat_at=at,
            resolved_at=at,
        )

    body = api_as(staff["huy"]).get("/api/reports/csat").json()

    assert round(body["auto"]["mean"], 2) == 4.33
    assert body["person"]["mean"] == 4.5
    assert body["auto"]["distribution"]["5"] == 1
    assert "mean" not in body


def test_low_rated_comments_are_masked_text(api_as, staff):
    t = ticket(staff["lan"])
    TicketRating.objects.create(
        ticket=t, resolution_seq=1, score=1, comment_masked="[EMAIL_1] chậm"
    )

    body = api_as(staff["ha"]).get("/api/reports/csat").json()

    assert body["low_rated"][0]["comment"] == "[EMAIL_1] chậm"


# ── rollout (UC-F10-06) ──


def test_automation_rate_split_live_vs_shadow(api_as, staff):
    t = ticket(staff["lan"])
    for n in range(100):
        decision(t, "auto_route" if n < 40 else "hitl", shadow=True)

    business = api_as(staff["huy"]).get("/api/metrics/dashboard").json()["business"]
    rollout = api_as(staff["huy"]).get("/api/reports/rollout").json()["automation"]

    assert business["automation_rate_live"] == 0.0
    assert business["automation_rate_would_have"] == 0.4
    assert business["automation_rate"] == 0.4
    assert (rollout["live_rate"], rollout["would_have_rate"]) == (0.0, 0.4)


def test_ac_f10_10_shadow_agreement_uses_the_gate_query(api_as, staff):
    t = ticket(staff["lan"])
    outcomes = ["reroute"] * 2 + ["corrected"] + ["approve"] * 7
    for outcome in outcomes:
        run, _ = decision(t, "auto_route")
        if outcome == "corrected":
            review(t, staff["ha"], "approve", run=run, corrected="network")
        else:
            review(t, staff["ha"], outcome, run=run)

    body = api_as(staff["huy"]).get("/api/reports/rollout").json()

    auto_route = next(b for b in body["branches"] if b["decision_branch"] == "auto_route")
    assert auto_route["agreement"]["rate"] == 0.7
    assert (
        auto_route["agreement"]["rate"] == rollout_metrics.shadow_agreement("auto_route", 14).rate
    )
    assert api_as(staff["mai"]).get("/api/reports/rollout").status_code == 403


# ── security, notifications (UC-F10-07, FR-F10-012) ──


def test_a_manager_sees_security_counts_only(api_as, staff):
    now = timezone.now()
    SecurityAlert.objects.create(
        kind="pii_critical",
        state="closed",
        severity="critical",
        first_seen_at=now - timedelta(hours=2),
        last_seen_at=now,
        ack_due_at=now,
        acknowledged_at=now - timedelta(hours=1),
        resolution="false_positive",
        closed_at=now,
    )

    manager = api_as(staff["huy"]).get("/api/reports/security").json()
    security = api_as(staff["anh"]).get("/api/reports/security").json()

    assert manager["detail"] is False
    assert manager["total"] == 1
    assert manager["ack_p50_sec"] is None and manager["false_positive_rate"] is None
    assert security["ack_p50_sec"] == 3600
    assert security["false_positive_rate"] == 1.0
    assert api_as(staff["mai"]).get("/api/reports/security").status_code == 403


def test_notification_report_needs_a_manager_or_workflow_admin(api_as, staff):
    assert api_as(staff["tu"]).get("/api/reports/notifications").status_code == 200
    assert api_as(staff["mai"]).get("/api/reports/notifications").status_code == 403


# ── facts (FR-F10-001) ──


def built(t: Ticket) -> dict[str, Any]:
    row = TicketFacts.objects.filter(ticket=t).values().get()
    return {k: v for k, v in row.items() if k not in ("id", "built_at")}


def test_facts_build_is_idempotent(staff):
    t = ticket(staff["lan"], assigned_to=staff["mai"], resolved_at=timezone.now())
    calendar = Calendar.objects.get(is_default=True)
    policy = Policy.objects.filter(state="active").order_by("order").first()
    assert policy is not None
    started = timezone.now() - timedelta(days=2)
    for kind, state, breached in (("response", "met", None), ("resolution", "met", started)):
        Clock.objects.create(
            ticket=t,
            kind=kind,
            policy=policy,
            policy_snapshot=snapshot_of(policy, calendar),
            state=state,
            started_at=started,
            elapsed_as_of=started,
            warned_at=started - timedelta(minutes=1) if breached else None,
            breached_at=breached,
            met_at=started + timedelta(hours=1),
        )
    Reassignment.objects.create(
        ticket=t,
        from_team=Team.objects.get(slug="network"),
        to_team=Team.objects.get(slug="access"),
        reason_code="wrong_team",
        note_masked="sai nhóm",
        actor=staff["ha"],
    )
    TicketRating.objects.create(ticket=t, resolution_seq=1, score=4)

    assert report_facts.build() >= 1
    first = built(t)
    report_facts.build()

    assert TicketFacts.objects.filter(ticket=t).count() == 1
    assert built(t) == first
    assert first["response_state"] == FactState.MET.value
    assert first["resolution_state"] == FactState.BREACHED.value
    assert first["resolution_warned_in_time"] is True
    assert first["cross_team_reassign_count"] == 1
    assert first["csat_score"] == 4


def test_a_second_build_only_touches_changed_tickets(staff):
    quiet = ticket(staff["lan"])
    rated = ticket(staff["lan"], resolved_at=timezone.now())
    report_facts.build()

    TicketRating.objects.create(ticket=rated, resolution_seq=1, score=2)

    assert report_facts.changed_since(TicketFacts.objects.get(ticket=quiet).built_at) == [rated.id]
    report_facts.build()
    assert TicketFacts.objects.get(ticket=rated).csat_score == 2


def test_a_live_auto_reply_and_an_active_link_are_recorded(staff):
    t = ticket(staff["lan"])
    decision(t, "auto_reply", shadow=False)
    incident = Incident.objects.create(
        public_id="INC-2026-0009", title="t", severity="high", detected_by="density_detector"
    )
    IncidentLink.objects.create(incident=incident, ticket=t, linked_by="detector")

    report_facts.build()

    row = TicketFacts.objects.get(ticket=t)
    assert row.auto_replied is True
    assert row.linked_incident is True
    assert row.resolution_state == FactState.NONE.value


# ── weekly email (FR-F10-014) ──


def test_the_weekly_email_goes_once_per_week(staff):
    assert weekly_report.send() is True
    assert weekly_report.send() is False

    sent = Message.objects.filter(event="report.weekly")
    assert sorted(sent.values_list("user__username", flat=True)) == ["huy.pq", "quang.nv"]
    assert "K1" in sent.first().body  # type: ignore[union-attr]
    assert AuditLog.objects.filter(event="report_weekly_sent").count() == 1


def test_the_weekly_email_links_to_the_admin_dashboard(staff):
    weekly_report.send()

    links = set(Message.objects.filter(event="report.weekly").values_list("link", flat=True))
    assert links == {"/admin/dashboard"}
