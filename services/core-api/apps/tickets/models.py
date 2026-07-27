"""
Ticket, embedding, PII quarantine, AI run, routing decision, and incident
models. Table/column names mirror spec §3.1 / §3.3 / §3.5 exactly via
`db_table` — this is what lets infra/migrations/sql/*.sql (written against
those exact names) apply cleanly after these migrations run.
"""

from django.conf import settings
from django.db import models
from pgvector.django import VectorField

from contracts.enums import PIILevel, TicketCategory


class Incident(models.Model):
    """§3.5. A mass-incident parent: created when the incident detector
    (§9) finds ticket volume far above its adaptive baseline."""

    public_id = models.CharField(max_length=32, unique=True)  # INC-2026-0007
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=[(c.value, c.value) for c in TicketCategory])
    severity = models.CharField(max_length=20)
    detected_by = models.CharField(max_length=30)  # density_detector|human
    ticket_count = models.IntegerField(default=0)
    detection_window_min = models.IntegerField(null=True, blank=True)
    baseline_rate = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    status = models.CharField(max_length=20, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "incidents"

    def __str__(self) -> str:
        return self.public_id


class Ticket(models.Model):
    """§3.1. The main table holds ONLY masked data — raw PII never lands
    here (see PiiQuarantine below and apps/tickets/services/masking.py)."""

    public_id = models.CharField(max_length=32, unique=True)  # TKT-2026-000123
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_tickets"
    )

    subject_masked = models.TextField()
    body_masked = models.TextField()
    pii_level = models.CharField(max_length=20, choices=[(p.value, p.value) for p in PIILevel])
    pii_map = models.JSONField(default=dict)  # {"[EMAIL_1]": "<quarantine ref uuid>"}

    status = models.CharField(max_length=20, default="new")
    # Set ONLY by router.py, never directly from an LLM proposal (ADR-0001).
    category = models.CharField(
        max_length=20, choices=[(c.value, c.value) for c in TicketCategory], null=True, blank=True
    )
    assigned_team = models.CharField(max_length=50, null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )

    incident = models.ForeignKey(
        Incident, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets"
    )
    duplicate_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates"
    )

    sla_due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    reopened_count = models.SmallIntegerField(default=0)  # the most important metric
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets"

    def __str__(self) -> str:
        return self.public_id


class TicketEmbedding(models.Model):
    """Split from `tickets` so re-embedding on a model change never locks
    the main table (spec §3.1 comment)."""

    ticket = models.OneToOneField(
        Ticket, on_delete=models.CASCADE, primary_key=True, related_name="embedding_row"
    )
    model = models.CharField(max_length=100)
    embedding = VectorField(dimensions=1024)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_embeddings"


class PiiQuarantine(models.Model):
    """§3.1. Raw PII, encrypted at the application layer (AES-GCM, key
    outside the DB — see services/crypto.py), with a hard TTL."""

    ref = models.UUIDField(primary_key=True, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="quarantine_entries")
    ciphertext = models.BinaryField()
    nonce = models.BinaryField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pii_quarantine"


class PiiAccessLog(models.Model):
    """Every raw-PII read is a row here. No exceptions — enforced by
    routing every quarantine read through one service function."""

    ref = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()  # required, non-empty (enforced in service)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pii_access_log"


class AiRun(models.Model):
    """§3.3. One row per ai-engine invocation. `proposed_draft` is the raw,
    not-yet-trusted LLM output; `trust_signals`/`trust_score` are what the
    router actually acts on."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="ai_runs")
    idempotency_key = models.CharField(max_length=100, unique=True)  # ticket_id + attempt

    prompt_version = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    graph_version = models.CharField(max_length=50)

    proposed_draft = models.JSONField(null=True, blank=True)
    llm_self_confidence = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )  # log-only — see ADR-0003

    trust_signals = models.JSONField()
    trust_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)

    retrieved_chunks = models.JSONField(default=list)
    tokens_in = models.IntegerField(null=True, blank=True)
    tokens_out = models.IntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    degraded_reason = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_runs"


class RoutingDecision(models.Model):
    """§3.3. `thresholds_used` is a snapshot, not a reference — three
    months from now, "what were the thresholds at the time" must be
    answerable without knowing when thresholds.yaml last changed."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="routing_decisions")
    ai_run = models.ForeignKey(
        AiRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="routing_decisions"
    )

    branch = models.CharField(max_length=20)
    reason_code = models.CharField(max_length=50)
    reason_detail = models.TextField()
    gate_failed = models.CharField(max_length=100, null=True, blank=True)
    thresholds_used = models.JSONField()
    shadow_mode = models.BooleanField(default=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "routing_decisions"
