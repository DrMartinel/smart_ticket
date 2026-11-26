"""Matrix rows for the F17 event a staff change on a ticket's resource raises: it goes to the
ticket's requester."""

from django.db import migrations

ROWS = [
    ("infra.change_on_your_resource", "requester", "in_app"),
    ("infra.change_on_your_resource", "requester", "email"),
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


def unseed(apps, schema_editor):
    MatrixRule = apps.get_model("notifications", "MatrixRule")
    MatrixRule.objects.filter(event__in={event for event, _, _ in ROWS}).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0007_access_events")]

    operations = [migrations.RunPython(seed, unseed)]
