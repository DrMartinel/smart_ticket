from __future__ import annotations

from typing import Any

from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.kb.models import KbArticle
from apps.kb.schemas import ArticleIn, AutoReplyFlagIn, RiskTierIn, serialize_article
from apps.kb.services import (
    KBGovernanceError,
    article_create,
    ingest_article,
    set_auto_reply_allowed,
    set_risk_tier,
)
from common.permissions import AuthedRequest

router = Router(tags=["kb"])


@router.get("", auth=JWTAuth())
def list_articles(request: AuthedRequest) -> list[dict[str, Any]]:
    return [serialize_article(a) for a in KbArticle.objects.filter(is_active=True).order_by("slug")]


@router.post("", auth=JWTAuth())
def create_article(request: AuthedRequest, payload: ArticleIn) -> dict[str, Any]:
    article = article_create(
        slug=payload.slug,
        title=payload.title,
        body=payload.body,
        category=payload.category,
        risk_tier=payload.risk_tier,
    )
    return serialize_article(article)


@router.post("/{slug}/reingest", auth=JWTAuth())
def reingest(request: AuthedRequest, slug: str) -> dict[str, Any]:
    article = _get_or_404(slug)
    chunks = ingest_article(article)
    return {"slug": slug, "chunks": len(chunks)}


@router.post("/{slug}/auto-reply-allowed", auth=JWTAuth())
def toggle_auto_reply(
    request: AuthedRequest, slug: str, payload: AutoReplyFlagIn
) -> dict[str, Any]:
    article = _get_or_404(slug)
    try:
        set_auto_reply_allowed(
            article=article, allowed=payload.allowed, actor=request.auth, reason=payload.reason
        )
    except KBGovernanceError as e:
        raise HttpError(403, str(e)) from e
    return serialize_article(article)


@router.post("/{slug}/risk-tier", auth=JWTAuth())
def change_risk_tier(request: AuthedRequest, slug: str, payload: RiskTierIn) -> dict[str, Any]:
    article = _get_or_404(slug)
    try:
        set_risk_tier(
            article=article, risk_tier=payload.risk_tier, actor=request.auth, reason=payload.reason
        )
    except KBGovernanceError as e:
        raise HttpError(403, str(e)) from e
    return serialize_article(article)


def _get_or_404(slug: str) -> KbArticle:
    try:
        return KbArticle.objects.get(slug=slug)
    except KbArticle.DoesNotExist as e:
        raise HttpError(404, "KB article not found") from e
