"""The weekly KB-gap report (F6 UC-F6-06): refused tickets grouped by topic, each topic labelled
`gap` or `update` by its nearest live page."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.kb.models import (
    GapLabel,
    GapState,
    KbChunk,
    KbGapCluster,
    KbGapClusterTicket,
    KbGapReport,
)
from apps.kb.utils.drafts import KbError, KbRefusal
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.review.models import Verdict
from apps.tickets.models import Ticket
from apps.tickets.utils.router import ReasonCode


@dataclass
class Topic:
    vectors: list[np.ndarray] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)

    def centroid(self) -> np.ndarray:
        mean = np.mean(self.vectors, axis=0)
        return mean / (np.linalg.norm(mean) or 1.0)


def unit(vector: object) -> np.ndarray:
    v = np.asarray(vector, dtype=float)
    return v / (np.linalg.norm(v) or 1.0)


class KbGaps:
    """Builds the report and dismisses its topics."""

    def refused(self, start: datetime, end: datetime) -> list[tuple[Ticket, np.ndarray]]:
        """Tickets in the window refused below the retrieval floor, or whose reviewer marked the KB
        answer wrong (BR-F6-07), with their embeddings."""
        rows = (
            Ticket.objects.filter(created_at__gte=start, created_at__lt=end)
            .filter(
                Q(routing_decisions__reason_code=ReasonCode.RETRIEVAL_FLOOR.value)
                | Q(review_items__decisions__kb_verdict=Verdict.WRONG.value)
            )
            .exclude(embedding_row__isnull=True)
            .select_related("embedding_row")
            .distinct()
            .order_by("created_at")
        )
        return [(t, unit(t.embedding_row.embedding)) for t in rows]

    def cluster(self, refused: list[tuple[Ticket, np.ndarray]]) -> list[Topic]:
        """Greedy: each ticket joins the closest topic whose centroid is within
        `kb_gaps.cluster_similarity`, else starts one."""
        bar = settings.THRESHOLDS.kb_gaps.cluster_similarity
        topics: list[Topic] = []
        for ticket, vector in refused:
            scored = [(float(vector @ t.centroid()), t) for t in topics]
            best = max(scored, key=lambda s: s[0], default=None)
            if best is not None and best[0] >= bar:
                topic = best[1]
            else:
                topic = Topic()
                topics.append(topic)
            topic.vectors.append(vector)
            topic.tickets.append(ticket)
        return topics

    def dismissed_centroids(self, now: datetime) -> list[np.ndarray]:
        return [
            unit(c.centroid)
            for c in KbGapCluster.objects.filter(
                state=GapState.DISMISSED.value, dismissed_until__gt=now
            ).exclude(centroid__isnull=True)
        ]

    def build(self) -> KbGapReport:
        """One report per window; a re-run on the same day replaces its open topics and keeps the
        ones already drafted or dismissed."""
        th = settings.THRESHOLDS.kb_gaps
        now = timezone.now()
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=th.window_days)
        refused = self.refused(start, end)
        with transaction.atomic():
            report, _ = KbGapReport.objects.update_or_create(
                window_start=start,
                window_end=end,
                defaults={"tickets_considered": len(refused)},
            )
            report.clusters.filter(state=GapState.OPEN.value).delete()
            known = self.dismissed_centroids(now) + [
                unit(c.centroid) for c in report.clusters.exclude(centroid__isnull=True)
            ]
            for topic in self.cluster(refused):
                if len(topic.tickets) < th.min_cluster_size:
                    continue
                centroid = topic.centroid()
                if any(float(centroid @ k) >= th.cluster_similarity for k in known):
                    continue
                self.record(report, topic, centroid)
        if report.clusters.exists():
            notifier.emit(
                NotificationEvent.KB_GAPS_READY,
                notice=Notice(
                    message=f"{report.clusters.count()} chủ đề",
                    link="/kb/gaps",
                    data={"report": str(report.id)},
                ),
            )
        AuditLog.objects.record(
            "kb_gaps_built",
            actor_type="system",
            payload={
                "report": str(report.id),
                "tickets": len(refused),
                "clusters": report.clusters.count(),
            },
        )
        return report

    def record(self, report: KbGapReport, topic: Topic, centroid: np.ndarray) -> KbGapCluster:
        nearest = (
            KbChunk.objects.filter(article__is_active=True)
            .exclude(embedding__isnull=True)
            .annotate(distance=CosineDistance("embedding", centroid.tolist()))
            .select_related("article")
            .order_by("distance")
            .first()
        )
        similarity = 1.0 - float(nearest.distance) if nearest is not None else None
        label = (
            GapLabel.UPDATE
            if similarity is not None
            and similarity >= settings.THRESHOLDS.kb_gaps.update_similarity
            else GapLabel.GAP
        )
        cluster = KbGapCluster.objects.create(
            report=report,
            label=label.value,
            size=len(topic.tickets),
            sample_tickets=[t.public_id for t in topic.tickets],
            nearest_article=nearest.article if nearest is not None else None,
            nearest_similarity=similarity,
            centroid=centroid.tolist(),
        )
        KbGapClusterTicket.objects.bulk_create(
            KbGapClusterTicket(cluster=cluster, ticket=t) for t in topic.tickets
        )
        return cluster

    def latest(self) -> KbGapReport | None:
        return KbGapReport.objects.order_by("-created_at").first()

    @transaction.atomic
    def dismiss(self, cluster_id: uuid.UUID, actor: User, reason: str) -> KbGapCluster:
        """Hides the topic from reports for `kb_gaps.dismiss_days`."""
        if not reason.strip():
            raise KbError(422, KbRefusal.REASON_REQUIRED, "say why the topic is dismissed")
        cluster = KbGapCluster.objects.select_for_update().filter(pk=cluster_id).first()
        if cluster is None:
            raise KbError(404, KbRefusal.CLUSTER_NOT_FOUND, "no such gap cluster")
        cluster.state = GapState.DISMISSED.value
        cluster.dismiss_reason = reason.strip()
        cluster.dismissed_until = timezone.now() + timedelta(
            days=settings.THRESHOLDS.kb_gaps.dismiss_days
        )
        cluster.save()
        AuditLog.objects.record(
            "kb_gap_dismissed",
            actor_type="human",
            actor_id=actor.id,
            payload={"cluster": str(cluster.id), "reason": cluster.dismiss_reason},
        )
        return cluster


# --- the gaps service ---

kb_gaps = KbGaps()
