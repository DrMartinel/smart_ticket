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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, cast

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
from apps.tickets.utils.router import AGENT_HANDOFF_REASONS
from infrastructure.dtos import TicketCategory
from apps.tickets.request_schema import RevealReason, TicketIn

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.tickets.utils.crypto import QuarantineEntry, build_quarantine_entries

if TYPE_CHECKING:
    from apps.agent.models import AgentTurn
    from infrastructure.dtos import AgentHandoffReason
    from apps.chat.models import Conversation
    from apps.lifecycle.models import WorkflowStatus
from apps.tickets.utils.masking import mask


class IncidentStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"
    CLOSED = "closed"


# Incidents a new ticket can still join (BR-F7-02).
OPEN_INCIDENT_STATUSES = (IncidentStatus.PROPOSED, IncidentStatus.CONFIRMED)


class IncidentStage(StrEnum):
    """The public stage broadcasts show."""

    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    MONITORING = "monitoring"
    RESOLVED = "resolved"


class IncidentManager(models.Manager["Incident"]):
    def next_public_id(self) -> str:
        # Backed by a dedicated Postgres sequence (apps/tickets/migrations/
        # 0002_sequences_and_sql.py), not a row count, so IDs stay monotonic and
        # collision-free under concurrent submission.
        with connection.cursor() as cur:
            cur.execute("SELECT nextval('incident_public_id_seq')")
            n = cast(tuple[int], cur.fetchone())[0]
        return f"INC-{timezone.now().year}-{n:04d}"

    def open(self) -> QuerySet[Incident]:
        return self.filter(status__in=[s.value for s in OPEN_INCIDENT_STATUSES])


class TicketSource(StrEnum):
    """Where a ticket came from. A chat question is a ticket from the start,
    so it is masked, analysed, routed and recorded like any other; what
    differs is only who is asked before a routed handoff to support is
    carried out (`pipeline.waits_for_requester`)."""

    FORM = "form"
    CHAT = "chat"


class Incident(BaseModel):
    """§3.5. A mass-incident parent: proposed by the incident detector (§9) or
    declared by an incident manager, confirmed by one, broadcast to its
    requesters and resolved with its tickets (F7)."""

    public_id = models.CharField(max_length=32, unique=True)  # INC-2026-0007
    title = models.CharField(max_length=255)
    # Unknown when the detector proposes it (routing hasn't run); set at confirm.
    category = models.CharField(
        max_length=20, choices=[(c.value, c.value) for c in TicketCategory], null=True, blank=True
    )
    service = models.CharField(max_length=120, blank=True, default="")
    severity = models.CharField(max_length=20)
    detected_by = models.CharField(max_length=30)  # density_detector|human
    # Counted from the active links (BR-F7-09); kept for display.
    ticket_count = models.IntegerField(default=0)
    detection_window_min = models.IntegerField(null=True, blank=True)
    baseline_rate = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    # {count, baseline, sigma} when the detector proposed it.
    detector = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in IncidentStatus],
        default=IncidentStatus.PROPOSED.value,
    )
    stage = models.CharField(
        max_length=15,
        choices=[(s.value, s.value) for s in IncidentStage],
        default=IncidentStage.INVESTIGATING.value,
    )
    eta = models.DateTimeField(null=True, blank=True)
    eta_unknown = models.BooleanField(default=False)
    # Mean embedding of the linked tickets: a new ticket joins by cosine to it (BR-F7-02).
    centroid = VectorField(dimensions=1024, null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note_masked = models.TextField(blank=True, default="")
    dismiss_reason = models.TextField(blank=True, default="")
    # The incident's own P1 target, 24×7 from confirmation (BR-F7-10).
    target_resolve_at = models.DateTimeField(null=True, blank=True)
    target_breached_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "incidents"

    objects = IncidentManager()

    def __str__(self) -> str:
        return self.public_id

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_INCIDENT_STATUSES


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
        """The tickets `user` may read as staff, and the ones they reported (FR-F14-004)."""
        reach = self.reach(user)
        return self.all() if reach is None else self.filter(reach | models.Q(reporter=user))

    def reach(self, user: User) -> models.Q | None:
        """The tickets `user`'s ticket-read grants cover; None for every ticket."""
        from apps.accounts.utils.access import Access
        from apps.accounts.utils.catalog import Permission

        return Access.of(user).ticket_filter(Permission.TICKETS_READ)

    def in_department_of(self, user: User) -> QuerySet[Ticket]:
        """Tickets raised by people in the departments `user` heads, subtrees included."""
        from apps.accounts.utils.access import Access
        from apps.accounts.utils.catalog import Permission

        departments = Access.of(user).department_ids(Permission.REQUESTER_DEPARTMENT_READ)
        if departments is None:
            return self.all()
        return self.filter(reporter__department_id__in=departments)

    def for_requester(self, user: User) -> QuerySet[Ticket]:
        """Tickets `user` reported, form and chat, with when each last changed (BR-F3-04)."""
        return (
            self.filter(reporter=user)
            .select_related("workflow_status", "team", "reopened_from")
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
            "reporter", "assigned_to", "workflow_status"
        ).prefetch_related("review_items", "sla_clocks")
        reach = self.reach(user)
        if reach is not None:
            tickets = tickets.filter(reach)
        match view:
            case StaffView.REVIEW:
                from apps.review.models import SECURITY_QUEUES, ReviewItem

                waiting = ReviewItem.objects.filter(
                    ticket=models.OuterRef("pk"), state__in=ReviewItem.OPEN_STATES
                )
                from apps.accounts.utils.access import Access
                from apps.accounts.utils.catalog import Permission

                if not Access.of(user).holds(Permission.SECURITY_QUEUE_WORK):
                    waiting = waiting.exclude(queue__in=SECURITY_QUEUES)
                tickets = tickets.filter(models.Exists(waiting))
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

        return self.select_related("reporter", "assigned_to", "workflow_status").prefetch_related(
            models.Prefetch("routing_decisions", RoutingDecision.objects.order_by("-decided_at")),
            models.Prefetch("review_items", ReviewItem.objects.order_by("-created_at")),
            models.Prefetch("clarifications", TicketClarification.objects.order_by("asked_at")),
            models.Prefetch("ai_runs", AiRun.objects.order_by("-created_at")),
        )

    def board(
        self, workflow_id: uuid.UUID, user: User, *, query: str, per_column: int
    ) -> TicketBoard:
        """The newest `per_column` tickets of each status in `workflow_id` `user` may read, and
        every status's count."""
        tickets = self.filter(workflow_status__workflow_id=workflow_id)
        reach = self.reach(user)
        if reach is not None:
            tickets = tickets.filter(reach)
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
            .select_related("reporter", "assigned_to", "workflow_status")
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
        agent_turn: AgentTurn | None = None,
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

        def store(ticket: Ticket) -> dict[str, str]:
            PiiQuarantine.objects.store(ticket, quarantine_entries)
            own = {ph: str(entry.ref) for ph, entry in quarantine_entries.items()}
            if agent_turn is None:
                return own
            inherited = {ph: ref for ph, ref in agent_turn.pii_map.items() if ph not in own}
            text = f"{result.subject_masked}\n{result.body_masked}"
            return own | PiiQuarantine.objects.copy_to(ticket, inherited, text)

        return self._open(
            reporter=reporter,
            trace_id=trace_id,
            store=store,
            audit={},
            subject_masked=result.subject_masked,
            body_masked=result.body_masked,
            pii_level=result.pii_level.value,
            source=source.value,
            conversation=conversation,
            reopened_from=reopened_from,
            agent_turn=agent_turn,
        )

    def submit_for_agent(
        self,
        turn: AgentTurn,
        reason: AgentHandoffReason,
        conversation: Conversation | None,
        audit: dict[str, str],
    ) -> Ticket:
        """Opens the chat ticket an agent turn hands to a person: the turn's masked message, its
        quarantine entries and the agent's reason (BR-F15-14, BR-F15-18)."""
        from apps.chat.utils.turns import ticket_in_from_message

        ticket_in = ticket_in_from_message(turn.message_masked)
        return self._open(
            reporter=turn.conversation.user,
            trace_id=None,
            store=lambda ticket: PiiQuarantine.objects.copy_to(
                ticket, turn.pii_map, turn.message_masked
            ),
            audit=audit,
            subject_masked=ticket_in.subject,
            body_masked=ticket_in.body,
            pii_level=turn.pii_level,
            source=TicketSource.CHAT.value,
            conversation=conversation,
            agent_turn=turn,
            agent_handoff_reason=reason,
        )

    def _open(
        self,
        *,
        reporter: User,
        trace_id: str | None,
        store: Callable[[Ticket], dict[str, str]],
        audit: dict[str, str],
        **fields: Any,
    ) -> Ticket:
        """Creates a masked ticket, stores its quarantine entries, starts its workflow, audits
        it and queues its pipeline run."""
        with transaction.atomic():
            ticket = self.create(
                public_id=self.next_public_id(),
                reporter=reporter,
                requester_department_id=reporter.department_id,
                **fields,
            )
            ticket.pii_map = store(ticket)
            ticket.save(update_fields=["pii_map"])
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
                    **audit,
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
    # The reporter's department when they submitted (FR-F14-014).
    requester_department = models.ForeignKey(
        "accounts.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
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
    # The agent turn that opened this ticket (F15).
    agent_turn = models.ForeignKey(
        "agent.AgentTurn", on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets"
    )
    # Why the agent handed this ticket to a person (F15); the router's gate reads it.
    agent_handoff_reason = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        choices=[(r.value, r.value) for r in sorted(AGENT_HANDOFF_REASONS)],
    )

    class Meta(BaseModel.Meta):
        db_table = "tickets"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(agent_handoff_reason__isnull=True)
                | models.Q(
                    agent_handoff_reason__in=[r.value for r in sorted(AGENT_HANDOFF_REASONS)]
                ),
                name="tickets_agent_handoff_reason_known",
            )
        ]

    objects = TicketManager()

    def __str__(self) -> str:
        return self.public_id

    def enter_status(self, status: WorkflowStatus) -> None:
        """Puts the ticket in `status` and saves the fields that changed."""
        self.workflow_status = status
        self.status = status.key
        self.version += 1
        if not status.is_completed:
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

    def store_for_turn(self, turn: AgentTurn, entries: dict[str, QuarantineEntry]) -> None:
        """One encrypted row per placeholder of an agent turn's message (F15)."""
        self.bulk_create(
            [
                PiiQuarantine(
                    ref=entry.ref,
                    agent_turn=turn,
                    ciphertext=entry.ciphertext,
                    nonce=entry.nonce,
                    expires_at=entry.expires_at,
                )
                for entry in entries.values()
            ]
        )

    def copy_to(self, ticket: Ticket, pii_map: dict[str, str], text: str) -> dict[str, str]:
        """Copies the entries `pii_map` names for each placeholder in `text` to `ticket`; the
        ticket's placeholders and their new refs (BR-F15-18)."""
        wanted = {ph: ref for ph, ref in pii_map.items() if ph in text}
        rows = {str(row.ref): row for row in self.filter(ref__in=list(wanted.values()))}
        copies = {
            ph: PiiQuarantine(
                ref=uuid.uuid4(),
                ticket=ticket,
                ciphertext=rows[ref].ciphertext,
                nonce=rows[ref].nonce,
                expires_at=rows[ref].expires_at,
            )
            for ph, ref in wanted.items()
            if ref in rows
        }
        self.bulk_create(copies.values())
        return {ph: str(row.ref) for ph, row in copies.items()}


class PiiQuarantine(models.Model):
    """§3.1. Raw PII, encrypted at the application layer (AES-GCM, key
    outside the DB — see utils/crypto.py), with a hard TTL."""

    ref = models.UUIDField(primary_key=True, editable=False)
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, null=True, related_name="quarantine_entries"
    )
    # The agent turn whose message held the value (F15); a row has one owner.
    agent_turn = models.ForeignKey(
        "agent.AgentTurn", on_delete=models.CASCADE, null=True, related_name="quarantine_entries"
    )
    ciphertext = models.BinaryField()
    nonce = models.BinaryField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pii_quarantine"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ticket__isnull=False, agent_turn__isnull=True)
                | models.Q(ticket__isnull=True, agent_turn__isnull=False),
                name="pii_quarantine_one_owner",
            )
        ]

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
    # The flags, env switch and thresholds version the decision ran under (F9, BR-F9-09).
    rollout_snapshot = models.JSONField(default=dict, blank=True)
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
    # The incident broadcast a system comment carries (F7).
    broadcast = models.ForeignKey(
        "incidents.IncidentBroadcast",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comments",
    )
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
