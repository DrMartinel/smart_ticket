"""Incidents from before F7 (F7 §g): an `open` one becomes `confirmed` (they were real), its
tickets become links, and its centroid is their mean embedding."""

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Incident = apps.get_model("tickets", "Incident")
    Ticket = apps.get_model("tickets", "Ticket")
    Embedding = apps.get_model("tickets", "TicketEmbedding")
    Link = apps.get_model("incidents", "IncidentLink")
    now = timezone.now()
    for incident in Incident.objects.all():
        if incident.status == "open":
            incident.status = "confirmed"
            incident.confirmed_at = incident.created_at
        tickets = list(Ticket.objects.filter(incident=incident))
        for ticket in tickets:
            Link.objects.get_or_create(
                incident=incident,
                ticket=ticket,
                unlinked_at=None,
                defaults={"linked_by": "detector"},
            )
        vectors = [
            list(v)
            for v in Embedding.objects.filter(ticket__in=tickets).values_list(
                "embedding", flat=True
            )
        ]
        if vectors:
            incident.centroid = [sum(c) / len(vectors) for c in zip(*vectors, strict=True)]
        incident.ticket_count = len(tickets)
        if incident.status == "confirmed" and incident.target_resolve_at is None:
            incident.target_resolve_at = now
            incident.target_breached_at = now
        incident.save()


class Migration(migrations.Migration):
    dependencies = [
        ("incidents", "0001_initial"),
        ("tickets", "0010_incident_lifecycle"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
