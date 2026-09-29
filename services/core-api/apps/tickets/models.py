"""
Ticket, embedding, PII quarantine, AI run, routing decision, and incident
models. Table/column names mirror spec §3.1 / §3.3 / §3.5 exactly via
`db_table` — this is what lets infra/migrations/sql/*.sql (written against
those exact names) apply cleanly after these migrations run.
"""

from __future__ import annotations

import uuid

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import connection, models, transaction
from django.utils import timezone
from pgvector.django import CosineDistance, VectorField

from apps.core.models import BaseModel
from apps.tickets.utils.patterns import PIILevel
from infrastructure.ai_engine import TicketCategory
from apps.tickets.request_schema import TicketIn

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.utils.masking import mask

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager
    from apps.review.models import ReviewItem


class IncidentManager(models.Manager["Incident"]):
    def next_public_id(self) -> str:
        # Backed by a dedicated Postgres sequence (apps/tickets/migrations/
        # 0002_sequences_and_sql.py), not a row count, so IDs stay monotonic and
        # collision-free under concurrent submission.
        with connection.cursor() as cur:
            cur.execute("SELECT nextval('incident_public_id_seq')")
            n = cast(tuple[int], cur.fetchone())[0]
        return f"INC-{timezone.now().year}-{n:04d}"

    def get_or_create_for_mass_incident(
        self, ticket: Ticket, similar: list[Ticket], baseline_rate: float
    ) -> Incident:
        category = ticket.category or "other"

        # Celery runs with concurrency > 1 (spec §10.3), so two tickets in the
        # same mass incident can independently reach this function at nearly
        # the same instant. A plain filter-then-create has a check-then-act
        # race that produces two separate Incident rows for one real event —
        # exactly the outcome spec §9 says the detector must prevent (one
        # notification with an ETA, not a fragmented picture). A Postgres
        # advisory lock keyed by category serializes that window cheaply
        # without needing a dedicated "current incident" row to lock first.
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"mass_incident:{category}"]
                )

            existing = self.filter(
                category=category,
                status="open",
                created_at__gte=timezone.now() - timedelta(hours=6),
            ).first()
            if existing:
                existing.ticket_count = len(similar) + 1
                existing.save(update_fields=["ticket_count"])
                incident = existing
            else:
                incident = self.create(
                    public_id=self.next_public_id(),
                    title=f"Mass incident: {category} — {ticket.subject_masked[:80]}",
                    category=category,
                    severity="high",
                    detected_by="density_detector",
                    ticket_count=len(similar) + 1,
                    detection_window_min=settings.THRESHOLDS.incident.window_minutes,
                    baseline_rate=baseline_rate,
                    status="open",
                )

            # Link every ticket that contributed to the detection, so the
            # parent incident view can notify every affected reporter at once
            # — the actual value described in spec §9 ("40 người nhận 1 thông
            # báo có ETA").
            Ticket.objects.filter(id__in=[t.id for t in similar]).update(incident=incident)

        return incident


class Incident(BaseModel):
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

    class Meta(BaseModel.Meta):
        db_table = "incidents"

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[IncidentManager] = IncidentManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    def __str__(self) -> str:
        return self.public_id


@dataclass(frozen=True)
class IncidentVerdict:
    kind: Literal["unique", "duplicate", "mass_incident"]
    of: uuid.UUID | None = None  # ticket id, for duplicates
    parent: Incident | None = None
    baseline_rate: float | None = None


class TicketManager(models.Manager["Ticket"]):
    def next_public_id(self) -> str:
        # Backed by a dedicated Postgres sequence (apps/tickets/migrations/
        # 0002_sequences_and_sql.py), not a row count, so IDs stay monotonic and
        # collision-free under concurrent submission.
        with connection.cursor() as cur:
            cur.execute("SELECT nextval('ticket_public_id_seq')")
            n = cast(tuple[int], cur.fetchone())[0]
        return f"TKT-{timezone.now().year}-{n:06d}"

    def similar_to(
        self, embedding: list[float], category: str | None, threshold: float, window: timedelta
    ) -> list[Ticket]:
        since = timezone.now() - window
        qs = (
            self.filter(created_at__gte=since)
            .exclude(embedding_row__isnull=True)
            .annotate(distance=CosineDistance("embedding_row__embedding", embedding))
            .filter(distance__lte=1 - threshold)
            .order_by("distance")
        )
        if category:
            qs = qs.filter(category=category)
        return list(qs)

    def rolling_baseline(
        self, category: str | None, days: int = 30, window_minutes: int = 15
    ) -> tuple[float, float]:
        """Mean and stddev of ticket count per `window_minutes` bucket, over
        the trailing `days` window, for the given category. Returns (mean,
        std). With too little history, falls back to a conservative (0, 0) so
        the 3-sigma check simply requires `min_count` to trigger — better to
        lean toward escalation early than to silently need a month of data
        before mass-incident detection works at all."""

        since = timezone.now() - timedelta(days=days)
        qs = self.filter(created_at__gte=since)
        if category:
            qs = qs.filter(category=category)

        total_minutes = days * 24 * 60
        n_buckets = max(1, total_minutes // window_minutes)
        total_count = qs.count()
        if total_count == 0:
            return 0.0, 0.0

        mean = total_count / n_buckets
        # Poisson-ish approximation for std when we don't have per-bucket
        # counts cheaply available; adequate for an adaptive floor, not meant
        # to be a precise statistical model.
        std = mean**0.5
        return mean, std

    def submit(self, *, reporter: User, ticket_in: TicketIn, trace_id: str | None) -> Ticket:
        """Ticket submission — spec §5. Masks, persists and enqueues one
        validated submission.

        Masking runs INLINE and synchronously, inside the submit request: by
        the time this returns, the committed `tickets` row contains ONLY
        masked content, `pii_quarantine` holds the encrypted raw values, and
        the AI pipeline has been handed off to Celery for everything
        downstream (retrieval, LLM, routing).

        A masking failure does not raise: the ticket is stored with whatever
        regex could mask, at `PIILevel.MASK_FAILED`, which the router sends to a
        human. Callers must never retry or drop a MASK_FAILED ticket.
        """
        result = async_to_sync(mask)(ticket_in)
        quarantine_entries = build_quarantine_entries(result.placeholder_map)

        with transaction.atomic():
            ticket = self.create(
                public_id=self.next_public_id(),
                reporter=reporter,
                subject_masked=result.subject_masked,
                body_masked=result.body_masked,
                pii_level=result.pii_level.value,
                pii_map={ph: str(entry.ref) for ph, entry in quarantine_entries.items()},
            )
            PiiQuarantine.objects.bulk_create(
                [
                    PiiQuarantine(
                        ref=entry.ref,
                        ticket=ticket,
                        ciphertext=entry.ciphertext,
                        nonce=entry.nonce,
                        expires_at=entry.expires_at,
                    )
                    for entry in quarantine_entries.values()
                ]
            )
            AuditLog.objects.record(
                "ticket_submitted",
                actor_type="human",
                actor_id=reporter.id,
                ticket_id=ticket.id,
                payload={
                    "ticket_public_id": ticket.public_id,
                    "pii_level": ticket.pii_level,
                    "trace_id": trace_id,
                },
                trace_id=trace_id,
            )

        # Outside the atomic block on purpose: enqueued before commit, a fast
        # worker can look the ticket up, get DoesNotExist, and leave it stuck at
        # status="new" with no routing decision.
        # Imported here: tasks imports the pipeline, which imports this module.
        from apps.tickets import tasks

        # As a string: task arguments go through Celery's JSON serializer.
        tasks.process_ticket.delay(str(ticket.id))
        return ticket


class Ticket(BaseModel):
    """§3.1. The main table holds ONLY masked data — raw PII never lands
    here (see PiiQuarantine below and apps/tickets/utils/masking.py)."""

    reporter_id: uuid.UUID
    incident_id: uuid.UUID | None
    ai_runs: RelatedManager[AiRun]
    routing_decisions: RelatedManager[RoutingDecision]
    review_items: RelatedManager[ReviewItem]

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
    duplicate_of = models.ForeignKey["Ticket"](
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates"
    )

    sla_due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    reopened_count = models.SmallIntegerField(default=0)  # the most important metric
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "tickets"

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[TicketManager] = TicketManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    def __str__(self) -> str:
        return self.public_id

    def store_embedding(self, embedding: list[float], model_name: str) -> TicketEmbedding:
        return TicketEmbedding.objects.update_or_create(
            ticket=self, defaults={"model": model_name, "embedding": embedding}
        )[0]

    def classify_similarity(self, embedding: list[float]) -> IncidentVerdict:
        """Incident Detector — spec §9. Distinguishes an ordinary duplicate from a
        mass incident using an ADAPTIVE threshold (baseline + 3σ over a rolling
        30-day window per category), not a fixed constant — 5 network tickets in
        15 minutes is normal at a 5000-person company and abnormal at a
        100-person one."""
        th = settings.THRESHOLDS.incident
        window = timedelta(minutes=th.window_minutes)

        similar = Ticket.objects.similar_to(embedding, self.category, th.similarity, window)
        if not similar:
            return IncidentVerdict(kind="unique")

        baseline, sigma = Ticket.objects.rolling_baseline(
            self.category, days=30, window_minutes=th.window_minutes
        )

        if len(similar) > baseline + th.sigma_multiplier * sigma and len(similar) >= th.min_count:
            parent = Incident.objects.get_or_create_for_mass_incident(self, similar, baseline)
            return IncidentVerdict(kind="mass_incident", parent=parent, baseline_rate=baseline)

        return IncidentVerdict(kind="duplicate", of=similar[0].id)


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
    outside the DB — see utils/crypto.py), with a hard TTL."""

    ref = models.UUIDField(primary_key=True, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="quarantine_entries")
    ciphertext = models.BinaryField()
    nonce = models.BinaryField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "pii_quarantine"


class PiiAccessLog(BaseModel):
    """Every raw-PII read is a row here. No exceptions — enforced by
    routing every quarantine read through one service function."""

    ref = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()  # required, non-empty (enforced in service)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pii_access_log"


class AiRunManager(models.Manager["AiRun"]):
    def cost_today_usd(self) -> float:
        """Total AI spend since 00:00 UTC — what `budget.daily_cost_ceiling_usd`
        is compared against."""
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        total = self.filter(created_at__gte=today_start).values_list("cost_usd", flat=True)
        return float(sum(c or 0 for c in total))


class AiRun(BaseModel):
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

    class Meta(BaseModel.Meta):
        db_table = "ai_runs"

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[AiRunManager] = AiRunManager()  # pyright: ignore[reportIncompatibleVariableOverride]


class RoutingDecision(BaseModel):
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

    class Meta(BaseModel.Meta):
        db_table = "routing_decisions"
