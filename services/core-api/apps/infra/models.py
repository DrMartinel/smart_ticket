"""One row per read of the cloud or its observability: who asked, through what, what was
sent and how it ended (F17, ADR-0048 §9); the customer companies, each a Keystone domain
with a tier (F17 §o, ADR-0048 decision 11); and a ticket's cue runs, the resources each
linked and the cues each collected (F17 §o.8, ADR-0048 decision 10)."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Self

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import BaseModel
from apps.infra.domain.vocabulary import CueRunOutcome, CueStatus, ResourceKind, ResourceSource


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class InfraVia(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    CUE = "cue"


class InfraBackend(StrEnum):
    PROMETHEUS = "prometheus"
    ELASTICSEARCH = "elasticsearch"
    ALERTMANAGER = "alertmanager"
    CLOUD = "cloud"


class InfraQueryKind(StrEnum):
    STRUCTURED = "structured"
    PROMQL = "promql"
    RESOURCE = "resource"


class InfraOutcome(StrEnum):
    OK = "ok"
    REFUSED = "refused"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    SCOPE_UNAVAILABLE = "scope_unavailable"


class InfraQuery(BaseModel):
    """One query a person, their agent or a ticket's cues made, and what came of it."""

    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    via = models.CharField(max_length=8, choices=_choices(InfraVia))
    agent_turn = models.ForeignKey(
        "agent.AgentTurn",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="infra_queries",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    backend = models.CharField(max_length=16, choices=_choices(InfraBackend))
    # The backend that did not answer, which may not be the one the read was aimed at.
    failed_backend = models.CharField(
        max_length=16, choices=_choices(InfraBackend), null=True, blank=True
    )
    kind = models.CharField(max_length=16, choices=_choices(InfraQueryKind))
    compiled = models.TextField()
    projects = ArrayField(models.CharField(max_length=64), default=list)
    outcome = models.CharField(max_length=24, choices=_choices(InfraOutcome))
    refusal = models.CharField(max_length=40, null=True, blank=True)
    # The check a refused query failed, a `QueryCheck` value.
    refusal_reason = models.CharField(max_length=24, null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    rows = models.PositiveIntegerField(default=0)
    withheld = models.PositiveIntegerField(default=0)
    truncated = models.BooleanField(default=False)
    link = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "infra_queries"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(via=InfraVia.CUE.value, actor__isnull=True)
                    | (~models.Q(via=InfraVia.CUE.value) & models.Q(actor__isnull=False))
                ),
                name="infra_queries_no_actor_only_for_cues",
            ),
            models.CheckConstraint(
                condition=~models.Q(via=InfraVia.CUE.value) | models.Q(ticket__isnull=False),
                name="infra_queries_cue_names_its_ticket",
            ),
        ]


class CustomerTier(StrEnum):
    STANDARD = "standard"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class CustomerLookup(StrEnum):
    """What a ticket's customer lookup found (BR-F17-21)."""

    FOUND = "found"
    NONE = "none"
    UNAVAILABLE = "unavailable"


class Customer(BaseModel):
    """A customer company: a Keystone domain, with the display name and tier Keystone lacks."""

    name = models.CharField(max_length=120, unique=True)
    keystone_domain_id = models.CharField(max_length=64, unique=True)
    tier = models.CharField(max_length=16, choices=_choices(CustomerTier))
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "infra_customers"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tier__in=[t.value for t in CustomerTier]),
                name="infra_customers_tier_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CueRunQuerySet(models.QuerySet["CueRun"]):
    def shown_for(self, ticket_id: uuid.UUID) -> Self:
        """The ticket's latest handoff run and every run a person started after it, oldest
        first, with their resources and cues."""
        runs = self.filter(ticket_id=ticket_id)
        handoff = runs.filter(transfer__isnull=False).order_by("-started_at").first()
        shown = (
            runs.filter(transfer__isnull=True)
            if handoff is None
            else runs.filter(
                models.Q(pk=handoff.pk)
                | models.Q(transfer__isnull=True, started_at__gte=handoff.started_at)
            )
        )
        return (
            shown.order_by("started_at")
            .select_related("started_by")
            .prefetch_related("resources__cues", "cues")
        )


class CueRun(BaseModel):
    """One collection of a ticket's cues: at a handoff, or for a resource a person linked."""

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="cue_runs")
    transfer = models.OneToOneField(
        "lifecycle.Transfer", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(
        max_length=20, choices=_choices(CueRunOutcome), default=CueRunOutcome.RUNNING.value
    )

    objects = CueRunQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "infra_cue_runs"
        indexes = [models.Index(fields=["ticket", "-started_at"], name="idx_cue_run_ticket")]


class TicketResource(BaseModel):
    """A cloud resource a cue run linked its ticket to, and how it came to."""

    run = models.ForeignKey(CueRun, on_delete=models.CASCADE, related_name="resources")
    seq = models.PositiveSmallIntegerField()
    project_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=8, choices=_choices(ResourceKind))
    resource_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    source = models.CharField(max_length=16, choices=_choices(ResourceSource))
    token = models.CharField(max_length=255, null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "infra_ticket_resources"
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["run", "resource_id"], name="uq_ticket_resource"),
        ]


class TicketCue(BaseModel):
    """One cue of a run: a fixed template's result about one resource, or an overview row."""

    run = models.ForeignKey(CueRun, on_delete=models.CASCADE, related_name="cues")
    resource = models.ForeignKey(
        TicketResource, on_delete=models.CASCADE, null=True, blank=True, related_name="cues"
    )
    seq = models.PositiveSmallIntegerField()
    template = models.CharField(max_length=40)
    status = models.CharField(max_length=12, choices=_choices(CueStatus))
    summary = models.TextField()
    evidence = models.JSONField(default=dict)
    query = models.ForeignKey(
        InfraQuery, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    link = models.TextField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "infra_ticket_cues"
        ordering = ["seq"]
