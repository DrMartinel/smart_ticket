"""Reporting facts (F10): one row per ticket, rebuilt nightly from the operational tables."""

from __future__ import annotations

from enum import StrEnum

from django.db import models

from apps.core.models import BaseModel


class FactState(StrEnum):
    MET = "met"
    BREACHED = "breached"
    RUNNING = "running"
    PAUSED = "paused"
    NONE = "none"


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class TicketFactsQuerySet(models.QuerySet["TicketFacts"]):
    def stopped(self, kind: str, start: object, end: object) -> TicketFactsQuerySet:
        """Rows whose `kind` clock stopped in [start, end): the SLA denominator (BR-F10-01)."""
        return self.filter(
            **{
                f"{kind}_met_at__gte": start,
                f"{kind}_met_at__lt": end,
                f"{kind}_state__in": [FactState.MET.value, FactState.BREACHED.value],
            }
        )


class TicketFacts(BaseModel):
    """What the reports need to know about one ticket, as of `built_at`."""

    ticket = models.OneToOneField("tickets.Ticket", on_delete=models.CASCADE, related_name="facts")
    created_day = models.DateField()
    team = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField(max_length=20, null=True, blank=True)
    priority = models.CharField(max_length=2, null=True, blank=True)
    source = models.CharField(max_length=10, blank=True, default="")
    handed_off_at = models.DateTimeField(null=True, blank=True)
    first_assigned_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    time_to_assign_business_min = models.FloatField(null=True, blank=True)
    response_state = models.CharField(
        max_length=10, choices=_choices(FactState), default=FactState.NONE.value
    )
    resolution_state = models.CharField(
        max_length=10, choices=_choices(FactState), default=FactState.NONE.value
    )
    response_met_at = models.DateTimeField(null=True, blank=True)
    resolution_met_at = models.DateTimeField(null=True, blank=True)
    response_warned_in_time = models.BooleanField(null=True, blank=True)
    resolution_warned_in_time = models.BooleanField(null=True, blank=True)
    reassign_count = models.PositiveIntegerField(default=0)
    cross_team_reassign_count = models.PositiveIntegerField(default=0)
    auto_replied = models.BooleanField(default=False)
    reopened = models.BooleanField(default=False)
    linked_incident = models.BooleanField(default=False)
    csat_score = models.SmallIntegerField(null=True, blank=True)
    csat_seq = models.SmallIntegerField(null=True, blank=True)
    csat_at = models.DateTimeField(null=True, blank=True)
    shadow_branch = models.CharField(max_length=20, null=True, blank=True)
    review_action = models.CharField(max_length=20, null=True, blank=True)
    category_corrected = models.BooleanField(default=False)
    built_at = models.DateTimeField()

    objects = TicketFactsQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "report_ticket_facts"
        indexes = [
            models.Index(fields=["team", "resolution_met_at"], name="idx_facts_team_resolution"),
            models.Index(fields=["built_at"], name="idx_facts_built_at"),
        ]
