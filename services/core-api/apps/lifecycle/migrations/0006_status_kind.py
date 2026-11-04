"""Gives every workflow status its own kind from its system status, drops the system statuses,
and renames the `ticket.baseStatus` placeholder in saved actions (ADR-0040)."""

import django.db.models.deletion
from django.db import migrations, models

OLD_PLACEHOLDER = "ticket.baseStatus"
NEW_PLACEHOLDER = "ticket.statusKind"

# kind -> (name, colour, order) of the system status a reversed migration links it to
BASES = {
    "backlog": ("Intake", "#6B7280", 1),
    "active": ("Open", "#3B82F6", 2),
    "completed": ("Resolved", "#22C55E", 3),
}


def kind_of(base):
    if base.is_completed:
        return "completed"
    return "backlog" if base.is_backlog else "active"


def rename_placeholder(apps, old, new):
    WorkflowAction = apps.get_model("lifecycle", "WorkflowAction")
    for action in WorkflowAction.objects.all():
        params = {
            k: v.replace(old, new) if isinstance(v, str) else v for k, v in action.params.items()
        }
        if params != action.params:
            action.params = params
            action.save(update_fields=["params"])


def forward(apps, schema_editor):
    WorkflowStatus = apps.get_model("lifecycle", "WorkflowStatus")
    for status in WorkflowStatus.objects.select_related("base"):
        status.kind = kind_of(status.base)
        status.save(update_fields=["kind"])
    rename_placeholder(apps, OLD_PLACEHOLDER, NEW_PLACEHOLDER)


def backward(apps, schema_editor):
    SystemStatus = apps.get_model("lifecycle", "SystemStatus")
    WorkflowStatus = apps.get_model("lifecycle", "WorkflowStatus")
    bases = {}
    for kind, (name, color, order) in BASES.items():
        bases[kind], _ = SystemStatus.objects.get_or_create(
            name=name,
            defaults={
                "color": color,
                "order": order,
                "is_backlog": kind == "backlog",
                "is_completed": kind == "completed",
            },
        )
    for status in WorkflowStatus.objects.all():
        status.base = bases[status.kind]
        status.save(update_fields=["base"])
    rename_placeholder(apps, NEW_PLACEHOLDER, OLD_PLACEHOLDER)


class Migration(migrations.Migration):
    dependencies = [("lifecycle", "0005_waiting_on_requester")]

    operations = [
        migrations.AddField(
            model_name="workflowstatus",
            name="kind",
            field=models.CharField(
                choices=[("backlog", "backlog"), ("active", "active"), ("completed", "completed")],
                default="active",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="workflowstatus",
            name="base",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_statuses",
                to="lifecycle.systemstatus",
            ),
        ),
        migrations.RunPython(forward, backward),
        migrations.RemoveConstraint(
            model_name="systemstatus",
            name="chk_system_status_backlog_xor_completed",
        ),
        migrations.RemoveField(
            model_name="workflowstatus",
            name="base",
        ),
        migrations.AlterField(
            model_name="actionrun",
            name="error_code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("status_not_in_workflow", "status_not_in_workflow"),
                    ("pipeline_status_target", "pipeline_status_target"),
                    ("pipeline_status_locked", "pipeline_status_locked"),
                    ("ticket_in_triage", "ticket_in_triage"),
                    ("transition_not_allowed", "transition_not_allowed"),
                    ("transition_exists", "transition_exists"),
                    ("rule_violation", "rule_violation"),
                    ("ticket_transforming", "ticket_transforming"),
                    ("version_conflict", "version_conflict"),
                    ("status_in_use", "status_in_use"),
                    ("workflow_in_use", "workflow_in_use"),
                    ("field_in_use", "field_in_use"),
                    ("unmapped_statuses", "unmapped_statuses"),
                    ("invalid_config", "invalid_config"),
                    ("name_taken", "name_taken"),
                    ("conflict", "conflict"),
                    ("invalid_field_value", "invalid_field_value"),
                    ("nothing_to_retry", "nothing_to_retry"),
                    ("transfer_in_progress", "transfer_in_progress"),
                    ("not_found", "not_found"),
                    ("same_workflow", "same_workflow"),
                    ("self_approval", "self_approval"),
                    ("stale_transfer", "stale_transfer"),
                    ("not_an_approver", "not_an_approver"),
                    ("not_awaiting", "not_awaiting"),
                    ("bad_callback_token", "bad_callback_token"),
                    ("invalid_param", "invalid_param"),
                    ("action_failed", "action_failed"),
                    ("action_crashed", "action_crashed"),
                    ("action_aborted", "action_aborted"),
                    ("approval_rejected", "approval_rejected"),
                    ("approval_expired", "approval_expired"),
                    ("callback_failed", "callback_failed"),
                    ("callback_timeout", "callback_timeout"),
                    ("run_timeout", "run_timeout"),
                    ("automation_depth_exceeded", "automation_depth_exceeded"),
                    ("superseded_by_pipeline", "superseded_by_pipeline"),
                    ("webhook_host_refused", "webhook_host_refused"),
                ],
                max_length=40,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="transfer",
            name="failure_code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("status_not_in_workflow", "status_not_in_workflow"),
                    ("pipeline_status_target", "pipeline_status_target"),
                    ("pipeline_status_locked", "pipeline_status_locked"),
                    ("ticket_in_triage", "ticket_in_triage"),
                    ("transition_not_allowed", "transition_not_allowed"),
                    ("transition_exists", "transition_exists"),
                    ("rule_violation", "rule_violation"),
                    ("ticket_transforming", "ticket_transforming"),
                    ("version_conflict", "version_conflict"),
                    ("status_in_use", "status_in_use"),
                    ("workflow_in_use", "workflow_in_use"),
                    ("field_in_use", "field_in_use"),
                    ("unmapped_statuses", "unmapped_statuses"),
                    ("invalid_config", "invalid_config"),
                    ("name_taken", "name_taken"),
                    ("conflict", "conflict"),
                    ("invalid_field_value", "invalid_field_value"),
                    ("nothing_to_retry", "nothing_to_retry"),
                    ("transfer_in_progress", "transfer_in_progress"),
                    ("not_found", "not_found"),
                    ("same_workflow", "same_workflow"),
                    ("self_approval", "self_approval"),
                    ("stale_transfer", "stale_transfer"),
                    ("not_an_approver", "not_an_approver"),
                    ("not_awaiting", "not_awaiting"),
                    ("bad_callback_token", "bad_callback_token"),
                    ("invalid_param", "invalid_param"),
                    ("action_failed", "action_failed"),
                    ("action_crashed", "action_crashed"),
                    ("action_aborted", "action_aborted"),
                    ("approval_rejected", "approval_rejected"),
                    ("approval_expired", "approval_expired"),
                    ("callback_failed", "callback_failed"),
                    ("callback_timeout", "callback_timeout"),
                    ("run_timeout", "run_timeout"),
                    ("automation_depth_exceeded", "automation_depth_exceeded"),
                    ("superseded_by_pipeline", "superseded_by_pipeline"),
                    ("webhook_host_refused", "webhook_host_refused"),
                ],
                max_length=40,
                null=True,
            ),
        ),
        migrations.DeleteModel(
            name="SystemStatus",
        ),
    ]
