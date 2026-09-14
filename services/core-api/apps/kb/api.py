from __future__ import annotations

from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.kb.models import KbArticle
from apps.kb.services import (
    KBGovernanceError,
    ingest_article,
    set_auto_reply_allowed,
    set_risk_tier,
)

router = Router(tags=["kb"])


class ArticleIn(Schema):
    slug: str
    title: str
    body: str
    category: str
    risk_tier: str = "high"


class AutoReplyFlagIn(Schema):
    allowed: bool
    reason: str


class RiskTierIn(Schema):
    risk_tier: str
    reason: str


def _serialize(a: KbArticle) -> dict:
    return {
        "id": a.id,
        "slug": a.slug,
        "title": a.title,
        "category": a.category,
        "auto_reply_allowed": a.auto_reply_allowed,
        "risk_tier": a.risk_tier,
        "approved_by": a.approved_by_id,
        "is_active": a.is_active,
        "version": a.version,
    }


@router.get("", auth=JWTAuth())
def list_articles(request):
    return [_serialize(a) for a in KbArticle.objects.filter(is_active=True).order_by("slug")]


@router.post("", auth=JWTAuth())
def create_article(request, payload: ArticleIn):
    article = KbArticle.objects.create(**payload.dict())
    ingest_article(article)
    return _serialize(article)


@router.post("/{slug}/reingest", auth=JWTAuth())
def reingest(request, slug: str):
    article = _get_or_404(slug)
    chunks = ingest_article(article)
    return {"slug": slug, "chunks": len(chunks)}


@router.post("/{slug}/auto-reply-allowed", auth=JWTAuth())
def toggle_auto_reply(request, slug: str, payload: AutoReplyFlagIn):
    article = _get_or_404(slug)
    try:
        set_auto_reply_allowed(
            article=article, allowed=payload.allowed, actor=request.auth, reason=payload.reason
        )
    except KBGovernanceError as e:
        raise HttpError(403, str(e)) from e
    return _serialize(article)


@router.post("/{slug}/risk-tier", auth=JWTAuth())
def change_risk_tier(request, slug: str, payload: RiskTierIn):
    article = _get_or_404(slug)
    try:
        set_risk_tier(
            article=article, risk_tier=payload.risk_tier, actor=request.auth, reason=payload.reason
        )
    except KBGovernanceError as e:
        raise HttpError(403, str(e)) from e
    return _serialize(article)


def _get_or_404(slug: str) -> KbArticle:
    try:
        return KbArticle.objects.get(slug=slug)
    except KbArticle.DoesNotExist as e:
        raise HttpError(404, "KB article not found") from e
