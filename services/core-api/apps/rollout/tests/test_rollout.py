"""Rollout and threshold control (F9, ADR-0035). What goes wrong quietly here: a branch going live
on one person's say, a flag changing the decision itself, or unreviewed numbers acting on tickets."""

from __future__ import annotations

import ast
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.accounts.models import Capability, User, UserCapability, UserRole
from apps.audit.models import AuditLog
from apps.lifecycle.tests.conftest import make_ticket
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.notifications.models import Message
from apps.review.models import ReviewDecision, ReviewItem
from apps.rollout.models import FlagRequest, RolloutFlag, RolloutGate, ThresholdChangeRequest
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.thresholds import threshold_changes
from apps.rollout.utils.vocabulary import FlagBranch
from apps.security.models import SecurityAlert
from apps.tickets.models import AiRun, RoutingDecision
from apps.tickets.utils.pipeline import _finalize
from apps.tickets.utils.router import Branch, KBArticleMeta, ReasonCode, RiskTier
from apps.tickets.utils.router import RoutingDecision as Decision
from infrastructure.dtos import TicketCategory

pytestmark = pytest.mark.django_db

CORE_API = Path(__file__).resolve().parents[3]


def person(username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username, password="x", role=role.value, email=f"{username}@example.test"
    )


@pytest.fixture(autouse=True)
def fresh_status():
    rollout._status = None
    yield
    rollout._status = None


@pytest.fixture
def people(db) -> dict[str, User]:
    found = {
        "lan": person("lan.nt", UserRole.EMPLOYEE),
        "huy": person("huy.pq", UserRole.MANAGER),
        "quang": person("quang.nv", UserRole.MANAGER),
        "dung": person("dung.ht", UserRole.MANAGER),
        "anh": person("anh.lh", UserRole.SECURITY),
        "tu": person("tu.dv", UserRole.TECHNICIAN),
        "mai": person("mai.bn", UserRole.TECHNICIAN),
    }
    UserCapability.objects.create(
        user=found["tu"], capability=Capability.WORKFLOW_ADMIN.value, source="local"
    )
    return found


@pytest.fixture
def env_live(settings):
    settings.SHADOW_MODE = False
    settings.THRESHOLDS_REQUIRE_APPROVAL = False


def set_flags(**states: str) -> None:
    for branch, state in states.items():
        RolloutFlag.objects.filter(branch=branch).update(state=state)


def decide(reporter: User, branch: Branch) -> RoutingDecision:
    """Carries out one router decision through the routing step, as the pipeline does."""
    ticket = make_ticket(reporter, at=PipelineStatus.NEW)
    run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="t",
        model="t",
        graph_version="t",
        trust_signals={},
    )
    kb = None
    if branch is Branch.AUTO_REPLY:
        decision = Decision(branch=branch, reason_code=ReasonCode.ALL_CHECKS_PASSED, kb_slug="p")
        kb = KBArticleMeta(
            id=uuid.uuid4(),
            slug="p",
            category=TicketCategory.ACCESS,
            auto_reply_allowed=True,
            risk_tier=RiskTier.LOW,
        )
    else:
        decision = Decision(
            branch=branch,
            reason_code=ReasonCode.ALL_CHECKS_PASSED,
            category=TicketCategory.NETWORK,
        )
    _finalize(ticket, run, decision, "trace", kb=kb)
    return RoutingDecision.objects.select_related("ticket").get(ticket=ticket)


def shadow_reviews(reporter: User, reviewer: User, *, decided: int, rerouted: int) -> None:
    """Shadow auto_route decisions a reviewer decided, `rerouted` of them rerouted."""
    for n in range(decided):
        ticket = make_ticket(reporter)
        run = AiRun.objects.create(
            ticket=ticket,
            idempotency_key=f"{ticket.id}:1",
            prompt_version="t",
            model="t",
            graph_version="t",
            trust_signals={},
        )
        RoutingDecision.objects.create(
            ticket=ticket,
            ai_run=run,
            branch="auto_route",
            reason_code="all_checks_passed",
            reason_detail="",
            thresholds_used={},
            shadow_mode=True,
        )
        item = ReviewItem.objects.create(ticket=ticket, ai_run=run, queue="low_confidence")
        ReviewDecision.objects.create(
            review_item=item,
            reviewer=reviewer,
            action_taken="reroute" if n < rerouted else "approve",
            corrected_category="access" if n < rerouted else None,
            override_reason="x" if n < rerouted else None,
            time_spent_sec=30,
        )


def post(client, url: str, body: dict | None = None):
    return client.post(url, body or {}, content_type="application/json")


class TestLiveOrShadow:
    def test_one_branch_live_the_other_shadow(self, people, env_live):
        """AC-F9-01 (BR-F9-01, BR-F9-09)."""
        set_flags(auto_route="on", auto_reply="off")

        a = decide(people["lan"], Branch.AUTO_ROUTE)
        b = decide(people["lan"], Branch.AUTO_REPLY)

        assert (a.shadow_mode, a.ticket.status) == (False, "auto_routed")
        assert b.shadow_mode is True
        assert b.ticket.review_items.count() == 1
        assert a.rollout_snapshot == b.rollout_snapshot
        assert a.rollout_snapshot["auto_route"] == "on"
        assert a.rollout_snapshot["auto_reply"] == "off"

    def test_route_is_identical_whatever_the_flags(self, people, env_live):
        """The flags decide only whether a decision is carried out, never which it is (§8.2)."""
        off = decide(people["lan"], Branch.AUTO_ROUTE)
        set_flags(auto_route="on")
        on = decide(people["lan"], Branch.AUTO_ROUTE)

        assert (off.branch, off.reason_code) == (on.branch, on.reason_code)
        assert (off.shadow_mode, on.shadow_mode) == (True, False)
        source = (CORE_API / "apps/tickets/utils/router.py").read_text()
        imported = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
        assert not any(m and "rollout" in m for m in imported)

    def test_env_shadow_overrides_flags(self, people, settings):
        """AC-F9-04."""
        settings.SHADOW_MODE = True
        settings.THRESHOLDS_REQUIRE_APPROVAL = False
        set_flags(auto_route="on")

        assert decide(people["lan"], Branch.AUTO_ROUTE).shadow_mode is True

    def test_unapproved_thresholds_force_shadow(self, people, settings):
        """AC-F9-05 (BR-F9-07)."""
        settings.SHADOW_MODE = False
        settings.THRESHOLDS_REQUIRE_APPROVAL = True
        ThresholdChangeRequest.objects.all().delete()
        set_flags(auto_route="on", auto_reply="on")

        a = decide(people["lan"], Branch.AUTO_ROUTE)
        b = decide(people["lan"], Branch.AUTO_REPLY)

        assert a.shadow_mode is True and b.shadow_mode is True
        assert a.rollout_snapshot["thresholds_approved"] is False
        (alert,) = SecurityAlert.objects.filter(kind="thresholds_unapproved")
        assert alert.severity == "high"
        assert Message.objects.filter(user=people["huy"], event="thresholds.unapproved").exists()

    def test_the_approved_baseline_loads(self, people, settings):
        """FR-F9-008: the file matching an approved request is marked loaded and audited."""
        settings.THRESHOLDS_REQUIRE_APPROVAL = True

        status = rollout.thresholds_status()

        assert (status.approved, status.change_request) == (True, "CR-2026-000")
        assert ThresholdChangeRequest.objects.get(version="CR-2026-000").state == "loaded"
        assert AuditLog.objects.filter(event="thresholds_loaded").count() == 1

    def test_no_runbook_flag_exists(self, people, api_as):
        """AC-F9-07 (BR-F9-10, ADR-0006)."""
        assert "runbook" not in {b.value for b in FlagBranch}
        assert not RolloutFlag.objects.filter(branch__icontains="runbook").exists()
        response = post(api_as(people["huy"]), "/api/rollout/runbook/requests", {"reason": "thử"})
        assert (response.status_code, response.json()["code"]) == (404, "no_such_branch")

    def test_production_cant_skip_the_threshold_check(self):
        """AC-F9-10 (BR-F9-08): production.py forces the check on after reading the env."""
        tree = ast.parse((CORE_API / "config/settings/production.py").read_text())
        forced = [
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(getattr(t, "id", None) == "THRESHOLDS_REQUIRE_APPROVAL" for t in n.targets)
        ]
        assert forced and isinstance(forced[-1].value, ast.Constant)
        assert forced[-1].value.value is True


class TestFlags:
    def test_one_person_cannot_turn_on(self, people, api_as, env_live):
        """AC-F9-02 (BR-F9-02)."""
        made = post(
            api_as(people["huy"]),
            "/api/rollout/auto_route/requests",
            {"reason": "P3: reroute 12.5 % trên 14 ngày", "gate_override_reason": ""},
        ).json()
        base = f"/api/rollout/requests/{made['id']}"
        body = {"gate_override_reason": "thử nghiệm"}

        own = post(api_as(people["huy"]), f"{base}/approve", body)
        assert (own.status_code, own.json()["code"]) == (403, "self_approval")
        tech = post(api_as(people["tu"]), f"{base}/approve", body)
        assert tech.status_code == 403
        assert post(api_as(people["quang"]), f"{base}/approve", body).json()["state"] == "pending"
        twice = post(api_as(people["quang"]), f"{base}/approve", body)
        assert twice.json()["code"] == "already_approved_by_you"
        assert RolloutFlag.objects.get(branch="auto_route").state == "pending_on"
        assert post(api_as(people["dung"]), f"{base}/approve", body).json()["state"] == "approved"

        assert RolloutFlag.objects.get(branch="auto_route").state == "on"
        assert AuditLog.objects.filter(event="rollout_flag_on").count() == 1

    def test_one_person_can_turn_off(self, people, api_as, env_live):
        """AC-F9-03 (BR-F9-02)."""
        set_flags(auto_reply="on")

        response = post(
            api_as(people["anh"]),
            "/api/rollout/auto_reply/off",
            {"reason": "Phản hồi sai trên trang VPN"},
        )

        assert response.status_code == 200
        assert RolloutFlag.objects.get(branch="auto_reply").state == "off"
        assert decide(people["lan"], Branch.AUTO_REPLY).shadow_mode is True
        assert (
            post(api_as(people["anh"]), "/api/rollout/auto_reply/off", {"reason": "lại"}).json()[
                "code"
            ]
            == "already_off"
        )

    def test_an_unmet_gate_needs_an_override_reason(self, people, api_as, env_live):
        """AC-F9-06 (BR-F9-03): 9 of 50 rerouted is 0.18 against < 0.15."""
        shadow_reviews(people["lan"], people["mai"], decided=50, rerouted=9)
        made = post(
            api_as(people["huy"]), "/api/rollout/auto_route/requests", {"reason": "P3"}
        ).json()
        gate = next(g for g in made["gate_snapshot_at_request"] if g["metric"] == "reroute_rate")
        assert (gate["value"], gate["met"]) == (0.18, False)

        response = post(api_as(people["quang"]), f"/api/rollout/requests/{made['id']}/approve")

        assert (response.status_code, response.json()["code"]) == (422, "override_reason_required")

    def test_a_met_gate_needs_no_override(self, people, api_as, env_live):
        shadow_reviews(people["lan"], people["mai"], decided=40, rerouted=4)
        made = post(
            api_as(people["huy"]), "/api/rollout/auto_route/requests", {"reason": "P3"}
        ).json()

        response = post(api_as(people["quang"]), f"/api/rollout/requests/{made['id']}/approve")

        assert response.status_code == 200
        (approval,) = response.json()["approvals"]
        assert approval["gate_snapshot"][0]["met"] is True

    def test_the_holdout_precision_is_entered_with_evidence(self, people, api_as, env_live):
        client = api_as(people["huy"])
        missing = post(client, "/api/rollout/auto_reply/requests", {"reason": "P4"})
        assert missing.json()["code"] == "entered_value_required"

        made = post(
            client,
            "/api/rollout/auto_reply/requests",
            {
                "reason": "P4",
                "entered_values": {
                    "holdout_precision": {"value": 0.97, "evidence": "evals/HISTORY.md 2026-11-20"}
                },
            },
        ).json()
        holdout = next(
            g for g in made["gate_snapshot_at_request"] if g["metric"] == "holdout_precision"
        )
        assert (holdout["value"], holdout["met"], holdout["entered"]) == (0.97, True, True)

    def test_a_request_needs_approved_thresholds(self, people, api_as, settings):
        settings.THRESHOLDS_REQUIRE_APPROVAL = True
        ThresholdChangeRequest.objects.all().delete()

        response = post(api_as(people["huy"]), "/api/rollout/auto_route/requests", {"reason": "P3"})

        assert response.json()["code"] == "thresholds_unapproved"

    def test_an_unapproved_request_expires(self, people, env_live):
        request = rollout.request_on("auto_route", people["huy"], "P3")
        FlagRequest.objects.filter(pk=request.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        assert rollout.sweep()["expired"] == 1
        assert RolloutFlag.objects.get(branch="auto_route").state == "off"
        request.refresh_from_db()
        assert request.state == "expired"

    def test_a_live_branch_whose_gate_slipped_is_reported_once_a_day(self, people, env_live):
        set_flags(auto_route="on")
        shadow_reviews(people["lan"], people["mai"], decided=10, rerouted=3)

        rollout.sweep()
        rollout.sweep()

        notices = Message.objects.filter(
            user=people["huy"], event="rollout.gate_unmet", channel="in_app"
        )
        assert notices.count() == 1
        assert RolloutFlag.objects.get(branch="auto_route").state == "on"


class TestGates:
    def test_a_gate_change_needs_approval(self, people, api_as):
        """AC-F9-08 (BR-F9-04)."""
        gate = RolloutGate.objects.get(branch="auto_route", metric="reroute_rate")
        change = (
            api_as(people["huy"])
            .patch(
                f"/api/rollout/gates/{gate.id}",
                {"threshold": 0.20, "window_days": 14, "reason": "Thử nới ngưỡng"},
                content_type="application/json",
            )
            .json()
        )

        shown = api_as(people["huy"]).get("/api/rollout").json()
        assert next(g for g in shown["gates"] if g["id"] == str(gate.id))["threshold"] == 0.15
        assert shown["gate_changes"][0]["state"] == "pending"
        own = post(api_as(people["huy"]), f"/api/rollout/gate-changes/{change['id']}/approve")
        assert own.json()["code"] == "self_approval"

        post(api_as(people["quang"]), f"/api/rollout/gate-changes/{change['id']}/approve")

        gate.refresh_from_db()
        assert gate.threshold == 0.20


class TestThresholdChanges:
    def current_with(self, version: str, **changes: str) -> str:
        text = threshold_changes.current_text().replace(
            'version: "CR-2026-000"', f'version: "{version}"'
        )
        for old, new in changes.items():
            text = text.replace(old, new)
        return text

    def test_a_change_request_holds_the_whole_file(self, people, api_as):
        """AC-F9-09 (BR-F9-05, BR-F9-06)."""
        client = api_as(people["tu"])
        partial = post(
            client, "/api/thresholds/change-requests", {"yaml_text": "trust:\n  t_auto: 0.86\n"}
        )
        assert (partial.status_code, partial.json()["code"]) == (422, "invalid_thresholds")
        assert partial.json()["details"]["path"] == "version"

        made = post(
            client,
            "/api/thresholds/change-requests",
            {"yaml_text": self.current_with("CR-2026-001"), "evidence": "calibration 2026-11-20"},
        ).json()
        post(client, f"/api/thresholds/change-requests/{made['id']}/submit")
        own = post(
            client, f"/api/thresholds/change-requests/{made['id']}/approve", {"comment": "ok"}
        )
        assert (own.status_code, own.json()["code"]) == (403, "self_approval")

    def test_threshold_cr_rejects_invalid_yaml(self, people, api_as):
        response = post(
            api_as(people["tu"]), "/api/thresholds/change-requests", {"yaml_text": "a: [unclosed"}
        )
        assert (response.status_code, response.json()["code"]) == (422, "invalid_thresholds")

    def test_the_file_must_carry_its_request_id(self, people, api_as):
        response = post(
            api_as(people["tu"]),
            "/api/thresholds/change-requests",
            {"yaml_text": self.current_with("CR-2026-099")},
        )
        assert response.json()["code"] == "version_mismatch"
        assert response.json()["details"]["version"] == "CR-2026-001"

    def test_two_approvers_one_a_manager_neither_the_author(self, people, api_as):
        made = threshold_changes.create(
            people["tu"], self.current_with("CR-2026-001", **{"t_auto: 0.88": "t_auto: 0.86"}), "e"
        )
        threshold_changes.submit(made.id, people["tu"])
        threshold_changes.approve(made.id, people["mai"], "ok")
        with pytest.raises(Exception, match="manager"):
            threshold_changes.approve(made.id, people["anh"], "ok")

        done = threshold_changes.approve(made.id, people["huy"], "ok")

        assert done.state == "approved"
        assert "t_auto: 0.86" in done.diff
        assert AuditLog.objects.filter(event="threshold_cr_approved").count() == 1
