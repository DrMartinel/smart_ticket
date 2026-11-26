"""Gives a ticket with no category the category its reviewer confirmed at handoff: Jev's choice in
the reviewed run, marked correct and not corrected (F2 implementation note 6)."""

from django.db import migrations
from django.db.models import Q

HANDOFF_ACTIONS = ("approve", "reroute")
SECURITY_QUEUES = ("injection", "pii_verify")


def backfill(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    ReviewDecision = apps.get_model("review", "ReviewDecision")
    confirmed = (
        ReviewDecision.objects.filter(
            Q(corrected_category=None) | Q(corrected_category=""),
            review_item__ticket__category=None,
            review_item__ai_run__isnull=False,
            action_taken__in=HANDOFF_ACTIONS,
            category_verdict="correct",
        )
        .exclude(review_item__queue__in=SECURITY_QUEUES)
        .order_by("decided_at")
        .values_list("review_item__ticket_id", "review_item__ai_run__trust_signals")
    )
    chosen = {}
    for ticket_id, signals in confirmed:
        choice = ((signals or {}).get("classification") or {}).get("category_choice")
        if choice:
            chosen[ticket_id] = choice
    for ticket_id, choice in chosen.items():
        Ticket.objects.filter(pk=ticket_id, category=None).update(category=choice)


class Migration(migrations.Migration):
    dependencies = [
        ("review", "0004_decided_via_and_agent_draft"),
        ("tickets", "0014_agent_pii_critical"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
