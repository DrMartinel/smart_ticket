"""
Incident Detector — spec §9. Distinguishes an ordinary duplicate from a
mass incident using an ADAPTIVE threshold (baseline + 3σ over a rolling
30-day window per category), not a fixed constant — 5 network tickets in
15 minutes is normal at a 5000-person company and abnormal at a
100-person one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from django.conf import settings
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.tickets.models import Incident, Ticket, TicketEmbedding
from apps.tickets.services.ids import next_incident_public_id


@dataclass(frozen=True)
class IncidentVerdict:
    kind: Literal["unique", "duplicate", "mass_incident"]
    of: int | None = None  # ticket id, for duplicates
    parent: Incident | None = None
    baseline_rate: float | None = None


def find_similar(embedding: list[float], category: str | None, threshold: float, window: timedelta) -> list[Ticket]:
    since = timezone.now() - window
    qs = (
        Ticket.objects.filter(created_at__gte=since)
        .exclude(embedding_row__isnull=True)
        .annotate(distance=CosineDistance("embedding_row__embedding", embedding))
        .filter(distance__lte=1 - threshold)
        .order_by("distance")
    )
    if category:
        qs = qs.filter(category=category)
    return list(qs)


def rolling_baseline(category: str | None, days: int = 30, window_minutes: int = 15) -> tuple[float, float]:
    """Mean and stddev of ticket count per `window_minutes` bucket, over
    the trailing `days` window, for the given category. Returns (mean,
    std). With too little history, falls back to a conservative (0, 0) so
    the 3-sigma check simply requires `min_count` to trigger — better to
    lean toward escalation early than to silently need a month of data
    before mass-incident detection works at all."""

    since = timezone.now() - timedelta(days=days)
    qs = Ticket.objects.filter(created_at__gte=since)
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


def classify_similarity(ticket: Ticket, embedding: list[float]) -> IncidentVerdict:
    th = settings.THRESHOLDS.incident
    window = timedelta(minutes=th.window_minutes)

    similar = find_similar(embedding, ticket.category, th.similarity, window)
    if not similar:
        return IncidentVerdict(kind="unique")

    baseline, sigma = rolling_baseline(ticket.category, days=30, window_minutes=th.window_minutes)

    if len(similar) > baseline + th.sigma_multiplier * sigma and len(similar) >= th.min_count:
        parent = _get_or_create_incident(ticket, similar, baseline)
        return IncidentVerdict(kind="mass_incident", parent=parent, baseline_rate=baseline)

    return IncidentVerdict(kind="duplicate", of=similar[0].id)


def _get_or_create_incident(ticket: Ticket, similar: list[Ticket], baseline_rate: float) -> Incident:
    existing = Incident.objects.filter(
        category=ticket.category, status="open", created_at__gte=timezone.now() - timedelta(hours=6)
    ).first()
    if existing:
        existing.ticket_count = len(similar) + 1
        existing.save(update_fields=["ticket_count"])
        return existing

    incident = Incident.objects.create(
        public_id=next_incident_public_id(),
        title=f"Mass incident: {ticket.category or 'uncategorized'} — {ticket.subject_masked[:80]}",
        category=ticket.category or "other",
        severity="high",
        detected_by="density_detector",
        ticket_count=len(similar) + 1,
        detection_window_min=settings.THRESHOLDS.incident.window_minutes,
        baseline_rate=baseline_rate,
        status="open",
    )
    # Link every ticket that contributed to the detection, so the parent
    # incident view can notify every affected reporter at once — the
    # actual value described in spec §9 ("40 người nhận 1 thông báo có ETA").
    Ticket.objects.filter(id__in=[t.id for t in similar]).update(incident=incident)
    return incident


def store_embedding(ticket: Ticket, embedding: list[float], model_name: str) -> TicketEmbedding:
    return TicketEmbedding.objects.update_or_create(
        ticket=ticket, defaults={"model": model_name, "embedding": embedding}
    )[0]
