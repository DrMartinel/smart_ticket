"""
Final rerank node — spec §6.3. Jev's scores are the ones the floor and the
trust signals read; ClassifyCategoryNode, next, compares the floor and
decides refuse-before-LLM (spec §6.2).

The pool arrives in cross-encoder order (CandidatePoolNode). Jev scores its
top `rerank_pool` chunks, at most `rerank_max_chunks_per_page` from any one
page (ADR-0015); Jev's order and `rerank_score` are
final, and its top `rerank_top_n` go on, at most `rerank_top_n_per_page` from
one page. The floor is compared only with
`rerank_score`, never with the cross-encoder's or fusion's RRF score
(ADR-0005).

Under `SHORTLIST_PROVIDER=none` there is no cross-encoder order: the pool
arrives already scored by Jev (CandidatePoolNode), and this node only cuts
its top `rerank_top_n`.
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


def first_per_page(chunks: list[RankedChunk], *, size: int, per_page: int) -> list[RankedChunk]:
    """The first `size` of `chunks`, in their order, at most `per_page` from
    any one page; a page's further chunks give way to the next page's."""

    taken: list[RankedChunk] = []
    per_article: Counter[uuid.UUID] = Counter()
    for chunk in chunks:
        if len(taken) == size:
            break
        if per_article[chunk.article_id] < per_page:
            per_article[chunk.article_id] += 1
            taken.append(chunk)
    return taken


def jev_shortlist(pool: list[RankedChunk], *, size: int, per_page: int) -> list[RankedChunk]:
    """Jev's shortlist: the first `size` chunks of the cross-encoder's order,
    at most `per_page` of them from any one page. A slice of an order, never
    a threshold on the cross-encoder's score (ADR-0005).

    Unlimited, the 15 slots held a median of 8 distinct pages (2026-10-08
    probe): a page's 4th and 5th chunks took slots that a page further down
    could have used, and the cross-encoder ranks pages that are *about* the
    ticket above the page that resolves it, so that page was the one cut."""

    return first_per_page(pool, size=size, per_page=per_page)


def top_n(ranked: list[RankedChunk]) -> list[RankedChunk]:
    """Jev's top `rerank_top_n`, at most `rerank_top_n_per_page` from one
    page. Recall@3 counts pages: a page's second chunk in the top 3 holds a
    slot another page could use (2026-10-10, g052 and g053 had one page in
    all three). A cut of Jev's order, never a threshold (ADR-0005)."""

    return first_per_page(
        ranked, size=settings.rerank_top_n, per_page=settings.rerank_top_n_per_page
    )


def jev_scored(state: TriageState, chunks: list[RankedChunk]) -> list[RankedChunk]:
    """`chunks` with Jev's `rerank_score`, in Jev's order. Raises on any
    failure, or on a reply that doesn't score every chunk: never a partial
    list."""

    if not chunks:
        return []
    titles = article_titles(list({r.article_id for r in chunks}))
    scores = reranker.score(
        state.ticket.subject_masked,
        state.ticket.body_masked,
        [Passage(titles.get(r.article_id, ""), r.content) for r in chunks],
    )
    if len(scores) != len(chunks):
        raise ValueError(f"Jev returned {len(scores)} scores for {len(chunks)}")
    ranked = sorted(zip(scores, chunks, strict=True), key=lambda p: p[0], reverse=True)
    return [r.model_copy(update={"rerank_score": s}) for s, r in ranked]


class RerankNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        if settings.shortlist_provider == "none":
            # CandidatePoolNode had Jev score the whole pool, in Jev's order:
            # no shortlist to cut, no second call.
            return {"reranked": top_n(state.pool)}

        shortlist = jev_shortlist(
            state.pool, size=settings.rerank_pool, per_page=settings.rerank_max_chunks_per_page
        )
        return {"reranked": top_n(jev_scored(state, shortlist))}


rerank = RerankNode()
