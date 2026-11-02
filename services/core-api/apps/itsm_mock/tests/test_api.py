"""
Runbook endpoints over HTTP (F12): the catalog a manager approves, and execution as the review
panel calls it. A refused runbook reaches the caller as a coded 4xx, never a 500.
"""

from __future__ import annotations

import pytest

from apps.audit.models import AuditLog
from apps.itsm_mock.models import Runbook, RunbookExecution
from apps.itsm_mock.tests.conftest import approve_catalog, record_decision, runbook_item
from apps.review.models import ReviewAction

NEW_URL = "https://n8n.congty.vn/webhook/restart-service-v2"


def catalog_rows() -> int:
    return AuditLog.objects.filter(event="runbook_catalog_changed").count()


@pytest.mark.django_db
class TestCatalog:
    def test_the_seed_is_listed_unapproved(self, people, api_as):
        response = api_as(people["ha.vt"]).get("/api/itsm/runbooks")

        assert response.status_code == 200
        rows = {r["code"]: r for r in response.json()}
        assert set(rows) == {
            "RB-RESET-PASSWORD",
            "RB-UNLOCK-ACCOUNT",
            "RB-GRANT-ACCESS",
            "RB-RESTART-SERVICE",
        }
        assert not any(r["runnable"] for r in rows.values())
        assert rows["RB-GRANT-ACCESS"]["risk"] == "high"
        assert rows["RB-RESET-PASSWORD"]["target_rule"] == "reporter"

    def test_a_catalog_change_needs_a_manager(self, people, api_as, settings):
        """AC-F12-06, BR-F12-08: tu.dv's new URL waits; the old config runs until a manager
        approves."""
        settings.LIFECYCLE_WEBHOOK_ALLOWED_HOSTS = ["n8n.congty.vn"]
        approve_catalog(people["huy.pq"])
        old = Runbook.objects.get(code="RB-RESTART-SERVICE").config

        changed = api_as(people["tu.dv"]).patch(
            "/api/itsm/runbooks/RB-RESTART-SERVICE",
            {"config": {"url": NEW_URL}},
            content_type="application/json",
        )

        assert changed.status_code == 200
        runbook = Runbook.objects.get(code="RB-RESTART-SERVICE")
        assert runbook.config == old
        assert runbook.is_runnable()
        assert (runbook.pending_change or {})["config"] == {"url": NEW_URL}
        assert catalog_rows() == 1

        approved = api_as(people["quang.nv"]).post("/api/itsm/runbooks/RB-RESTART-SERVICE/approve")

        assert approved.status_code == 200
        runbook.refresh_from_db()
        assert runbook.config == {"url": NEW_URL}
        assert runbook.pending_change is None
        assert runbook.approved_by == people["quang.nv"]

    def test_the_author_of_a_change_cannot_approve_it(self, people, api_as):
        from apps.accounts.models import Capability, UserCapability

        UserCapability.objects.create(
            user=people["huy.pq"], capability=Capability.WORKFLOW_ADMIN.value, source="local"
        )
        client = api_as(people["huy.pq"])
        client.patch(
            "/api/itsm/runbooks/RB-RESET-PASSWORD",
            {"title": "Reset a password"},
            content_type="application/json",
        )

        response = client.post("/api/itsm/runbooks/RB-RESET-PASSWORD/approve")

        assert response.status_code == 403
        assert response.json()["code"] == "self_approval"

    def test_a_new_runbook_waits_for_a_manager(self, people, api_as):
        created = api_as(people["tu.dv"]).post(
            "/api/itsm/runbooks",
            {
                "code": "RB-JIRA",
                "title": "Grant Jira",
                "executor": "keycloak",
                "config": {"action": "add_to_group", "allowed_groups": ["/apps/jira-users"]},
                "required_fields": ["target_username", "group"],
                "target_rule": "any",
                "risk": "high",
            },
            content_type="application/json",
        )

        assert created.status_code == 201
        assert created.json()["runnable"] is False
        assert catalog_rows() == 1

    @pytest.mark.parametrize(
        "config",
        [
            {"action": "add_to_group", "allowed_groups": ["/it/access/lead"]},
            {"action": "add_to_group", "allowed_groups": ["/apps/vpn-users", "/finance"]},
        ],
    )
    def test_a_group_carrying_rights_is_never_grantable(self, people, api_as, config):
        response = api_as(people["tu.dv"]).patch(
            "/api/itsm/runbooks/RB-GRANT-ACCESS",
            {"config": config},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert response.json()["code"] == "group_not_allowed"
        assert Runbook.objects.get(code="RB-GRANT-ACCESS").pending_change is None
        assert catalog_rows() == 0

    @pytest.mark.parametrize(
        "change",
        [
            {"config": {"url": "https://evil.example.com/hook"}},
            {"executor": "keycloak", "config": {"action": "reset_password_to", "value": "x"}},
            {"required_fields": ["host"], "target_rule": "reporter"},
        ],
    )
    def test_a_definition_no_executor_can_run_is_refused(self, people, api_as, settings, change):
        settings.LIFECYCLE_WEBHOOK_ALLOWED_HOSTS = ["n8n.congty.vn"]
        response = api_as(people["tu.dv"]).patch(
            "/api/itsm/runbooks/RB-RESTART-SERVICE", change, content_type="application/json"
        )

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_config"

    def test_only_a_workflow_admin_drafts_and_only_a_manager_approves(self, people, api_as):
        drafted = api_as(people["ha.vt"]).patch(
            "/api/itsm/runbooks/RB-RESET-PASSWORD",
            {"title": "x" * 5},
            content_type="application/json",
        )
        approved = api_as(people["tu.dv"]).post("/api/itsm/runbooks/RB-RESET-PASSWORD/approve")

        assert drafted.status_code == 403
        assert approved.status_code == 403

    def test_nothing_waiting_is_nothing_to_approve(self, people, api_as):
        approve_catalog(people["huy.pq"])

        response = api_as(people["quang.nv"]).post("/api/itsm/runbooks/RB-RESET-PASSWORD/approve")

        assert response.status_code == 409
        assert response.json()["code"] == "nothing_to_approve"


@pytest.mark.django_db
class TestExecute:
    def test_a_refused_target_is_a_422_with_its_code(self, people, iam, api_as):
        """AC-F12-01 over HTTP."""
        approve_catalog(people["huy.pq"])
        item = runbook_item(people["lan.nt"], draft_payload={"target_username": "huy.pq"})
        record_decision(item, people["ha.vt"], ReviewAction.APPROVE)

        response = api_as(people["ha.vt"]).post(
            f"/api/itsm/review-items/{item.id}/execute",
            {"payload": {"target_username": "huy.pq"}},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert response.json()["code"] == "target_not_reporter"
        assert iam.calls == []

    def test_an_execution_is_returned_and_shown_on_the_panel(self, people, api_as):
        approve_catalog(people["huy.pq"])
        item = runbook_item(people["lan.nt"])
        record_decision(item, people["ha.vt"], ReviewAction.APPROVE)
        client = api_as(people["ha.vt"])

        response = client.post(
            f"/api/itsm/review-items/{item.id}/execute",
            {"payload": {"target_username": "lan.nt"}},
            content_type="application/json",
        )
        panel = client.get(f"/api/itsm/review-items/{item.id}/runbook").json()

        assert response.status_code == 200
        body = response.json()
        assert body["runbook_id"] == "RB-RESET-PASSWORD"
        assert body["state"] == "queued"
        assert body["approved_by"] == "ha.vt"
        assert body["executed_payload"] == {"target_username": "lan.nt"}
        assert panel["runbook_id"] == "RB-RESET-PASSWORD"
        assert panel["draft_payload"] == {"target_username": "lan.nt"}
        assert panel["approved"] is True
        assert panel["runbook"]["runnable"] is True
        assert [e["id"] for e in panel["executions"]] == [body["id"]]

    def test_an_unapproved_runbook_is_a_422(self, people, api_as):
        approve_catalog(people["huy.pq"])
        item = runbook_item(people["lan.nt"])

        response = api_as(people["ha.vt"]).post(
            f"/api/itsm/review-items/{item.id}/execute",
            {"payload": {"target_username": "lan.nt"}},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert response.json()["code"] == "not_approved"
        assert not RunbookExecution.objects.exists()

    def test_a_missing_review_item_is_a_404(self, people, api_as):
        import uuid

        response = api_as(people["ha.vt"]).post(
            f"/api/itsm/review-items/{uuid.uuid4()}/execute",
            {"payload": {}},
            content_type="application/json",
        )

        assert response.status_code == 404
