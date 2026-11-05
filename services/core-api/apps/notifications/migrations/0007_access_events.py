"""Matrix rows for the F14 access events: each goes to the person it is about."""

from django.db import migrations

ROWS = [
    ("access.granted", "subject", "in_app"),
    ("access.granted", "subject", "email"),
    ("access.grant_expiring", "subject", "in_app"),
    ("access.grant_expiring", "subject", "email"),
    ("access.review_assigned", "subject", "in_app"),
    ("access.review_assigned", "subject", "email"),
    ("access.review_closing", "subject", "in_app"),
    ("access.review_closing", "subject", "email"),
    ("org.person_moved", "subject", "in_app"),
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
    dependencies = [("notifications", "0006_drop_thresholds_unapproved")]

    operations = [migrations.RunPython(seed, unseed)]
