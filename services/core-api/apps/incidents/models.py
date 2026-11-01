"""Which tickets belong to an incident, and what it told their requesters (F7)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class IncidentLinkQuerySet(models.QuerySet["IncidentLink"]):
    def active(self) -> IncidentLinkQuerySet:
        return self.filter(unlinked_at__isnull=True)


class IncidentLink(BaseModel):
    """A ticket in an incident; at most one active link per ticket."""

    incident = models.ForeignKey("tickets.Incident", on_delete=models.CASCADE, related_name="links")
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="incident_links"
    )
    # detector | matcher | a username
    linked_by = models.CharField(max_length=150)
    linked_at = models.DateTimeField(auto_now_add=True)
    similarity = models.FloatField(null=True, blank=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)
    unlink_reason = models.TextField(blank=True, default="")

    objects = IncidentLinkQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "incident_links"
        constraints = [
            models.UniqueConstraint(
                fields=["ticket"],
                condition=models.Q(unlinked_at__isnull=True),
                name="incident_links_one_active_per_ticket",
            )
        ]


class IncidentBroadcast(BaseModel):
    """One update sent once to every linked requester (BR-F7-05), masked."""

    incident = models.ForeignKey(
        "tickets.Incident", on_delete=models.CASCADE, related_name="broadcasts"
    )
    stage = models.CharField(max_length=15)
    body_vi_masked = models.TextField()
    body_en_masked = models.TextField(blank=True, default="")
    eta = models.DateTimeField(null=True, blank=True)
    eta_unknown = models.BooleanField(default=False)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    requesters_count = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        db_table = "incident_broadcasts"
        ordering = ["-sent_at"]
