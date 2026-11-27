"""The workflow rule endpoints: who may read and change them, every refusal, the audit rows and
the preview (ADR-0055)."""

from __future__ import annotations

import json

import pytest

from apps.audit.models import AuditLog
from apps.categories.models import Category
from apps.lifecycle.domain.errors import LifecycleError
from apps.lifecycle.domain.vocabulary import FailureCode, RuleRefusal, TransitionPolicy
from apps.lifecycle.models import Workflow, WorkflowRule
from apps.lifecycle.request_schema import WorkflowIn
from apps.lifecycle.services.config import workflow_config
from apps.lifecycle.tests.conftest import StrictFlow

pytestmark = pytest.mark.django_db

URL = "/api/lifecycle/workflow-rules"


def send(client, method: str, url: str, body: dict | None = None):
    return getattr(client, method)(url, json.dumps(body or {}), content_type="application/json")


@pytest.fixture
def major(manager_user) -> Workflow:
    """An open workflow: a handed-off ticket can always move on."""
    return workflow_config.create_workflow(
        WorkflowIn(name="Major", transition_policy=TransitionPolicy.OPEN), actor=manager_user
    )


@pytest.fixture
def admin(api_as, manager_user):
    return api_as(manager_user)


def create(client, workflow: Workflow, **body):
    return send(client, "post", URL, {"workflow_id": str(workflow.id), "reason": "P1s", **body})


def audits(event: str) -> list[dict]:
    return [a.payload for a in AuditLog.objects.filter(event=event).order_by("occurred_at")]


# ── who may ──


def test_an_employee_cannot_read_the_rules(api_as, employee_user):
    assert api_as(employee_user).get(URL).status_code == 403


def test_a_technician_reads_but_cannot_change_the_rules(api_as, technician_user, major):
    client = api_as(technician_user)

    assert client.get(URL).status_code == 200
    assert client.get(f"{URL}/preview").status_code == 200
    assert create(client, major).status_code == 403
    assert not WorkflowRule.objects.exists()


# ── create, list, edit, reorder, delete ──


def test_a_rule_is_added_after_the_others_and_audited(admin, major):
    first = create(admin, major, priority="P1").json()

    response = create(admin, major, category="network", branch="hitl")

    assert response.status_code == 201
    body = response.json()
    assert (body["order"], body["category"], body["branch"], body["priority"]) == (
        first["order"] + 1,
        "network",
        "hitl",
        None,
    )
    assert (body["workflow_name"], body["changed_by"], body["change_reason"]) == (
        "Major",
        "mgr",
        "P1s",
    )
    assert [r["id"] for r in admin.get(URL).json()] == [first["id"], body["id"]]
    assert [(p["rule"], p["reason"]) for p in audits("workflow_rule_created")][-1] == (
        body["id"],
        "P1s",
    )


def test_an_edit_sets_a_key_back_to_any_and_keeps_the_ones_left_out(admin, major):
    rule = create(admin, major, category="network", priority="P1").json()

    response = send(admin, "patch", f"{URL}/{rule['id']}", {"priority": None, "reason": "all"})

    assert response.status_code == 200
    assert (response.json()["category"], response.json()["priority"]) == ("network", None)
    [payload] = audits("workflow_rule_changed")
    assert (payload["before"]["priority"], payload["after"]["priority"]) == ("P1", None)


def test_an_edit_that_changes_nothing_writes_no_audit_row(admin, major):
    rule = create(admin, major, priority="P1").json()

    send(admin, "patch", f"{URL}/{rule['id']}", {"priority": "P1", "reason": "same"})

    assert audits("workflow_rule_changed") == []


def test_reordering_puts_the_rules_in_the_order_given(admin, major):
    a = create(admin, major, priority="P1").json()["id"]
    b = create(admin, major, priority="P2").json()["id"]

    response = send(admin, "post", f"{URL}/reorder", {"ids": [b, a], "reason": "P2 first"})

    assert response.status_code == 200
    assert [r["id"] for r in response.json()] == [b, a]
    [payload] = audits("workflow_rules_reordered")
    assert (payload["before"], payload["after"]) == ([a, b], [b, a])


def test_a_deleted_rule_is_gone_and_audited(admin, major):
    rule = create(admin, major, priority="P1").json()

    response = send(admin, "delete", f"{URL}/{rule['id']}", {"reason": "not needed"})

    assert response.status_code == 204
    assert not WorkflowRule.objects.exists()
    [payload] = audits("workflow_rule_deleted")
    assert (payload["rule"], payload["reason"]) == (rule["id"], "not needed")


def test_a_rule_may_name_the_default_workflow(admin):
    assert create(admin, Workflow.objects.default(), category="network").status_code == 201


# ── refusals ──


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_change_without_a_reason_is_refused(admin, major, reason):
    rule = create(admin, major, priority="P1").json()

    refusals = [
        create(admin, major, reason=reason),
        send(admin, "patch", f"{URL}/{rule['id']}", {"priority": "P2", "reason": reason}),
        send(admin, "post", f"{URL}/reorder", {"ids": [rule["id"]], "reason": reason}),
        send(admin, "delete", f"{URL}/{rule['id']}", {"reason": reason}),
    ]

    assert [(r.status_code, r.json()["code"]) for r in refusals] == [
        (422, RuleRefusal.REASON_REQUIRED)
    ] * 4
    assert WorkflowRule.objects.get().priority == "P1"


def test_an_unknown_rule_is_refused(admin):
    missing = "00000000-0000-0000-0000-000000000000"

    refusals = [
        send(admin, "patch", f"{URL}/{missing}", {"priority": "P2", "reason": "x"}),
        send(admin, "delete", f"{URL}/{missing}", {"reason": "x"}),
    ]

    assert [(r.status_code, r.json()["code"]) for r in refusals] == [
        (404, RuleRefusal.RULE_NOT_FOUND)
    ] * 2


def test_an_unknown_workflow_is_refused(admin):
    response = send(
        admin,
        "post",
        URL,
        {"workflow_id": "00000000-0000-0000-0000-000000000000", "reason": "x"},
    )

    assert (response.status_code, response.json()["code"]) == (
        422,
        RuleRefusal.WORKFLOW_NOT_FOUND,
    )


def test_a_strict_workflow_with_no_way_out_of_a_handoff_status_is_refused(
    admin, strict: StrictFlow
):
    response = create(admin, strict.workflow, priority="P1")

    assert (response.status_code, response.json()["code"]) == (
        422,
        RuleRefusal.WORKFLOW_HAS_NO_WAY_OUT,
    )
    assert response.json()["details"] == {"statuses": ["auto_routed", "escalated", "reopened"]}
    assert not WorkflowRule.objects.exists()


def test_an_edit_to_a_strict_workflow_with_no_way_out_is_refused(admin, major, strict: StrictFlow):
    rule = create(admin, major).json()

    response = send(
        admin,
        "patch",
        f"{URL}/{rule['id']}",
        {"workflow_id": str(strict.workflow.id), "reason": "x"},
    )

    assert response.json()["code"] == RuleRefusal.WORKFLOW_HAS_NO_WAY_OUT
    assert WorkflowRule.objects.get().workflow == major


@pytest.mark.parametrize("slug", ["billing", "network"])
def test_an_unknown_or_inactive_category_is_refused(admin, major, slug):
    Category.objects.filter(slug="network").update(is_active=False)

    response = create(admin, major, category=slug)

    assert (response.status_code, response.json()["code"]) == (
        422,
        RuleRefusal.UNKNOWN_CATEGORY,
    )


def test_an_auto_reply_rule_is_refused(admin, major):
    response = create(admin, major, branch="auto_reply")

    assert (response.status_code, response.json()["code"]) == (
        422,
        RuleRefusal.BRANCH_NEVER_HANDS_OFF,
    )


@pytest.mark.parametrize("which", ["missing", "twice", "unknown"])
def test_a_reorder_that_does_not_name_every_rule_once_is_refused(admin, major, which):
    a = create(admin, major, priority="P1").json()["id"]
    b = create(admin, major, priority="P2").json()["id"]
    ids = {
        "missing": [b],
        "twice": [b, a, a],
        "unknown": [b, "00000000-0000-0000-0000-000000000000"],
    }[which]

    response = send(admin, "post", f"{URL}/reorder", {"ids": ids, "reason": "x"})

    assert (response.status_code, response.json()["code"]) == (
        422,
        RuleRefusal.ORDER_INCOMPLETE,
    )
    assert [str(r.id) for r in WorkflowRule.objects.in_order()] == [a, b]


def test_a_workflow_a_rule_names_cannot_be_deleted(admin, manager_user, major):
    rule = create(admin, major, priority="P1").json()

    with pytest.raises(LifecycleError) as refused:
        workflow_config.delete_workflow(major, actor=manager_user)

    assert (refused.value.status, refused.value.code) == (409, FailureCode.WORKFLOW_IN_USE)
    assert refused.value.details == {"rules": [rule["id"]]}


# ── preview ──


def test_the_preview_names_the_first_matching_rule(admin, major):
    create(admin, major, priority="P4")
    p1 = create(admin, major, category="network", priority="P1").json()

    body = admin.get(f"{URL}/preview?category=network&branch=auto_route&priority=P1").json()

    assert body == {
        "workflow_id": str(major.id),
        "workflow_name": "Major",
        "selected_by": p1["id"],
        "rule_id": p1["id"],
    }


def test_the_preview_falls_back_to_the_categorys_workflow_then_the_default(admin, major):
    Category.objects.filter(slug="network").update(workflow=major)

    by_category = admin.get(f"{URL}/preview?category=network").json()
    by_default = admin.get(f"{URL}/preview?category=software").json()

    assert (by_category["workflow_name"], by_category["selected_by"]) == ("Major", "category")
    assert (by_default["workflow_id"], by_default["selected_by"], by_default["rule_id"]) == (
        str(Workflow.objects.default().id),
        "default",
        None,
    )


def test_the_preview_counts_an_inactive_rule_only_when_asked(admin, major):
    rule = create(admin, major, priority="P1", is_active=False).json()

    off = admin.get(f"{URL}/preview?priority=P1").json()
    counted = admin.get(f"{URL}/preview?priority=P1&include_inactive=true").json()

    assert (off["selected_by"], counted["selected_by"]) == ("default", rule["id"])
