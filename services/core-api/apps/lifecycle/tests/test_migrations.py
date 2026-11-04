"""Migration 0006: each workflow status takes its kind from the system status it was based on.
Migration 0007: no saved action holds a move for an approver."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)

BEFORE = [("lifecycle", "0005_waiting_on_requester")]
AFTER = [("lifecycle", "0006_status_kind")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture(autouse=True)
def back_to_the_latest():
    yield
    executor = MigrationExecutor(connection)
    migrate(executor.loader.graph.leaf_nodes())


def test_every_status_keeps_what_its_system_status_meant():
    old = migrate(BEFORE)
    SystemStatus = old.get_model("lifecycle", "SystemStatus")
    WorkflowStatus = old.get_model("lifecycle", "WorkflowStatus")
    bases = dict(WorkflowStatus.objects.values_list("key", "base__name"))
    meant = {
        name: "completed" if done else "backlog" if backlog else "active"
        for name, backlog, done in SystemStatus.objects.values_list(
            "name", "is_backlog", "is_completed"
        )
    }

    new = migrate(AFTER)

    kinds = dict(new.get_model("lifecycle", "WorkflowStatus").objects.values_list("key", "kind"))
    assert kinds == {key: meant[base] for key, base in bases.items()}
    assert {kinds["new"], kinds["auto_replied"], kinds["on_hold"]} == {
        "backlog",
        "completed",
        "active",
    }


def test_a_saved_action_naming_the_system_status_names_the_kind():
    old = migrate(BEFORE)
    WorkflowStatus = old.get_model("lifecycle", "WorkflowStatus")
    WorkflowAction = old.get_model("lifecycle", "WorkflowAction")
    action = WorkflowAction.objects.create(
        status=WorkflowStatus.objects.get(key="resolved"),
        action="send_email",
        params={"to": "a@b.c", "subject": "Now {{ticket.baseStatus}}", "body": "x"},
    )

    new = migrate(AFTER)

    saved = new.get_model("lifecycle", "WorkflowAction").objects.get(pk=action.pk)
    assert saved.params["subject"] == "Now {{ticket.statusKind}}"


def test_a_saved_approval_action_is_dropped():
    old = migrate(AFTER)
    WorkflowStatus = old.get_model("lifecycle", "WorkflowStatus")
    WorkflowAction = old.get_model("lifecycle", "WorkflowAction")
    action = WorkflowAction.objects.create(
        status=WorkflowStatus.objects.get(key="resolved"),
        action="require_approval",
        params={"approvers": "manager1"},
    )

    new = migrate([("lifecycle", "0007_drop_approvals")])

    assert not new.get_model("lifecycle", "WorkflowAction").objects.filter(pk=action.pk).exists()
