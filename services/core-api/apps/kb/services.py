"""
KB governance (ADR-0002) + ingestion (chunk + embed an article).
"""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.kb.models import KbArticle, KbAuthorityLog, KbChunk
from infrastructure.embeddings import embed_text

CHUNK_TARGET_TOKENS = 250


def _rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def chunk_body(body: str) -> list[str]:
    """Paragraph-aware chunking targeting ~CHUNK_TARGET_TOKENS tokens per
    chunk. Simple and deterministic on purpose — retrieval quality here
    depends far more on chunk *boundaries respecting paragraphs* than on a
    fancier splitter."""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for p in paragraphs:
        p_tokens = _rough_token_count(p)
        if current and current_tokens + p_tokens > CHUNK_TARGET_TOKENS:
            chunks.append("\n\n".join(current))
            current, current_tokens = [], 0
        current.append(p)
        current_tokens += p_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [body]


@transaction.atomic
def ingest_article(article: KbArticle) -> list[KbChunk]:
    """(Re)chunks and (re)embeds a KB article. Existing chunks are
    replaced wholesale — simplest correct behavior for a KB whose update
    cadence is "occasional edits by a KB owner", not high-frequency."""

    KbChunk.objects.filter(article=article).delete()
    pieces = chunk_body(article.body)
    chunks: list[KbChunk] = []
    for i, content in enumerate(pieces):
        embedding = embed_text(content)
        chunk = KbChunk.objects.create(
            article=article,
            chunk_index=i,
            content=content,
            section_title=None,
            token_count=_rough_token_count(content),
            embedding=embedding,
        )
        chunks.append(chunk)
    # tsv is maintained by the Postgres trigger on INSERT/UPDATE OF content
    # (infra/migrations/sql/0003_constraints_and_triggers.sql), fired by
    # the .create() calls above — no separate step needed here.
    return chunks


def article_create(*, slug: str, title: str, body: str, category: str, risk_tier: str) -> KbArticle:
    """Creates a KB article and ingests it so retrieval can find it.

    Grants no auto-reply authority: `auto_reply_allowed` keeps its False
    default, and only `set_auto_reply_allowed` may change it (ADR-0002).
    """
    article = KbArticle.objects.create(
        slug=slug, title=title, body=body, category=category, risk_tier=risk_tier
    )
    # Committed before ingestion, not with it: if embedding fails, the article
    # is kept with no chunks (invisible to retrieval) and `/reingest` retries.
    ingest_article(article)
    return article


class KBGovernanceError(Exception):
    pass


@transaction.atomic
def set_auto_reply_allowed(
    *, article: KbArticle, allowed: bool, actor: User, reason: str
) -> KbArticle:
    """The only legitimate way to flip `auto_reply_allowed`. Spec §15 Q3 /
    ADR-0002: manager role required, reason mandatory, logged."""

    if not actor.is_manager:
        raise KBGovernanceError("only manager-role users may change auto_reply_allowed")
    if not reason or not reason.strip():
        raise KBGovernanceError("reason is required")

    old_value = str(article.auto_reply_allowed)
    article.auto_reply_allowed = allowed
    if allowed:
        article.approved_by = actor
        article.approved_at = timezone.now()
    article.version += 1
    article.save(
        update_fields=["auto_reply_allowed", "approved_by", "approved_at", "version", "updated_at"]
    )

    KbAuthorityLog.objects.create(
        article=article,
        field="auto_reply_allowed",
        old_value=old_value,
        new_value=str(allowed),
        actor=actor,
        reason=reason,
    )
    return article


@transaction.atomic
def set_risk_tier(*, article: KbArticle, risk_tier: str, actor: User, reason: str) -> KbArticle:
    if not actor.is_manager:
        raise KBGovernanceError("only manager-role users may change risk_tier")
    if not reason or not reason.strip():
        raise KBGovernanceError("reason is required")

    old_value = article.risk_tier
    article.risk_tier = risk_tier
    article.save(update_fields=["risk_tier", "updated_at"])

    KbAuthorityLog.objects.create(
        article=article,
        field="risk_tier",
        old_value=old_value,
        new_value=risk_tier,
        actor=actor,
        reason=reason,
    )
    return article
