"""Rollout control and the loaded thresholds (F9, ADR-0035, ADR-0044)."""

from __future__ import annotations

import ast
import hashlib
import uuid
from pathlib import Path

import pytest
from django.conf import settings as django_settings

from apps.accounts.models import Capability, User, UserRole

from apps.accounts.testing import grant_capability
from apps.audit.models import AuditLog
from apps.lifecycle.tests.conftest import make_ticket
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.notifications.models import Message
from apps.review.models import ReviewDecision, ReviewItem
from apps.rollout.models import FlagRequest, RolloutFlag, RolloutGate
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.vocabulary import FlagBranch
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
    grant_capability(found["tu"], Capability.WORKFLOW_ADMIN.value)
    return found


@pytest.fixture
def env_live(settings):
    settings.SHADOW_MODE = False


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
        set_flags(auto_route="on")

        assert decide(people["lan"], Branch.AUTO_ROUTE).shadow_mode is True

    def test_a_decision_records_the_thresholds_version(self, people, env_live):
        """BR-F9-09: live needs only the env switch and the flag (ADR-0044)."""
        set_flags(auto_route="on")

        decision = decide(people["lan"], Branch.AUTO_ROUTE)

        assert decision.shadow_mode is False
        assert decision.rollout_snapshot["thresholds"] == django_settings.THRESHOLDS.version

    def test_no_runbook_flag_exists(self, people, api_as):
        """AC-F9-07 (BR-F9-10, ADR-0006)."""
        assert "runbook" not in {b.value for b in FlagBranch}
        assert not RolloutFlag.objects.filter(branch__icontains="runbook").exists()
        response = post(api_as(people["huy"]), "/api/rollout/runbook/on", {"reason": "thử"})
        assert (response.status_code, response.json()["code"]) == (404, "no_such_branch")


class TestFlags:
    def test_one_manager_turns_on_at_once(self, people, api_as, env_live):
        """ADR-0043: no second manager."""
        response = post(
            api_as(people["huy"]),
            "/api/rollout/auto_route/on",
            {"reason": "P3: reroute 12.5 % trên 14 ngày", "gate_override_reason": "thử nghiệm"},
        )

        assert response.status_code == 200
        assert RolloutFlag.objects.get(branch="auto_route").state == "on"
        (on,) = AuditLog.objects.filter(event="rollout_flag_on")
        assert on.actor_id == people["huy"].id
        again = post(api_as(people["quang"]), "/api/rollout/auto_route/on", {"reason": "x"})
        assert again.json()["code"] == "already_on"

    def test_a_technician_cannot_turn_on(self, people, api_as, env_live):
        response = post(api_as(people["tu"]), "/api/rollout/auto_route/on", {"reason": "P3"})

        assert response.status_code == 403
        assert RolloutFlag.objects.get(branch="auto_route").state == "off"

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

        response = post(api_as(people["huy"]), "/api/rollout/auto_route/on", {"reason": "P3"})

        assert (response.status_code, response.json()["code"]) == (422, "override_reason_required")
        assert response.json()["details"]["unmet"] == ["reroute_rate"]
        assert RolloutFlag.objects.get(branch="auto_route").state == "off"

    def test_a_met_gate_needs_no_override(self, people, api_as, env_live):
        shadow_reviews(people["lan"], people["mai"], decided=40, rerouted=4)

        response = post(api_as(people["huy"]), "/api/rollout/auto_route/on", {"reason": "P3"})

        assert response.status_code == 200
        (request,) = FlagRequest.objects.all()
        assert request.gate_snapshot_at_request[0]["met"] is True

    def test_the_holdout_precision_is_entered_with_evidence(self, people, api_as, env_live):
        client = api_as(people["huy"])
        missing = post(client, "/api/rollout/auto_reply/on", {"reason": "P4"})
        assert missing.json()["code"] == "entered_value_required"

        post(
            client,
            "/api/rollout/auto_reply/on",
            {
                "reason": "P4",
                "gate_override_reason": "thử nghiệm",
                "entered_values": {
                    "holdout_precision": {"value": 0.97, "evidence": "evals/HISTORY.md 2026-11-20"}
                },
            },
        )

        (request,) = FlagRequest.objects.all()
        holdout = next(
            g for g in request.gate_snapshot_at_request if g["metric"] == "holdout_precision"
        )
        assert (holdout["value"], holdout["met"], holdout["entered"]) == (0.97, True, True)

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
    def test_one_manager_changes_a_gate_at_once(self, people, api_as):
        """AC-F9-08 (BR-F9-04, ADR-0043)."""
        gate = RolloutGate.objects.get(branch="auto_route", metric="reroute_rate")

        response = api_as(people["huy"]).patch(
            f"/api/rollout/gates/{gate.id}",
            {"threshold": 0.20, "window_days": 14, "reason": "Thử nới ngưỡng"},
            content_type="application/json",
        )

        assert response.json()["state"] == "approved"
        gate.refresh_from_db()
        assert gate.threshold == 0.20
        assert (
            AuditLog.objects.get(event="rollout_gate_changed").payload["from"]["threshold"] == 0.15
        )

    def test_a_technician_cannot_change_a_gate(self, people, api_as):
        gate = RolloutGate.objects.get(branch="auto_route", metric="reroute_rate")

        response = api_as(people["tu"]).patch(
            f"/api/rollout/gates/{gate.id}",
            {"threshold": 0.5, "reason": "x"},
            content_type="application/json",
        )

        assert response.status_code == 403
        gate.refresh_from_db()
        assert gate.threshold == 0.15


class TestThresholds:
    def test_the_current_thresholds_show_the_loaded_file(self, people, api_as):
        response = api_as(people["tu"]).get("/api/thresholds/current")

        text = Path(django_settings.THRESHOLDS_PATH).read_text(encoding="utf-8")
        assert response.status_code == 200
        assert response.json()["version"] == django_settings.THRESHOLDS.version
        assert response.json()["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert response.json()["yaml"] == text
