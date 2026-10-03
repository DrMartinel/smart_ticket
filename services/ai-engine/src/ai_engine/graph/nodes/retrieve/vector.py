"""Vector retrieval over `kb_chunks.embedding` — spec §6.3, pgvector cosine via HNSW."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle, KbChunk


class VectorHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    article_id: uuid.UUID
    article_slug: str
    content: str
    score: float  # cosine similarity, [-1, 1] in theory, [0, 1] in practice for text embeddings


def vector_search(query_embedding: list[float]) -> list[VectorHit]:
    distance = KbChunk.embedding.cosine_distance(query_embedding)
    statement = (
        select(
            KbChunk.id,
            KbChunk.article_id,
            KbArticle.slug,
            KbChunk.content,
            (1 - distance).label("score"),
        )
        .join(KbArticle, KbArticle.id == KbChunk.article_id)
        .where(KbChunk.embedding.is_not(None))
        # Order by the raw distance, not by `score`: `<=>` in ORDER BY is what
        # the HNSW index (vector_cosine_ops) can serve; `1 - <=>` is not.
        .order_by(distance)
        .limit(settings.vector_top_k)
    )
    rows = db.all(statement)
    return [
        VectorHit(
            chunk_id=chunk_id,
            article_id=article_id,
            article_slug=article_slug,
            content=content,
            score=float(score),
        )
        for chunk_id, article_id, article_slug, content, score in rows
    ]
