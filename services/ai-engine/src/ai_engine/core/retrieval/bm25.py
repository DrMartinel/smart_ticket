"""
BM25 lexical retrieval over `kb_chunks` — spec §6.3, via ParadeDB pg_search
(ADR-0013).

Real BM25: IDF means a rare token ("GuardDuty", an error code) outweighs
filler that appears on every page. `|||` is match-disjunction, so a chunk
needs only some of the ticket's words, not all of them. The spec's
`plainto_tsquery` + `ts_rank_cd` required every word in one chunk and matched
nothing on the English golden set, and `ts_rank_cd` has no IDF at all.

`pdb.score` only ORDERS hits here. It is query-dependent and means nothing
across tickets, so nothing may compare it with a number (ADR-0005's rule,
applied to BM25 too). Only ranks leave this channel.

Error codes (`0x1A2B3C4D`, `ERR-4042`) still get an explicit boost on top.
"""

from __future__ import annotations

import uuid

import re

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ai_engine.core.config import settings
from ai_engine.core.db.tables import KbArticle, KbChunk

_ERROR_CODE_RE = re.compile(r"0x[0-9A-Fa-f]{8}|ERR-\d+")


class LexicalHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    article_id: uuid.UUID
    article_slug: str
    content: str
    score: float


def bm25_search(session: Session, query_text: str) -> list[LexicalHit]:
    error_codes = _ERROR_CODE_RE.findall(query_text)

    score = func.pdb.score(KbChunk.id).label("score")
    statement = (
        select(KbChunk.id, KbChunk.article_id, KbArticle.slug, KbChunk.content, score)
        .join(KbArticle, KbArticle.id == KbChunk.article_id)
        # `|||` has no SQLAlchemy operator; is_comparison keeps it a boolean
        # predicate. Both columns are in the one BM25 index (idx_chunk_bm25).
        .where(
            or_(
                KbChunk.content.op("|||", is_comparison=True)(query_text),
                KbChunk.section_title.op("|||", is_comparison=True)(query_text),
            )
        )
        .order_by(score.desc())
        .limit(settings.bm25_top_k)
    )
    rows = session.execute(statement).all()

    hits = []
    for chunk_id, article_id, article_slug, content, score in rows:
        boosted = float(score)
        if error_codes and any(code in content for code in error_codes):
            boosted += settings.bm25_error_code_boost
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
