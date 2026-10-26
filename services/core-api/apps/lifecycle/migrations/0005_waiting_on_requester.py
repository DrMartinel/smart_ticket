"""Adds `waiting_on_requester` (base On hold, pauses the SLA) to every workflow, and turns saved
`set_sla` actions' wall-clock `offset_hours` into business `business_hours` (F1, ADR-0030)."""

from django.db import migrations

KEY = "waiting_on_requester"


def forward(apps, schema_editor):
    SystemStatus = apps.get_model("lifecycle", "SystemStatus")
    Workflow = apps.get_model("lifecycle", "Workflow")
    WorkflowStatus = apps.get_model("lifecycle", "WorkflowStatus")
    WorkflowAction = apps.get_model("lifecycle", "WorkflowAction")
    on_hold = SystemStatus.objects.filter(name="On hold").first()
    if on_hold is not None:
        for workflow in Workflow.objects.all():
            if workflow.statuses.filter(key=KEY).exists():
                workflow.statuses.filter(key=KEY).update(pauses_sla=True)
                continue
            last = workflow.statuses.order_by("-order").values_list("order", flat=True).first()
            WorkflowStatus.objects.create(
                workflow=workflow,
                base=on_hold,
                key=KEY,
                name="Waiting on requester",
                color="#A78BFA",
                order=(last or 0) + 1,
                pauses_sla=True,
            )
    for action in WorkflowAction.objects.filter(action="set_sla"):
        params = dict(action.params)
        if "offset_hours" in params:
            params["business_hours"] = params.pop("offset_hours")
            params.setdefault("reason", "migrated from a wall-clock offset (ADR-0030)")
            action.params = params
            action.save(update_fields=["params"])


def backward(apps, schema_editor):
    apps.get_model("lifecycle", "WorkflowStatus").objects.filter(
        key=KEY, tickets__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("lifecycle", "0004_workflowstatus_pauses_sla")]

    operations = [migrations.RunPython(forward, backward)]
