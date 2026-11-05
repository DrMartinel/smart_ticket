"""Adds the requester's department to each ticket's facts, filled from the ticket."""

from django.db import migrations, models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce


def backfill(apps, schema_editor):
    TicketFacts = apps.get_model("reports", "TicketFacts")
    Ticket = apps.get_model("tickets", "Ticket")
    TicketFacts.objects.update(
        department=Coalesce(
            Subquery(
                Ticket.objects.filter(pk=OuterRef("ticket_id")).values(
                    "requester_department__code"
                )[:1]
            ),
            Value(""),
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
        ("tickets", "0011_ticket_requester_department"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketfacts",
            name="department",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
