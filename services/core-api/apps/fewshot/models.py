"""Few-shot pool — spec §3.5. Governance rules enforced at both the DB
level (`chk_fewshot_confirmed`) and in services.py (TTL, retraction)."""

from django.conf import settings
from django.db import models
from pgvector.django import VectorField

from contracts.enums import TicketCategory
from apps.tickets.models import Ticket


class FewshotExample(models.Model):
    source_ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="fewshot_examples")
    category = models.CharField(max_length=20, choices=[(c.value, c.value) for c in TicketCategory])
    input_text = models.TextField()  # already masked
    output_json = models.JSONField()
    embedding = VectorField(dimensions=1024, null=True, blank=True)

    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_at = models.DateTimeField()
    user_confirmed = models.BooleanField(default=False)  # required to enter the pool
    expires_at = models.DateTimeField()  # approved_at + ttl_days
    retracted_at = models.DateTimeField(null=True, blank=True)  # set when source ticket reopens
    retract_reason = models.TextField(null=True, blank=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "fewshot_examples"
        # chk_fewshot_confirmed CHECK constraint is added by
        # infra/migrations/sql/0003_constraints_and_triggers.sql.
