from __future__ import annotations

from django.db.models import QuerySet
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.kb.models import KBGovernanceError, KbArticle
from apps.kb.request_schema import ArticleIn, AutoReplyFlagIn, RiskTierIn
from apps.kb.response_schema import ArticleOut, ReingestOut
from common.permissions import AuthedRequest

router = Router(tags=["kb"])


@router.get("", auth=JWTAuth(), response=list[ArticleOut])
def list_articles(request: AuthedRequest) -> QuerySet[KbArticle]:
    return KbArticle.objects.filter(is_active=True).order_by("slug")


@router.post("", auth=JWTAuth(), response=ArticleOut)
def create_article(request: AuthedRequest, payload: ArticleIn) -> KbArticle:
    return KbArticle.objects.create_and_ingest(
        slug=payload.slug,
        title=payload.title,
        body=payload.body,
        category=payload.category,
        risk_tier=payload.risk_tier,
    )


@router.post("/{slug}/reingest", auth=JWTAuth(), response=ReingestOut)
def reingest(request: AuthedRequest, slug: str) -> ReingestOut:
    article = _get_or_404(slug)
    chunks = article.ingest()
    return ReingestOut(slug=slug, chunks=len(chunks))


@router.post("/{slug}/auto-reply-allowed", auth=JWTAuth(), response=ArticleOut)
def toggle_auto_reply(request: AuthedRequest, slug: str, payload: AutoReplyFlagIn) -> KbArticle:
    article = _get_or_404(slug)
    try:
        article.set_auto_reply_allowed(
            allowed=payload.allowed, actor=request.auth, reason=payload.reason
        )
    except KBGovernanceError as e:
        raise HttpError(403, str(e)) from e
    return article


@router.post("/{slug}/risk-tier", auth=JWTAuth(), response=ArticleOut)
def change_risk_tier(request: AuthedRequest, slug: str, payload: RiskTierIn) -> KbArticle:
    article = _get_or_404(slug)
    try:
        article.set_risk_tier(
            risk_tier=payload.risk_tier, actor=request.auth, reason=payload.reason
        )
    except KBGovernanceError as e:
        raise HttpError(403, str(e)) from e
    return article


def _get_or_404(slug: str) -> KbArticle:
    try:
        return KbArticle.objects.get(slug=slug)
    except KbArticle.DoesNotExist as e:
        raise HttpError(404, "KB article not found") from e
