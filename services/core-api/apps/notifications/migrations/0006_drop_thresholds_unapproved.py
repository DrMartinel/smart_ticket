"""Drops the matrix rows, preferences and templates of `thresholds.unapproved` (ADR-0044)."""

from django.db import migrations

EVENTS = ("thresholds.unapproved",)


def drop(apps, schema_editor):
    for model in ("MatrixRule", "Preference", "Template"):
        apps.get_model("notifications", model).objects.filter(event__in=EVENTS).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0005_drop_approval_events")]

    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
