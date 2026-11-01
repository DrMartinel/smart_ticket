"""
Response shapes for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import TYPE_CHECKING

from ninja import Field, Schema
from pydantic import AliasChoices

if TYPE_CHECKING:
    from apps.kb.models import KbAuthorityLog, KbGapCluster, KbGapReport
    from apps.kb.utils.authority import QueueItem
    from apps.kb.utils.drafts import DraftDiff


class ArticleOut(Schema):
    id: uuid.UUID
    slug: str
    title: str
    category: str
    source_url: str
    auto_reply_allowed: bool
    risk_tier: str
    approved_by: uuid.UUID | None = Field(
        validation_alias=AliasChoices("approved_by_id", "approved_by")
    )
    is_active: bool
    version: int


class ReingestOut(Schema):
    slug: str
    chunks: int


class UserRefOut(Schema):
    id: uuid.UUID
    username: str


class DraftOut(Schema):
    id: uuid.UUID
    kind: str
    slug: str
    title: str
    body: str
    category: str
    proposed_risk_tier: str
    change_note: str
    state: str
    base_version: int | None
    author: UserRefOut
    reviewer: UserRefOut | None
    review_comment: str
    gap_cluster_id: uuid.UUID | None
    article: ArticleOut | None
    authority_pending: bool
    authority_reason: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class ChunkPreviewOut(Schema):
    section_title: str | None
    content: str


class DraftDiffOut(Schema):
    title_diff: list[str]
    body_diff: list[str]
    chunks_preview: list[ChunkPreviewOut]


class AuthorityQueueItemOut(Schema):
    article: ArticleOut
    reason: str
    draft_id: uuid.UUID | None
    proposed_risk_tier: str | None
    change_note: str
    published_at: datetime | None
    published_by: str | None
    title_diff: list[str]
    body_diff: list[str]

    @classmethod
    def of(cls, item: QueueItem, diff: DraftDiff | None) -> AuthorityQueueItemOut:
        draft = item.draft
        return cls.model_validate(
            {
                "article": item.article,
                "reason": item.reason,
                "draft_id": draft.id if draft else None,
                "proposed_risk_tier": draft.proposed_risk_tier if draft else None,
                "change_note": draft.change_note if draft else "",
                "published_at": draft.published_at if draft else None,
                "published_by": draft.reviewer.username if draft and draft.reviewer else None,
                "title_diff": diff.title_diff if diff else [],
                "body_diff": diff.body_diff if diff else [],
            }
        )


class BulkAllowedOut(Schema):
    updated: int


class AuthorityLogOut(Schema):
    id: uuid.UUID
    slug: str
    field: str
    old_value: str | None
    new_value: str | None
    actor: str
    reason: str
    changed_at: datetime

    @staticmethod
    def resolve_slug(obj: KbAuthorityLog) -> str:
        return obj.article.slug

    @staticmethod
    def resolve_actor(obj: KbAuthorityLog) -> str:
        return obj.actor.username


class GapTicketOut(Schema):
    public_id: str
    subject_masked: str


class GapClusterOut(Schema):
    id: uuid.UUID
    label: str
    size: int
    tickets: list[GapTicketOut]
    nearest_slug: str | None
    nearest_title: str | None
    nearest_similarity: float | None
    state: str
    dismiss_reason: str
    dismissed_until: datetime | None
    draft_id: uuid.UUID | None

    @classmethod
    def of(cls, cluster: KbGapCluster) -> GapClusterOut:
        nearest = cluster.nearest_article
        drafts = list(cluster.drafts.all())
        return cls(
            id=cluster.id,
            label=cluster.label,
            size=cluster.size,
            tickets=[
                GapTicketOut(public_id=t.public_id, subject_masked=t.subject_masked)
                for t in cluster.tickets.all()
            ],
            nearest_slug=nearest.slug if nearest else None,
            nearest_title=nearest.title if nearest else None,
            nearest_similarity=cluster.nearest_similarity,
            state=cluster.state,
            dismiss_reason=cluster.dismiss_reason,
            dismissed_until=cluster.dismissed_until,
            draft_id=drafts[0].id if drafts else None,
        )


class GapReportOut(Schema):
    id: uuid.UUID | None
    window_start: datetime | None
    window_end: datetime | None
    tickets_considered: int
    clusters: list[GapClusterOut]

    @classmethod
    def of(cls, report: KbGapReport | None, clusters: list[KbGapCluster]) -> GapReportOut:
        return cls(
            id=report.id if report else None,
            window_start=report.window_start if report else None,
            window_end=report.window_end if report else None,
            tickets_considered=report.tickets_considered if report else 0,
            clusters=[GapClusterOut.of(c) for c in clusters],
        )
