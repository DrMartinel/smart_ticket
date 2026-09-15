"""Vector retrieval over `kb_chunks.embedding` — spec §6.3, pgvector cosine via HNSW."""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.config import settings


@dataclass(frozen=True)
class VectorHit:
    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float  # cosine similarity, [-1, 1] in theory, [0, 1] in practice for text embeddings


def to_vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(x) for x in embedding) + "]"


def vector_search(conn, query_embedding: list[float]) -> list[VectorHit]:
    literal = to_vector_literal(query_embedding)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.article_id, a.slug, c.content,
                   1 - (c.embedding <=> %(v)s::vector) AS score
            FROM kb_chunks c
            JOIN kb_articles a ON a.id = c.article_id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %(v)s::vector
            LIMIT %(k)s
            """,
            {"v": literal, "k": settings.vector_top_k},
        )
        rows = cur.fetchall()
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
