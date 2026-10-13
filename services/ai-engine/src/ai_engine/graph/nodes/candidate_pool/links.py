"""
Link expansion (ADR-0014 decisions 1-2, ADR-0015, ADR-0018): reads the
articles associated with a seed from `kb_article_associations`, in the one
source `ASSOCIATION_SOURCE` names, and their chunks nearest the draft.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from sqlalchemy import func, select

from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle, KbArticleAssociation, KbChunk
from ai_engine.graph.state import Candidate


class Association(NamedTuple):
    seed: uuid.UUID
    target: uuid.UUID
    score: float


def associations(seed_ids: list[uuid.UUID], *, max_per_seed: int) -> list[Association]:
    """Reads each seed's associations to active articles, seed by seed, best
    score first, at most `max_per_seed` per seed."""

    if not seed_ids or settings.association_source == "none":
        return []
    association = KbArticleAssociation
    ranked = (
        select(
            association.source_article_id,
            association.target_article_id,
            association.score,
            func.row_number()
            .over(
                partition_by=association.source_article_id,
                # The id breaks score ties, so the same rows give the same order.
                order_by=(association.score.desc(), association.target_article_id),
            )
            .label("rank"),
        )
        .join(KbArticle, KbArticle.id == association.target_article_id)
        .where(
            association.source_article_id.in_(seed_ids),
            association.source == settings.association_source,
            KbArticle.is_active.is_(True),
        )
        .subquery()
    )
    rows = db.all(
        select(ranked.c.source_article_id, ranked.c.target_article_id, ranked.c.score)
        .where(ranked.c.rank <= max_per_seed)
        .order_by(ranked.c.source_article_id, ranked.c.rank)
    )

    by_seed: dict[uuid.UUID, list[Association]] = {seed: [] for seed in seed_ids}
    for seed, target, score in rows:
        # The table's CHECK forbids self-pairs; skipped here as well, so a
        # seed never expands to itself whatever wrote the row.
        if target != seed:
            by_seed[seed].append(Association(seed, target, float(score)))
    return [a for seed in seed_ids for a in by_seed[seed]]


def linked_article_ids(seed_ids: list[uuid.UUID], *, max_per_seed: int) -> list[uuid.UUID]:
    """Active articles associated with `seed_ids`, in `associations()`'s
    order, each article once. A target that is another seed or a fused
    candidate is kept, since that page may have better chunks than the ones
    retrieved (the caller de-duplicates chunks)."""

    linked: list[uuid.UUID] = []
    for a in associations(seed_ids, max_per_seed=max_per_seed):
        if a.target not in linked:
            linked.append(a.target)
    return linked


def nearest_chunks(
    article_ids: list[uuid.UUID],
    query_embedding: list[float],
    *,
    per_article: int,
) -> list[Candidate]:
    """Each article's `per_article` chunks nearest the query embedding, in
    one query. Pages are long; their best chunks for this ticket are the
    ones worth scoring."""

    if not article_ids:
        return []
    distance = KbChunk.embedding.cosine_distance(query_embedding)
    ranked = (
        select(
            KbChunk.id,
            KbChunk.article_id,
            KbArticle.slug,
            KbChunk.content,
            func.row_number()
            .over(partition_by=KbChunk.article_id, order_by=distance)
            .label("rank"),
        )
        .join(KbArticle, KbArticle.id == KbChunk.article_id)
        .where(KbChunk.article_id.in_(article_ids), KbChunk.embedding.is_not(None))
        .subquery()
    )
    rows = db.all(
        select(ranked.c.id, ranked.c.article_id, ranked.c.slug, ranked.c.content)
        .where(ranked.c.rank <= per_article)
        .order_by(ranked.c.article_id, ranked.c.rank)
    )
    return [
        Candidate(chunk_id=cid, article_id=aid, article_slug=slug, content=content)
        for cid, aid, slug, content in rows
    ]


def article_titles(article_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Titles for Jev, which sees each passage with its page title."""

    if not article_ids:
        return {}
    return {
        article_id: title
        for article_id, title in db.all(
            select(KbArticle.id, KbArticle.title).where(KbArticle.id.in_(article_ids))
        )
    }
