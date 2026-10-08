"""
Final rerank node — spec §6.3. Jev's scores are the ones the floor and the
trust signals read; ClassifyCategoryNode, next, compares the floor and
decides refuse-before-LLM (spec §6.2).

The pool arrives in cross-encoder order (CandidatePoolNode). Jev scores its
top `rerank_pool` chunks, at most `rerank_max_chunks_per_page` from any one
page (ADR-0015); Jev's order and `rerank_score` are
final, and its top `rerank_top_n` go on. The floor is compared only with
`rerank_score`, never with the cross-encoder's or fusion's RRF score
(ADR-0005).
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.rerank.reranker import Passage, reranker
from ai_engine.graph.nodes.candidate_pool.links import article_titles
from ai_engine.graph.state import RankedChunk, TriageState


def jev_shortlist(pool: list[RankedChunk], *, size: int, per_page: int) -> list[RankedChunk]:
    """Jev's shortlist: the first `size` chunks of the cross-encoder's order,
    at most `per_page` of them from any one page. A slice of an order, never
    a threshold on the cross-encoder's score (ADR-0005).

    Unlimited, the 15 slots held a median of 8 distinct pages (2026-10-08
    probe): a page's 4th and 5th chunks took slots that a page further down
    could have used, and the cross-encoder ranks pages that are *about* the
    ticket above the page that resolves it, so that page was the one cut."""

    taken: list[RankedChunk] = []
    per_article: Counter[uuid.UUID] = Counter()
    for chunk in pool:
        if len(taken) == size:
            break
        if per_article[chunk.article_id] < per_page:
            per_article[chunk.article_id] += 1
            taken.append(chunk)
    return taken


class RerankNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        shortlist = jev_shortlist(
            state.pool, size=settings.rerank_pool, per_page=settings.rerank_max_chunks_per_page
        )
        if not shortlist:
            return {"reranked": []}

        titles = article_titles(list({r.article_id for r in shortlist}))
        scores = reranker.score(
            state.ticket.subject_masked,
            state.ticket.body_masked,
            [Passage(titles.get(r.article_id, ""), r.content) for r in shortlist],
        )
        if len(scores) != len(shortlist):
            raise ValueError(f"Jev returned {len(scores)} scores for {len(shortlist)}")

        ranked = sorted(zip(scores, shortlist, strict=True), key=lambda p: p[0], reverse=True)
        rescored = [r.model_copy(update={"rerank_score": s}) for s, r in ranked]
        return {"reranked": rescored[: settings.rerank_top_n]}


rerank = RerankNode()
