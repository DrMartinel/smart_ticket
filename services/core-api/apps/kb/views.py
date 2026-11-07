import uuid

from django.db.models import QuerySet
from django.http import HttpResponse
from ninja import Query, Router, Status
from ninja.pagination import LimitOffsetPagination, paginate

from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.kb.models import (
    DraftKind,
    GapState,
    KbArticle,
    KbAssociationOverride,
    KbAuthorityLog,
    KbDraft,
    KbGraphRebuildRequest,
)
from apps.kb.request_schema import (
    ArticleFilter,
    GraphOverrideIn,
    GraphReasonIn,
    ArticleIn,
    AuthorityLogFilter,
    AutoReplyFlagIn,
    BulkAllowedIn,
    GapDismissIn,
    DraftFilter,
    DraftIn,
    DraftPatchIn,
    DraftReviewIn,
    RiskTierIn,
)
from apps.kb.response_schema import (
    ArticleOut,
    AssociationOverrideOut,
    GraphEdgeOut,
    PageGraphOut,
    RebuildRequestOut,
    AuthorityLogOut,
    AuthorityQueueItemOut,
    BulkAllowedOut,
    DraftDiffOut,
    DraftOut,
    GapClusterOut,
    GapReportOut,
    ReingestOut,
)
from apps.kb.utils.authority import kb_authority
from apps.kb.utils.drafts import DraftDiff, kb_drafts
from apps.kb.utils.gaps import kb_gaps
from apps.kb.utils.graph import GraphEdge, PageGraph, kb_graph
from apps.kb.utils.indexing import indexer

router = Router(tags=["kb"])


# No `from __future__ import annotations` in this module: @paginate makes
# ninja resolve the handler's annotations from its own module, where string
# annotations like "ArticleFilter" are undefined.
@router.get("", auth=SessionAuth(), response=list[ArticleOut])
@paginate(LimitOffsetPagination)
@require(Permission.KB_PAGES_READ, agent=AgentTier.NONE)
def list_articles(request: AuthedRequest, filters: Query[ArticleFilter]) -> QuerySet[KbArticle]:
    return filters.filter(KbArticle.objects.filter(is_active=True)).order_by("slug")


@router.post("", auth=SessionAuth(), response={201: DraftOut})
@require(Permission.KB_PAGES_CREATE, agent=AgentTier.NONE)
def create_article(request: AuthedRequest, payload: ArticleIn) -> Status[KbDraft]:
    draft = kb_drafts.create(
        request.auth.user,
        {
            "kind": DraftKind.CREATE,
            "slug": payload.slug,
            "title": payload.title,
            "body": payload.body,
            "category": payload.category,
            "proposed_risk_tier": payload.risk_tier,
        },
    )
    return Status(201, draft)


@router.post("/{slug}/reingest", auth=SessionAuth(), response=ReingestOut)
@require(Permission.KB_PAGES_REINGEST, agent=AgentTier.NONE)
def reingest(request: AuthedRequest, slug: str) -> ReingestOut:
    article = kb_authority.article(slug)
    chunks = indexer.ingest(article)
    return ReingestOut(slug=slug, chunks=len(chunks))


@router.post("/{slug}/auto-reply-allowed", auth=SessionAuth(), response=ArticleOut)
@require(Permission.KB_AUTHORITY_GRANT, agent=AgentTier.NONE)
def toggle_auto_reply(request: AuthedRequest, slug: str, payload: AutoReplyFlagIn) -> KbArticle:
    return kb_authority.set_allowed(slug, request.auth.user, payload.allowed, payload.reason)


@router.post("/{slug}/risk-tier", auth=SessionAuth(), response=ArticleOut)
@require(Permission.KB_AUTHORITY_RISK_TIER, agent=AgentTier.NONE)
def change_risk_tier(request: AuthedRequest, slug: str, payload: RiskTierIn) -> KbArticle:
    return kb_authority.set_tier(slug, request.auth.user, payload.risk_tier, payload.reason)


# ── drafts (F6 UC-F6-01, 02, 07) ──


@router.get("/drafts", auth=SessionAuth(), response=list[DraftOut])
@paginate(LimitOffsetPagination)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def list_drafts(request: AuthedRequest, filters: Query[DraftFilter]) -> QuerySet[KbDraft]:
    rows = KbDraft.objects.select_related("author", "reviewer", "article").order_by("-updated_at")
    if filters.state:
        rows = rows.filter(state=filters.state.value)
    if filters.author:
        rows = rows.filter(author__username=filters.author)
    return rows


@router.post("/drafts", auth=SessionAuth(), response={201: DraftOut})
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def create_draft(request: AuthedRequest, payload: DraftIn) -> Status[KbDraft]:
    return Status(201, kb_drafts.create(request.auth.user, payload.model_dump()))


@router.get("/drafts/{draft_id}", auth=SessionAuth(), response=DraftOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def get_draft(request: AuthedRequest, draft_id: uuid.UUID) -> KbDraft:
    return kb_drafts.get(draft_id)


@router.patch("/drafts/{draft_id}", auth=SessionAuth(), response=DraftOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def update_draft(request: AuthedRequest, draft_id: uuid.UUID, payload: DraftPatchIn) -> KbDraft:
    return kb_drafts.update(draft_id, request.auth.user, payload.model_dump(exclude_none=True))


@router.post("/drafts/{draft_id}/submit", auth=SessionAuth(), response=DraftOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def submit_draft(request: AuthedRequest, draft_id: uuid.UUID) -> KbDraft:
    return kb_drafts.submit(draft_id, request.auth.user)


@router.post("/drafts/{draft_id}/review", auth=SessionAuth(), response=DraftOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def review_draft(request: AuthedRequest, draft_id: uuid.UUID, payload: DraftReviewIn) -> KbDraft:
    return kb_drafts.review(
        draft_id, request.auth.user, payload.decision == "approve", payload.comment
    )


@router.post("/drafts/{draft_id}/withdraw", auth=SessionAuth(), response=DraftOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def withdraw_draft(request: AuthedRequest, draft_id: uuid.UUID) -> KbDraft:
    return kb_drafts.withdraw(draft_id, request.auth.user)


@router.post("/drafts/{draft_id}/rebase", auth=SessionAuth(), response=DraftOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def rebase_draft(request: AuthedRequest, draft_id: uuid.UUID) -> KbDraft:
    return kb_drafts.rebase(draft_id, request.auth.user)


@router.get("/drafts/{draft_id}/diff", auth=SessionAuth(), response=DraftDiffOut)
@require(Permission.KB_DRAFTS_MANAGE, agent=AgentTier.NONE)
def draft_diff(request: AuthedRequest, draft_id: uuid.UUID) -> DraftDiff:
    return kb_drafts.diff(kb_drafts.get(draft_id))


# ── authority (UC-F6-03, 04, 05) ──


@router.get("/authority-queue", auth=SessionAuth(), response=list[AuthorityQueueItemOut])
@require(Permission.KB_AUTHORITY_QUEUE, agent=AgentTier.NONE)
def authority_queue(request: AuthedRequest) -> list[AuthorityQueueItemOut]:
    return [
        AuthorityQueueItemOut.of(item, kb_drafts.diff(item.draft) if item.draft else None)
        for item in kb_authority.queue()
    ]


@router.post("/auto-reply-allowed/bulk", auth=SessionAuth(), response=BulkAllowedOut)
@require(Permission.KB_AUTHORITY_GRANT, agent=AgentTier.NONE)
def bulk_auto_reply(request: AuthedRequest, payload: BulkAllowedIn) -> BulkAllowedOut:
    return BulkAllowedOut(
        updated=kb_authority.bulk(payload.slugs, request.auth.user, payload.allowed, payload.reason)
    )


@router.get("/authority-log", auth=SessionAuth(), response=list[AuthorityLogOut])
@paginate(LimitOffsetPagination)
@require(Permission.KB_AUTHORITY_LOG_READ, agent=AgentTier.NONE)
def authority_log(
    request: AuthedRequest, filters: Query[AuthorityLogFilter]
) -> QuerySet[KbAuthorityLog]:
    return kb_authority.log(**filters.dict())


@router.get("/authority-log.csv", auth=SessionAuth())
@require(Permission.KB_AUTHORITY_LOG_READ, agent=AgentTier.NONE)
def authority_log_csv(request: AuthedRequest, filters: Query[AuthorityLogFilter]) -> HttpResponse:
    response = HttpResponse(
        kb_authority.export(request.auth.user, filters.dict()),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="kb-authority-log.csv"'
    response["Cache-Control"] = "no-store"
    return response


# ── gaps (UC-F6-06) ──


@router.get("/gaps", auth=SessionAuth(), response=GapReportOut)
@require(Permission.KB_GAPS_MANAGE, agent=AgentTier.NONE)
def gaps(request: AuthedRequest) -> GapReportOut:
    report = kb_gaps.latest()
    clusters = (
        list(
            report.clusters.exclude(state=GapState.DISMISSED.value)
            .select_related("nearest_article")
            .prefetch_related("tickets", "drafts")
        )
        if report
        else []
    )
    return GapReportOut.of(report, clusters)


@router.post("/gaps/{cluster_id}/dismiss", auth=SessionAuth(), response=GapClusterOut)
@require(Permission.KB_GAPS_MANAGE, agent=AgentTier.NONE)
def dismiss_gap(
    request: AuthedRequest, cluster_id: uuid.UUID, payload: GapDismissIn
) -> GapClusterOut:
    return GapClusterOut.of(kb_gaps.dismiss(cluster_id, request.auth.user, payload.reason))


# ── page graph (F11, ADR-0037) ──


@router.get("/{slug}/graph", auth=SessionAuth(), response=PageGraphOut)
@require(Permission.KB_GRAPH_READ, agent=AgentTier.NONE)
def page_graph(request: AuthedRequest, slug: str) -> PageGraph:
    return kb_graph.page(slug)


@router.post("/{slug}/graph/edges/{target}/confirm", auth=SessionAuth(), response=GraphEdgeOut)
@require(Permission.KB_GRAPH_EDIT, agent=AgentTier.NONE)
def confirm_edge(request: AuthedRequest, slug: str, target: str) -> GraphEdge:
    return kb_graph.confirm(slug, target, request.auth.user)


@router.post("/{slug}/graph/overrides", auth=SessionAuth(), response={201: AssociationOverrideOut})
@require(Permission.KB_GRAPH_EDIT, agent=AgentTier.NONE)
def add_override(
    request: AuthedRequest, slug: str, payload: GraphOverrideIn
) -> Status[KbAssociationOverride]:
    override = kb_graph.add_override(
        slug, payload.target, payload.action, payload.reason, request.auth.user
    )
    return Status(201, override)


@router.delete("/{slug}/graph/overrides/{target}", auth=SessionAuth(), response={204: None})
@require(Permission.KB_GRAPH_EDIT, agent=AgentTier.NONE)
def remove_override(
    request: AuthedRequest, slug: str, target: str, payload: GraphReasonIn
) -> Status[None]:
    kb_graph.remove_override(slug, target, payload.reason, request.auth.user)
    return Status(204, None)


@router.post("/{slug}/graph/rebuild", auth=SessionAuth(), response={201: RebuildRequestOut})
@require(Permission.KB_GRAPH_REBUILD, agent=AgentTier.NONE)
def rebuild_graph(request: AuthedRequest, slug: str) -> Status[KbGraphRebuildRequest]:
    return Status(201, kb_graph.rebuild(slug, request.auth.user))
