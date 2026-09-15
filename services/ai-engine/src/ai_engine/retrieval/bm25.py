"""
BM25-style lexical retrieval over `kb_chunks.tsv` — spec §6.3. Uses
Postgres's `ts_rank_cd` (cover density ranking) rather than plain
`ts_rank`, since cover density rewards query terms appearing close
together, which matters for short error-code-heavy queries.

Error codes get an explicit post-hoc boost (spec: "weight cao cho mã lỗi:
0x[0-9A-F]{8}, ERR-\\d+") because `ts_rank_cd` alone treats `ERR-4042`
like any other token — it has no notion that a ticket quoting the exact
error code should be pulled far ahead of one that's merely topically
similar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_engine.config import settings

_ERROR_CODE_RE = re.compile(r"0x[0-9A-Fa-f]{8}|ERR-\d+")
ERROR_CODE_BOOST = 0.5


@dataclass(frozen=True)
class LexicalHit:
    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float


def extract_error_codes(text: str) -> list[str]:
    return _ERROR_CODE_RE.findall(text)


def bm25_search(conn, query_text: str) -> list[LexicalHit]:
    error_codes = extract_error_codes(query_text)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.article_id, a.slug, c.content,
                   ts_rank_cd(c.tsv, plainto_tsquery('simple', %(q)s)) AS score
            FROM kb_chunks c
            JOIN kb_articles a ON a.id = c.article_id
            WHERE c.tsv @@ plainto_tsquery('simple', %(q)s)
            ORDER BY score DESC
            LIMIT %(k)s
            """,
            {"q": query_text, "k": settings.bm25_top_k},
        )
        rows = cur.fetchall()

    hits = []
    for chunk_id, article_id, article_slug, content, score in rows:
        boosted = float(score)
        if error_codes and any(code in content for code in error_codes):
            boosted += ERROR_CODE_BOOST
        hits.append(
            LexicalHit(
                chunk_id=chunk_id,
                article_id=article_id,
                article_slug=article_slug,
                content=content,
                score=boosted,
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits
