"""Lifecycle endpoints over HTTP: role gates, response shapes, and refusals as `{code, message, details}`."""

from __future__ import annotations

import json

import pytest

from apps.lifecycle.models import ActionRun, Workflow
from apps.lifecycle.request_schema import FieldIn, TransitionPatch
from apps.lifecycle.tests.conftest import actions, put_in, status_of
from apps.lifecycle.utils.actions import HANDLERS
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.rules import FieldType
from apps.lifecycle.utils.vocabulary import PipelineStatus, RunState

pytestmark = pytest.mark.django_db

BASE = "/api/lifecycle"


def post(client, url, body=None):
    return client.post(url, json.dumps(body or {}), content_type="application/json")


def put(client, url, body):
    return client.put(url, json.dumps(body), content_type="application/json")


def test_an_employee_cannot_read_workflows(api_as, employee_user):
    assert api_as(employee_user).get(f"{BASE}/workflows").status_code == 403


def test_a_technician_reads_but_cannot_change_workflows(api_as, technician_user):
    client = api_as(technician_user)

    assert client.get(f"{BASE}/workflows").status_code == 200
    assert post(client, f"{BASE}/workflows", {"name": "Mine"}).status_code == 403


def test_a_manager_creates_a_workflow_with_its_pipeline_statuses(api_as, manager_user):
    response = post(api_as(manager_user), f"{BASE}/workflows", {"name": "Hardware"})

    assert response.status_code == 201
    body = response.json()
    assert {s["key"] for s in body["statuses"]} == {s.value for s in PipelineStatus}
    assert all(s["is_pipeline"] for s in body["statuses"])


def test_the_workflow_detail_carries_statuses_transitions_and_fields(
    api_as, strict, technician_user
):
    workflow_config.add_field(strict.workflow, FieldIn(name="Note", field_type=FieldType.TEXT))

    body = api_as(technician_user).get(f"{BASE}/workflows/{strict.workflow.id}").json()

    assert {"statuses", "transitions", "fields"} <= set(body)
    assert len(body["transitions"]) == 3
    assert body["fields"][0]["name"] == "Note"


def test_the_catalog_lists_every_action_with_its_parameters(api_as, technician_user):
    body = api_as(technician_user).get(f"{BASE}/catalog").json()

    assert {a["code"] for a in body["actions"]} == {c.value for c in HANDLERS}
    webhook = next(a for a in body["actions"] if a["code"] == "call_webhook")
    assert webhook["blocking"] is True
    assert {p["name"] for p in webhook["params"]} == {"url", "method", "body"}
    assert "ticket.subject" in body["variables"]


def test_a_refusal_comes_back_as_code_message_and_details(api_as, ticket, technician_user):
    target = status_of(Workflow.objects.default(), "auto_replied")

    response = post(
        api_as(technician_user),
        f"{BASE}/tickets/{ticket.public_id}/move",
        {"status_id": str(target.id)},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "pipeline_status_target"
    assert set(response.json()) == {"code", "message", "details"}


def test_a_move_returns_the_tickets_new_position(api_as, ticket, technician_user):
    target = status_of(Workflow.objects.default(), "in_progress")

    response = post(
        api_as(technician_user),
        f"{BASE}/tickets/{ticket.public_id}/move",
        {"status_id": str(target.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["workflow_status"]["key"] == "in_progress"
    assert body["waiting_transform"] is False


def test_only_a_manager_may_force_a_move(api_as, ticket, technician_user):
    target = status_of(Workflow.objects.default(), "in_progress")

    response = post(
        api_as(technician_user),
        f"{BASE}/tickets/{ticket.public_id}/move",
        {"status_id": str(target.id), "force": True},
    )

    assert response.status_code == 403


def test_the_moves_endpoint_lists_only_what_a_person_may_do(
    api_as, ticket, strict, technician_user
):
    put_in(ticket, strict.working)

    body = api_as(technician_user).get(f"{BASE}/tickets/{ticket.public_id}/transitions").json()

    assert sorted(o["status"]["key"] for o in body) == sorted([strict.hold.key, strict.done.key])
    assert {o["direction"] for o in body} == {"forward"}


def test_writing_fields_returns_the_stored_values(api_as, ticket, technician_user):
    field = workflow_config.add_field(
        Workflow.objects.default(), FieldIn(name="Cost", field_type=FieldType.NUMBER)
    )

    response = put(
        api_as(technician_user),
        f"{BASE}/tickets/{ticket.public_id}/fields",
        {"values": {str(field.id): 12}},
    )

    assert response.status_code == 200
    assert response.json()["field_values"] == [
        {"field_id": str(field.id), "field_name": "Cost", "value": 12}
    ]


def test_deleting_a_status_in_use_reports_how_many_tickets(api_as, ticket, strict, manager_user):
    put_in(ticket, strict.hold)

    response = api_as(manager_user).delete(f"{BASE}/statuses/{strict.hold.id}")

    assert response.status_code == 409
    assert response.json() == {
        "code": "status_in_use",
        "message": "tickets are in this status: pass migrate_to",
        "details": {"ticket_count": 1},
    }


def n8n_run(ticket, strict, celery, webhooks):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "trigger_n8n",
                    "params": {"webhook_url": "http://localhost/n8n"},
                    "position": "before",
                }
            )
        ),
    )
    put_in(ticket, strict.working)
    from apps.lifecycle.utils.engine import lifecycle
    from apps.lifecycle.utils.vocabulary import Trigger

    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()
    return ActionRun.objects.get(transfer__ticket=ticket), webhooks.calls[0]["body"]


def test_a_callback_needs_no_login_but_its_token(client, ticket, strict, celery, webhooks):
    run, sent = n8n_run(ticket, strict, celery, webhooks)
    url = sent["callbackUrl"].removeprefix("http://localhost:8000")
    assert url == f"{BASE}/action-runs/{run.id}/callback"

    forged = client.post(
        url,
        json.dumps({"success": True}),
        content_type="application/json",
        HTTP_X_LIFECYCLE_TOKEN="x",
    )
    assert forged.status_code == 403
    assert forged.json()["code"] == "bad_callback_token"

    ok = client.post(
        url,
        json.dumps({"success": True}),
        content_type="application/json",
        HTTP_X_LIFECYCLE_TOKEN=sent["callbackToken"],
    )
    assert ok.status_code == 204
    run.refresh_from_db()
    assert run.state == RunState.SUCCEEDED.value


def test_an_approver_sees_and_answers_their_approvals(
    api_as, ticket, strict, celery, manager_user, technician_user
):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "require_approval",
                    "params": {"approvers": manager_user.username},
                    "position": "before",
                }
            )
        ),
    )
    put_in(ticket, strict.working)
    post(
        api_as(technician_user),
        f"{BASE}/tickets/{ticket.public_id}/move",
        {"status_id": str(strict.done.id)},
    )
    celery.drain()
    client = api_as(manager_user)

    [approval] = client.get(f"{BASE}/approvals/mine").json()
    assert approval["ticket_public_id"] == ticket.public_id

    response = post(client, f"{BASE}/approvals/{approval['id']}/approve", {"comment": "go"})
    celery.drain()

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert client.get(f"{BASE}/tickets/{ticket.public_id}").json()["status"] == strict.done.key


def test_a_failed_transfer_lands_in_the_failed_queue(
    api_as, ticket, strict, celery, webhooks, technician_user
):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "call_webhook",
                    "params": {"url": "http://localhost/x"},
                    "position": "before",
                }
            )
        ),
    )
    webhooks.status = 400
    put_in(ticket, strict.working)
    post(
        api_as(technician_user),
        f"{BASE}/tickets/{ticket.public_id}/move",
        {"status_id": str(strict.done.id)},
    )
    celery.drain()

    [failed] = api_as(technician_user).get(f"{BASE}/transfers/failed").json()

    assert failed["ticket_public_id"] == ticket.public_id
    assert failed["failure_code"] == "action_aborted"
    assert failed["runs"][0]["state"] == "failed"
