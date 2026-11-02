"""A KB page's entity graph as a KB feature (F11, ADR-0037): its edges, editor overrides, rebuild
requests and the graph's health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.kb.models import (
    AssociationSource,
    KbArticle,
    KbArticleAssociation,
    KbAssociationOverride,
    KbGraphRebuildRequest,
    OverrideAction,
    RebuildReason,
    RebuildState,
)
from apps.kb.utils.drafts import KbError, KbRefusal
from apps.tickets.models import RoutingDecision
from apps.tickets.utils.router import Branch


@dataclass
class GraphOverride:
    action: str
    reason: str
    created_by: str
    created_at: datetime


@dataclass
class GraphEdge:
    """One pointer between two pages; `score` is None for an editor's added pointer with no
    built edge behind it."""

    slug: str
    title: str
    score: float | None
    evidence: list[str]
    build_id: str
    stale: bool
    reviewed: bool
    override: GraphOverride | None


@dataclass
class PageGraph:
    slug: str
    outgoing: list[GraphEdge]
    incoming: list[GraphEdge]
    last_build: KbGraphRebuildRequest | None
    pending_request: KbGraphRebuildRequest | None


@dataclass
class GraphHealth:
    pages: int
    pages_with_edges: int
    edges: int
    stale_edges: int
    hidden: int
    added: int
    # Pages whose latest rebuild request is pending, or failed.
    pending_requests: int
    failed_requests: int
    # Auto-replies in the period whose run reports chunk origins (runs since F11).
    auto_replies: int
    auto_replies_from_expansion: int

    @property
    def expansion_share(self) -> float | None:
        return self.auto_replies_from_expansion / self.auto_replies if self.auto_replies else None


def cited_by_expansion(retrieved_chunks: list[dict[str, Any]]) -> bool:
    """Whether the passage Jev scored highest, the one an auto-reply cites, came from link
    expansion."""
    scored = [c for c in retrieved_chunks if c.get("rerank_score") is not None]
    if not scored:
        return False
    top = max(scored, key=lambda c: float(c["rerank_score"]))
    return top.get("origin", "fused") == "expansion"


class KbGraph:
    """Reads a page's edges and records editors' corrections and rebuild requests."""

    def article(self, slug: str) -> KbArticle:
        article = KbArticle.objects.filter(slug=slug).first()
        if article is None:
            raise KbError(404, KbRefusal.ARTICLE_NOT_FOUND, "KB article not found")
        return article

    def edges(self) -> Any:
        return KbArticleAssociation.objects.filter(source=AssociationSource.ENTITY_GRAPH)

    def page(self, slug: str) -> PageGraph:
        article = self.article(slug)
        overrides = {
            (o.source_article_id, o.target_article_id): o
            for o in KbAssociationOverride.objects.filter(
                Q(source_article=article) | Q(target_article=article)
            ).select_related("created_by", "source_article", "target_article")
        }
        outgoing = [
            self.edge(
                row.target_article, row, overrides.pop((article.id, row.target_article_id), None)
            )
            for row in self.edges()
            .filter(source_article=article)
            .select_related("target_article")
            .order_by("-score", "target_article__slug")
        ]
        outgoing += [
            self.edge(o.target_article, None, o)
            for (source, _), o in overrides.items()
            if source == article.id and o.action == OverrideAction.ADD.value
        ]
        incoming = [
            self.edge(row.source_article, row, overrides.get((row.source_article_id, article.id)))
            for row in self.edges()
            .filter(target_article=article)
            .select_related("source_article")
            .order_by("-score", "source_article__slug")
        ]
        requests = KbGraphRebuildRequest.objects.filter(article=article)
        return PageGraph(
            slug=article.slug,
            outgoing=outgoing,
            incoming=incoming,
            last_build=requests.exclude(state=RebuildState.PENDING.value)
            .order_by("-done_at", "-requested_at")
            .first(),
            pending_request=requests.filter(state=RebuildState.PENDING.value).first(),
        )

    @staticmethod
    def edge(
        other: KbArticle,
        row: KbArticleAssociation | None,
        override: KbAssociationOverride | None,
    ) -> GraphEdge:
        return GraphEdge(
            slug=other.slug,
            title=other.title,
            score=row.score if row else None,
            evidence=list(row.evidence) if row else [],
            build_id=row.build_id if row else "",
            stale=row.stale if row else False,
            reviewed=row.reviewed if row else False,
            override=GraphOverride(
                action=override.action,
                reason=override.reason,
                created_by=override.created_by.username,
                created_at=override.created_at,
            )
            if override
            else None,
        )

    @transaction.atomic
    def confirm(self, slug: str, target: str, actor: User) -> GraphEdge:
        """Marks a built edge reviewed (UC-F11-02)."""
        article = self.article(slug)
        row = (
            self.edges()
            .select_for_update()
            .filter(source_article=article, target_article__slug=target)
            .select_related("target_article")
            .first()
        )
        if row is None:
            raise KbError(404, KbRefusal.EDGE_NOT_FOUND, "no entity-graph edge to that page")
        row.reviewed = True
        row.save(update_fields=["reviewed"])
        AuditLog.objects.record(
            "kb_graph_edge_confirmed",
            actor_type="user",
            actor_id=actor.id,
            payload={"source": article.slug, "target": target, "build_id": row.build_id},
        )
        override = KbAssociationOverride.objects.filter(
            source_article=article, target_article=row.target_article
        ).first()
        return self.edge(row.target_article, row, override)

    @transaction.atomic
    def add_override(
        self, slug: str, target: str, action: OverrideAction, reason: str, actor: User
    ) -> KbAssociationOverride:
        """Hides a pointer from link expansion, or adds one ranked first (BR-F11-03)."""
        article = self.article(slug)
        target_article = self.article(target)
        if target_article.id == article.id:
            raise KbError(422, KbRefusal.SELF_EDGE, "a page cannot point at itself")
        try:
            with transaction.atomic():
                override = KbAssociationOverride.objects.create(
                    source_article=article,
                    target_article=target_article,
                    action=action.value,
                    reason=reason,
                    created_by=actor,
                )
        except IntegrityError as e:
            raise KbError(
                409, KbRefusal.OVERRIDE_EXISTS, "this pair already has an override; remove it first"
            ) from e
        AuditLog.objects.record(
            "kb_graph_override_added",
            actor_type="user",
            actor_id=actor.id,
            payload={"source": slug, "target": target, "action": action.value, "reason": reason},
        )
        return override

    @transaction.atomic
    def remove_override(self, slug: str, target: str, reason: str, actor: User) -> None:
        article = self.article(slug)
        override = KbAssociationOverride.objects.filter(
            source_article=article, target_article__slug=target
        ).first()
        if override is None:
            raise KbError(404, KbRefusal.OVERRIDE_NOT_FOUND, "no override for that pair")
        action = override.action
        override.delete()
        AuditLog.objects.record(
            "kb_graph_override_removed",
            actor_type="user",
            actor_id=actor.id,
            payload={"source": slug, "target": target, "action": action, "reason": reason},
        )

    def rebuild(self, slug: str, actor: User) -> KbGraphRebuildRequest:
        """Files a manual rebuild request (UC-F11-03)."""
        article = self.article(slug)
        request = self.request_rebuild(article, RebuildReason.MANUAL, actor)
        if request is None:
            raise KbError(
                409, KbRefusal.ALREADY_PENDING, "a rebuild of this page is already pending"
            )
        return request

    @transaction.atomic
    def request_rebuild(
        self, article: KbArticle, reason: RebuildReason, actor: User | None = None
    ) -> KbGraphRebuildRequest | None:
        """A new pending request for `article`, or None when one is already pending."""
        try:
            with transaction.atomic():
                request = KbGraphRebuildRequest.objects.create(
                    article=article, requested_by=actor, reason=reason.value
                )
        except IntegrityError:
            return None
        AuditLog.objects.record(
            "kb_graph_rebuild_requested",
            actor_type="user" if actor else "system",
            actor_id=actor.id if actor else None,
            payload={"slug": article.slug, "reason": reason.value, "request": str(request.id)},
        )
        return request

    def mark_stale(self, article: KbArticle) -> int:
        """Flags every entity-graph edge touching `article` stale (BR-F11-01)."""
        return (
            self.edges()
            .filter(Q(source_article=article) | Q(target_article=article))
            .update(stale=True)
        )

    def health(self, since: datetime) -> GraphHealth:
        """The graph's coverage, corrections and the auto-replies since `since` whose cited
        passage came from link expansion (FR-F11-007)."""
        edges = self.edges().filter(source_article__is_active=True, target_article__is_active=True)
        overrides = KbAssociationOverride.objects.all()
        latest_states = (
            KbGraphRebuildRequest.objects.order_by("article_id", "-requested_at")
            .distinct("article_id")
            .values_list("state", flat=True)
        )
        auto_replies = [
            run_chunks
            for run_chunks in RoutingDecision.objects.filter(
                branch=Branch.AUTO_REPLY.value, decided_at__gte=since, ai_run__isnull=False
            ).values_list("ai_run__retrieved_chunks", flat=True)
            if run_chunks and any("origin" in c for c in run_chunks)
        ]
        return GraphHealth(
            pages=KbArticle.objects.filter(is_active=True).count(),
            pages_with_edges=edges.values("source_article").distinct().count(),
            edges=edges.count(),
            stale_edges=edges.filter(stale=True).count(),
            hidden=overrides.filter(action=OverrideAction.HIDE.value).count(),
            added=overrides.filter(action=OverrideAction.ADD.value).count(),
            pending_requests=sum(1 for s in latest_states if s == RebuildState.PENDING.value),
            failed_requests=sum(1 for s in latest_states if s == RebuildState.FAILED.value),
            auto_replies=len(auto_replies),
            auto_replies_from_expansion=sum(1 for c in auto_replies if cited_by_expansion(c)),
        )


# --- the page graph service ---

kb_graph = KbGraph()
