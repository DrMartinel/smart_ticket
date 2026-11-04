"""Drops the require_approval action (ADR-0043): its configured actions, the moves it holds, and
its table."""

from django.db import migrations, models
from django.utils import timezone

REASON = "approvals were removed (ADR-0043); move the ticket again"


def release(apps, schema_editor):
    """Deletes require_approval actions and cancels the moves they hold."""
    WorkflowAction = apps.get_model("lifecycle", "WorkflowAction")
    ActionRun = apps.get_model("lifecycle", "ActionRun")
    Transfer = apps.get_model("lifecycle", "Transfer")
    Ticket = apps.get_model("tickets", "Ticket")
    WorkflowAction.objects.filter(action="require_approval").delete()
    held = ActionRun.objects.filter(action="require_approval", state__in=["queued", "running"])
    transfers = list(held.values_list("transfer_id", flat=True))
    tickets = list(held.values_list("ticket_id", flat=True))
    now = timezone.now()
    held.update(state="skipped", finished_at=now, awaiting_until=None)
    Transfer.objects.filter(id__in=transfers, state__in=["pending", "committed"]).update(
        state="cancelled", failure_code="approval_rejected", failure_reason=REASON, finished_at=now
    )
    Ticket.objects.filter(id__in=tickets).update(waiting_transform=False)


class Migration(migrations.Migration):
    dependencies = [
        ("lifecycle", "0006_status_kind"),
        ("tickets", "0010_incident_lifecycle"),
    ]

    operations = [
        migrations.RunPython(release, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="actionrun",
            name="action",
            field=models.CharField(
                choices=[
                    ("set_field", "set_field"),
                    ("clear_field", "clear_field"),
                    ("assign_user", "assign_user"),
                    ("assign_team", "assign_team"),
                    ("set_sla", "set_sla"),
                    ("move_status", "move_status"),
                    ("change_workflow", "change_workflow"),
                    ("send_email", "send_email"),
                    ("call_webhook", "call_webhook"),
                    ("trigger_n8n", "trigger_n8n"),
                ],
                max_length=30,
            ),
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
                    ("stale_transfer", "stale_transfer"),
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
                    ("stale_transfer", "stale_transfer"),
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
            model_name="workflowaction",
            name="action",
            field=models.CharField(
                choices=[
                    ("set_field", "set_field"),
                    ("clear_field", "clear_field"),
                    ("assign_user", "assign_user"),
                    ("assign_team", "assign_team"),
                    ("set_sla", "set_sla"),
                    ("move_status", "move_status"),
                    ("change_workflow", "change_workflow"),
                    ("send_email", "send_email"),
                    ("call_webhook", "call_webhook"),
                    ("trigger_n8n", "trigger_n8n"),
                ],
                max_length=30,
            ),
        ),
        migrations.DeleteModel(
            name="ApprovalRequest",
        ),
    ]
