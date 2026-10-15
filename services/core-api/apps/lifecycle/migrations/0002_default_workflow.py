"""Seeds the system statuses and the default workflow, and puts existing tickets in it (ADR-0028)."""

from django.db import migrations

from apps.lifecycle.seed import SYSTEM_STATUSES, seed_default_workflow


def seed(apps, schema_editor):
    SystemStatus = apps.get_model("lifecycle", "SystemStatus")
    Workflow = apps.get_model("lifecycle", "Workflow")
    WorkflowStatus = apps.get_model("lifecycle", "WorkflowStatus")
    Ticket = apps.get_model("tickets", "Ticket")

    workflow = seed_default_workflow(SystemStatus, Workflow, WorkflowStatus)
    for status in WorkflowStatus.objects.filter(workflow=workflow):
        Ticket.objects.filter(status=status.key, workflow_status__isnull=True).update(
            workflow_status=status
        )


def unseed(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    Ticket.objects.update(workflow_status=None)
    apps.get_model("lifecycle", "Workflow").objects.filter(name="Default").delete()
    apps.get_model("lifecycle", "SystemStatus").objects.filter(
        name__in=[s[0] for s in SYSTEM_STATUSES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("lifecycle", "0001_initial"),
        ("tickets", "0004_ticket_lifecycle"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
