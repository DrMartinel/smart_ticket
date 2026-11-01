"""Matrix row for `incident.ticket_not_closed` (F7): the assignee of a ticket close-all couldn't
move."""

from django.db import migrations


def seed(apps, schema_editor):
    MatrixRule = apps.get_model("notifications", "MatrixRule")
    MatrixRule.objects.get_or_create(
        event="incident.ticket_not_closed",
        recipient_kind="assignee",
        channel="in_app",
        defaults={"default_on": True, "mandatory": False},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0002_seed_matrix")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
