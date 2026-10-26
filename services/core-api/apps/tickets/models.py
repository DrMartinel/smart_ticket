"""
Ticket, embedding, PII quarantine, AI run, routing decision, and incident
models. Table/column names mirror spec §3.1 / §3.3 / §3.5 exactly via
`db_table` — this is what lets infra/migrations/sql/*.sql (written against
those exact names) apply cleanly after these migrations run.
"""

from __future__ import annotations

import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, cast

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import connection, models, transaction
from django.db.models import F, QuerySet, Window
from django.db.models import Max
from django.db.models.functions import Coalesce, Greatest, RowNumber
from django.utils import timezone
from pgvector.django import CosineDistance, VectorField

from apps.core.models import BaseModel
from apps.tickets.utils.patterns import PIILevel
from infrastructure.dtos import TicketCategory
from apps.tickets.request_schema import RevealReason, TicketIn

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.tickets.utils.crypto import QuarantineEntry, build_quarantine_entries

if TYPE_CHECKING:
    from apps.chat.models import Conversation
    from apps.lifecycle.models import WorkflowStatus
from apps.tickets.utils.masking import mask


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


class TicketSource(StrEnum):
    """Where a ticket came from. A chat question is a ticket from the start,
    so it is masked, analysed, routed and recorded like any other; what
    differs is only who is asked before a routed handoff to support is
    carried out (`pipeline.waits_for_requester`)."""

    FORM = "form"
    CHAT = "chat"


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

    objects = IncidentManager()

    def __str__(self) -> str:
        return self.public_id


@dataclass(frozen=True)
class IncidentVerdict:
    kind: Literal["unique", "duplicate", "mass_incident"]
    of: uuid.UUID | None = None  # ticket id, for duplicates
    parent: Incident | None = None
    baseline_rate: float | None = None


@dataclass(frozen=True)
class TicketPage:
    """A page of a staff view."""

    items: list[Ticket]
    total: int
    counts: dict[str, int]


@dataclass(frozen=True)
class TicketBoard:
    """A workflow's tickets by status: the newest of each, and how many each holds."""

    items: list[Ticket]
    counts: dict[str, int]


class StaffView(StrEnum):
    """The saved ticket lists staff work from."""

    REVIEW = "review"
    MINE = "mine"
    OPEN = "open"
    RESOLVED = "resolved"
    ALL = "all"


# Review item states that still wait for a person.
class TicketManager(models.Manager["Ticket"]):
    def visible_to(self, user: User) -> QuerySet[Ticket]:
        """Every ticket for support staff; a requester's own tickets otherwise."""
        return self.all() if user.is_support_staff else self.filter(reporter=user)

    def for_requester(self, user: User) -> QuerySet[Ticket]:
        """Tickets `user` reported, form and chat, with when each last changed (BR-F3-04)."""
        return (
            self.filter(reporter=user)
            .select_related("workflow_status__base", "team", "reopened_from")
            .prefetch_related("sla_clocks", "ratings")
            .annotate(
                last_update=Greatest(
                    "created_at",
                    Coalesce(Max("transfers__created_at"), "created_at"),
                    Coalesce(Max("comments__created_at"), "created_at"),
                )
            )
        )

    def in_view(self, view: StaffView, user: User, query: str = "") -> QuerySet[Ticket]:
        """The tickets `view` shows `user`, newest first, matching `query` on id or subject."""
        tickets = self.select_related(
            "reporter", "assigned_to", "workflow_status__base"
        ).prefetch_related("review_items", "sla_clocks")
        match view:
            case StaffView.REVIEW:
                from apps.review.models import ReviewItem

                tickets = tickets.filter(review_items__state__in=ReviewItem.OPEN_STATES).distinct()
            case StaffView.MINE:
                tickets = tickets.filter(assigned_to=user, resolved_at__isnull=True)
            case StaffView.OPEN:
                tickets = tickets.filter(resolved_at__isnull=True)
            case StaffView.RESOLVED:
                tickets = tickets.filter(resolved_at__isnull=False)
        query = query.strip()
        if query:
            tickets = tickets.filter(
                models.Q(public_id__icontains=query) | models.Q(subject_masked__icontains=query)
            )
        return tickets.order_by("-created_at")

    def for_detail(self) -> QuerySet[Ticket]:
        """Tickets with what the staff detail shows loaded, each list in display order."""
        from apps.review.models import ReviewItem

        return self.select_related(
            "reporter", "assigned_to", "workflow_status__base"
        ).prefetch_related(
            models.Prefetch("routing_decisions", RoutingDecision.objects.order_by("-decided_at")),
            models.Prefetch("review_items", ReviewItem.objects.order_by("-created_at")),
            models.Prefetch("clarifications", TicketClarification.objects.order_by("asked_at")),
            models.Prefetch("ai_runs", AiRun.objects.order_by("-created_at")),
        )

    def board(self, workflow_id: uuid.UUID, *, query: str, per_column: int) -> TicketBoard:
        """The newest `per_column` tickets of each status in `workflow_id`, and every status's count."""
        tickets = self.filter(workflow_status__workflow_id=workflow_id)
        query = query.strip()
        if query:
            tickets = tickets.filter(
                models.Q(public_id__icontains=query) | models.Q(subject_masked__icontains=query)
            )
        counts = dict(tickets.values_list("status").annotate(n=models.Count("id")).order_by())
        newest = (
            tickets.annotate(
                rank=Window(
                    RowNumber(),
                    partition_by=F("workflow_status_id"),
                    order_by=F("created_at").desc(),
                )
            )
            .filter(rank__lte=per_column)
            .select_related("reporter", "assigned_to", "workflow_status__base")
            .prefetch_related("review_items", "sla_clocks")
            .order_by("-created_at")
        )
        return TicketBoard(items=list(newest), counts=counts)

    def page(
        self, view: StaffView, user: User, *, query: str, number: int, size: int
    ) -> TicketPage:
        """One page of `view`, with the size of every view for the sidebar."""
        tickets = self.in_view(view, user, query)
        start = (number - 1) * size
        return TicketPage(
            items=list(tickets[start : start + size]),
            total=tickets.count(),
            counts=self.view_counts(user),
        )

    def view_counts(self, user: User) -> dict[str, int]:
        """How many tickets each staff view holds for `user`."""
        return {view.value: self.in_view(view, user).count() for view in StaffView}

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

    def submit(
        self,
        *,
        reporter: User,
        ticket_in: TicketIn,
        trace_id: str | None,
        source: TicketSource = TicketSource.FORM,
        conversation: Conversation | None = None,
        reopened_from: Ticket | None = None,
    ) -> Ticket:
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
        result = async_to_sync(mask)(ticket_in, settings.THRESHOLDS.masking.ner_max_share)
        quarantine_entries = build_quarantine_entries(result.placeholder_map)

        with transaction.atomic():
            ticket = self.create(
                public_id=self.next_public_id(),
                reporter=reporter,
                subject_masked=result.subject_masked,
                body_masked=result.body_masked,
                pii_level=result.pii_level.value,
                pii_map={ph: str(entry.ref) for ph, entry in quarantine_entries.items()},
                source=source.value,
                conversation=conversation,
                reopened_from=reopened_from,
            )
            PiiQuarantine.objects.store(ticket, quarantine_entries)
            # Imported here: the lifecycle engine imports this module.
            from apps.lifecycle.utils.engine import lifecycle

            lifecycle.start(ticket)
            AuditLog.objects.record(
                "ticket_submitted",
                actor_type="human",
                actor_id=reporter.id,
                ticket_id=ticket.id,
                payload={
                    "ticket_public_id": ticket.public_id,
                    "pii_level": ticket.pii_level,
                    "source": ticket.source,
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

    public_id = models.CharField(max_length=32, unique=True)  # TKT-2026-000123
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_tickets"
    )

    subject_masked = models.TextField()
    body_masked = models.TextField()
    pii_level = models.CharField(max_length=20, choices=[(p.value, p.value) for p in PIILevel])
    pii_map = models.JSONField(default=dict)  # {"[EMAIL_1]": "<quarantine ref uuid>"}

    status = models.CharField(max_length=20, default="new")
    source = models.CharField(
        max_length=10,
        choices=[(s.value, s.value) for s in TicketSource],
        default=TicketSource.FORM.value,
    )
    # The router's decision for a chat ticket, recorded but not yet carried
    # out while status="awaiting_requester": the requester is asked whether
    # to hand it to support, and `pipeline.release_to_support` then executes
    # exactly this decision. Never re-routed on release, so what was decided
    # and what was done cannot drift apart. None once released.
    held_decision = models.JSONField(null=True, blank=True)
    # Set by router.py or a person's recorded reroute, never from a proposal (ADR-0001, BR-F2-06).
    category = models.CharField(
        max_length=20, choices=[(c.value, c.value) for c in TicketCategory], null=True, blank=True
    )
    # The team's slug, kept equal to `team` for existing readers (FR-F2-013).
    assigned_team = models.CharField(max_length=50, null=True, blank=True)
    team = models.ForeignKey(
        "teams.Team", on_delete=models.PROTECT, null=True, blank=True, related_name="tickets"
    )
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
    # The chat conversation the question was asked in (F3); None for form tickets.
    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    # The completed ticket this one was submitted to reopen, after its window (BR-F3-08).
    reopened_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reopened_as"
    )

    # Mirror of the resolution clock's due time (F1); `before_sla` rules read it.
    sla_due_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(
        max_length=2, null=True, blank=True, choices=[(p, p) for p in ("P1", "P2", "P3", "P4")]
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    reopened_count = models.SmallIntegerField(default=0)  # the most important metric
    # How many times the ticket has entered a completed status; ratings are per value (BR-F3-10).
    resolution_seq = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # The lifecycle's position (ADR-0028); `status` holds this status's key.
    workflow_status = models.ForeignKey(
        "lifecycle.WorkflowStatus",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
    )
    waiting_transform = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        db_table = "tickets"

    objects = TicketManager()

    def __str__(self) -> str:
        return self.public_id

    def enter_status(self, status: WorkflowStatus) -> None:
        """Puts the ticket in `status` and saves the fields that changed."""
        self.workflow_status = status
        self.status = status.key
        self.version += 1
        if not status.base.is_completed:
            self.resolved_at = None
        elif self.resolved_at is None:
            self.resolved_at = timezone.now()
            self.resolution_seq += 1
        self.save(
            update_fields=["workflow_status", "status", "version", "resolved_at", "resolution_seq"]
        )

    def latest_clarification(self) -> TicketClarification | None:
        """Finds the last question this ticket asked its requester."""
        return self.clarifications.order_by("-asked_at").first()

    def open_clarification(self) -> TicketClarification | None:
        """Finds the question the requester can still answer (ADR-0023)."""
        latest = self.latest_clarification()
        return latest if latest is not None and self.awaits_answer_to(latest) else None

    def awaits_answer_to(self, clarification: TicketClarification) -> bool:
        """Whether the requester can still answer `clarification`, this ticket's latest question."""
        if self.status != "awaiting_requester" or self.held_decision is None:
            return False
        if clarification.answered_at is not None:
            return False
        wait = timedelta(minutes=settings.THRESHOLDS.clarification.wait_minutes)
        return timezone.now() < clarification.asked_at + wait

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


class PiiQuarantineManager(models.Manager["PiiQuarantine"]):
    def store(self, ticket: Ticket, entries: dict[str, QuarantineEntry]) -> None:
        """One encrypted row per placeholder, from `build_quarantine_entries`."""
        self.bulk_create(
            [
                PiiQuarantine(
                    ref=entry.ref,
                    ticket=ticket,
                    ciphertext=entry.ciphertext,
                    nonce=entry.nonce,
                    expires_at=entry.expires_at,
                )
                for entry in entries.values()
            ]
        )


class PiiQuarantine(models.Model):
    """§3.1. Raw PII, encrypted at the application layer (AES-GCM, key
    outside the DB — see utils/crypto.py), with a hard TTL."""

    ref = models.UUIDField(primary_key=True, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="quarantine_entries")
    ciphertext = models.BinaryField()
    nonce = models.BinaryField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pii_quarantine"

    objects = PiiQuarantineManager()


class PiiAccessLogQuerySet(models.QuerySet["PiiAccessLog"]):
    def matching(
        self,
        *,
        ticket: str | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        reason_code: RevealReason | None = None,
    ) -> PiiAccessLogQuerySet:
        """Rows for a ticket's public id, an actor's username, a time range and a reason."""
        rows = self.select_related("actor", "ticket")
        if ticket:
            rows = rows.filter(ticket__public_id=ticket)
        if actor:
            rows = rows.filter(actor__username=actor)
        if since:
            rows = rows.filter(accessed_at__gte=since)
        if until:
            rows = rows.filter(accessed_at__lt=until)
        if reason_code:
            rows = rows.filter(reason_code=reason_code.value)
        return rows.order_by("-accessed_at")

    def by_actor_since(self, actor: User, since: datetime) -> PiiAccessLogQuerySet:
        """The actor's reveals since a time."""
        return self.filter(actor=actor, accessed_at__gte=since)


class PiiAccessLog(BaseModel):
    """One row per raw-PII value returned to a person (spec §3.1, F5)."""

    ref = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="pii_reveals")
    placeholder = models.CharField(max_length=40)
    reason_code = models.CharField(
        max_length=30, choices=[(r.value, r.value) for r in RevealReason]
    )
    reason = models.TextField()  # masked by the regex tier
    review_item = models.ForeignKey(
        "review.ReviewItem", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    outcome = models.CharField(max_length=20, default="revealed")
    accessed_at = models.DateTimeField(auto_now_add=True)

    objects = PiiAccessLogQuerySet.as_manager()

    class Meta(BaseModel.Meta):
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

    objects = AiRunManager()

    def cited_kb_title(self) -> str | None:
        """The title of the KB page the run's proposal names, if it still exists."""
        from apps.kb.models import KbArticle

        slug = (self.proposed_draft or {}).get("kb_slug")
        if not slug:
            return None
        return KbArticle.objects.filter(slug=slug).values_list("title", flat=True).first()


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


class TicketClarification(BaseModel):
    """A question a live chat ticket asked its requester, and their masked
    answer (ADR-0023)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="clarifications")
    # The run whose decision asked it.
    ai_run = models.ForeignKey(
        AiRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="clarifications"
    )
    question = models.TextField()
    # [{"slug": ..., "title": ...}] for each page offered, titles as when asked.
    options = models.JSONField(default=list)
    # The ticket's masked body when the question was asked.
    ticket_body_masked = models.TextField()
    answer_masked = models.TextField(null=True, blank=True)
    asked_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "ticket_clarifications"


class CommentAuthorKind(StrEnum):
    REQUESTER = "requester"
    STAFF = "staff"
    SYSTEM = "system"


class CommentVisibility(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"


class TicketCommentQuerySet(models.QuerySet["TicketComment"]):
    def public(self) -> TicketCommentQuerySet:
        return self.filter(visibility=CommentVisibility.PUBLIC.value)

    def for_staff(self) -> TicketCommentQuerySet:
        """Comments staff may read: none still held for a masking review (UC-F3-03 3y)."""
        return self.filter(hidden_for_review=False)


class TicketComment(BaseModel):
    """A public comment or an internal note on a ticket, masked before it was stored (BR-F3-06)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ticket_comments",
    )
    author_kind = models.CharField(
        max_length=10, choices=[(k.value, k.value) for k in CommentAuthorKind]
    )
    visibility = models.CharField(
        max_length=10, choices=[(v.value, v.value) for v in CommentVisibility]
    )
    body_masked = models.TextField()
    pii_level = models.CharField(max_length=20, choices=[(p.value, p.value) for p in PIILevel])
    # Masking failed: staff don't see it until a reviewer shows it.
    hidden_for_review = models.BooleanField(default=False)
    # A reviewer discarded it; it stays hidden and the requester is asked to resend.
    discarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TicketCommentQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "ticket_comments"
        indexes = [models.Index(fields=["ticket", "created_at"], name="ticket_comments_thread")]


class TicketRating(BaseModel):
    """The requester's 1–5 rating of one resolution of a ticket (BR-F3-10)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="ratings")
    resolution_seq = models.SmallIntegerField()
    score = models.SmallIntegerField()
    comment_masked = models.TextField(null=True, blank=True)
    rated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "ticket_ratings"
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "resolution_seq"], name="ticket_ratings_one_per_resolution"
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=1, score__lte=5), name="ticket_ratings_score_1_5"
            ),
        ]
