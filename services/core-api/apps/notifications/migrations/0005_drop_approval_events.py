"""Drops the matrix rows, preferences and templates of the four approval events (ADR-0043)."""

from django.db import migrations

EVENTS = (
    "approval.requested",
    "rollout.flag_requested",
    "thresholds.cr_pending",
    "runbook.second_approval_requested",
)


def drop(apps, schema_editor):
    for model in ("MatrixRule", "Preference", "Template"):
        apps.get_model("notifications", model).objects.filter(event__in=EVENTS).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_runbook_events")]

    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
