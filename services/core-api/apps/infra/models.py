"""One row per read of the cloud or its observability: who asked, through what, what was
sent and how it ended (F17, ADR-0048 §9)."""

from __future__ import annotations

from enum import StrEnum

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import BaseModel


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class InfraVia(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


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
    """One query a person or their agent made, and what came of it."""

    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    via = models.CharField(max_length=8, choices=_choices(InfraVia))
    agent_turn = models.ForeignKey(
        "agent.AgentTurn", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    backend = models.CharField(max_length=16, choices=_choices(InfraBackend))
    kind = models.CharField(max_length=16, choices=_choices(InfraQueryKind))
    compiled = models.TextField()
    projects = ArrayField(models.CharField(max_length=64), default=list)
    outcome = models.CharField(max_length=24, choices=_choices(InfraOutcome))
    refusal = models.CharField(max_length=40, null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    rows = models.PositiveIntegerField(default=0)
    withheld = models.PositiveIntegerField(default=0)
    link = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "infra_queries"
