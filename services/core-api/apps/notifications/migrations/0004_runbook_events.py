"""Matrix rows for the F12 runbook events: a second approval for managers, the outcome for the
assignee."""

from django.db import migrations

ROWS = [
    ("runbook.second_approval_requested", "manager", "in_app"),
    ("runbook.second_approval_requested", "manager", "email"),
    ("runbook.finished", "assignee", "in_app"),
]


def seed(apps, schema_editor):
    MatrixRule = apps.get_model("notifications", "MatrixRule")
    for event, kind, channel in ROWS:
        MatrixRule.objects.get_or_create(
            event=event,
            recipient_kind=kind,
            channel=channel,
            defaults={"default_on": True, "mandatory": False},
        )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_incident_ticket_not_closed")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
