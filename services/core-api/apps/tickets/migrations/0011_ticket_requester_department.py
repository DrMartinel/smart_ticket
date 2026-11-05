"""Adds the reporter's department at submit, filled from each reporter's current department."""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def backfill(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    User = apps.get_model("accounts", "User")
    Ticket.objects.update(
        requester_department_id=Subquery(
            User.objects.filter(pk=OuterRef("reporter_id")).values("department_id")[:1]
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_review_timestamps"),
        ("tickets", "0010_incident_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="requester_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="accounts.department",
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
