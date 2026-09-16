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

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from ai_engine.core.config import settings
from ai_engine.core.db.tables import KbArticle, KbChunk

_ERROR_CODE_RE = re.compile(r"0x[0-9A-Fa-f]{8}|ERR-\d+")
ERROR_CODE_BOOST = 0.5


class LexicalHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float


def extract_error_codes(text: str) -> list[str]:
    return _ERROR_CODE_RE.findall(text)


def bm25_search(session, query_text: str) -> list[LexicalHit]:
    error_codes = extract_error_codes(query_text)

    tsquery = func.plainto_tsquery("simple", query_text)
    score = func.ts_rank_cd(KbChunk.tsv, tsquery).label("score")
    statement = (
        select(KbChunk.id, KbChunk.article_id, KbArticle.slug, KbChunk.content, score)
        .join(KbArticle, KbArticle.id == KbChunk.article_id)
        # `@@` has no SQLAlchemy operator; bool_op keeps it a boolean predicate.
        .where(KbChunk.tsv.bool_op("@@")(tsquery))
        .order_by(score.desc())
        .limit(settings.bm25_top_k)
    )
    rows = session.execute(statement).all()

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
