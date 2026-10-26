"""Seeds the matrix with the catalog's default cells (F4 §f), each on."""

from django.db import migrations

# (event, recipient_kind, channel, mandatory) as the catalog stood when F4 shipped.
CELLS = [
    ("ticket.received", "requester", "in_app", False),
    ("ticket.received", "requester", "email", False),
    ("ticket.assigned", "assignee", "in_app", False),
    ("ticket.assigned", "assignee", "email", False),
    ("ticket.reassigned", "assignee", "in_app", False),
    ("ticket.reassigned", "assignee", "email", False),
    ("ticket.reassigned", "previous_assignee", "in_app", False),
    ("ticket.reassigned", "team_lead", "in_app", False),
    ("ticket.unassigned", "team_lead", "in_app", False),
    ("ticket.unassigned", "team_lead", "email", False),
    ("ticket.public_comment", "requester", "in_app", False),
    ("ticket.public_comment", "requester", "email", False),
    ("ticket.requester_replied", "assignee", "in_app", False),
    ("ticket.requester_replied", "assignee", "email", False),
    ("ticket.status_changed", "requester", "in_app", False),
    ("ticket.resolved", "requester", "in_app", False),
    ("ticket.resolved", "requester", "email", False),
    ("ticket.reopened", "assignee", "in_app", False),
    ("ticket.reopened", "team_lead", "in_app", False),
    ("ticket.rated_low", "team_lead", "in_app", False),
    ("ticket.rated_low", "team_lead", "email", False),
    ("sla.warning", "assignee", "in_app", False),
    ("sla.warning", "assignee", "email", False),
    ("sla.warning", "team_lead", "in_app", False),
    ("sla.breached", "assignee", "in_app", False),
    ("sla.breached", "assignee", "email", False),
    ("sla.breached", "team_lead", "in_app", False),
    ("sla.breached", "team_lead", "email", False),
    ("sla.breached_escalated", "manager", "in_app", False),
    ("sla.breached_escalated", "manager", "email", False),
    ("sla.holidays_missing", "workflow_admins", "in_app", False),
    ("sla.holidays_missing", "workflow_admins", "email", False),
    ("assignment.failed", "team_lead", "in_app", False),
    ("approval.requested", "approver", "in_app", True),
    ("approval.requested", "approver", "email", False),
    ("security.alert", "security", "in_app", True),
    ("security.alert", "security", "email", True),
    ("identity.break_glass_used", "security", "in_app", True),
    ("identity.break_glass_used", "security", "email", True),
    ("incident.broadcast", "linked_requesters", "in_app", True),
    ("incident.broadcast", "linked_requesters", "email", True),
    ("incident.proposed", "incident_managers", "in_app", True),
    ("incident.proposed", "incident_managers", "email", True),
    ("incident.sla_breached", "manager", "in_app", False),
    ("incident.sla_breached", "manager", "email", False),
    ("security.credential_exposed", "requester", "in_app", True),
    ("security.credential_exposed", "requester", "email", True),
    ("security.ack_overdue", "security", "in_app", True),
    ("security.ack_overdue", "security", "email", True),
    ("kb.review_requested", "kb_editors", "in_app", False),
    ("kb.review_requested", "manager", "in_app", False),
    ("kb.authority_needed", "manager", "in_app", False),
    ("kb.authority_needed", "manager", "email", False),
    ("kb.gaps_ready", "kb_editors", "in_app", False),
    ("kb.gaps_ready", "kb_editors", "email", False),
    ("rollout.flag_requested", "manager", "in_app", False),
    ("rollout.flag_requested", "manager", "email", False),
    ("rollout.flag_changed", "manager", "in_app", True),
    ("rollout.flag_changed", "manager", "email", False),
    ("rollout.flag_changed", "security", "in_app", True),
    ("rollout.flag_changed", "security", "email", False),
    ("rollout.gate_unmet", "manager", "in_app", False),
    ("rollout.gate_unmet", "manager", "email", False),
    ("thresholds.cr_pending", "manager", "in_app", False),
    ("thresholds.unapproved", "manager", "in_app", True),
    ("thresholds.unapproved", "manager", "email", True),
    ("thresholds.unapproved", "security", "in_app", True),
    ("thresholds.unapproved", "security", "email", True),
    ("report.weekly", "manager", "email", False),
]


def seed(apps, schema_editor):
    MatrixRule = apps.get_model("notifications", "MatrixRule")
    MatrixRule.objects.bulk_create(
        [
            MatrixRule(
                event=event,
                recipient_kind=kind,
                channel=channel,
                default_on=True,
                mandatory=mandatory,
            )
            for event, kind, channel, mandatory in CELLS
        ],
        ignore_conflicts=True,
    )


def unseed(apps, schema_editor):
    apps.get_model("notifications", "MatrixRule").objects.filter(updated_by__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
