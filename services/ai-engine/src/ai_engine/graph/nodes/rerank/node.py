"""
Final rerank node — spec §6.3. Jev's scores are the ones the floor and the
trust signals read; ClassifyCategoryNode, next, compares the floor and
decides refuse-before-LLM (spec §6.2).

The pool arrives in cross-encoder order (CandidatePoolNode). Jev ranks its
top `rerank_pool` chunks with one choice question (ADR-0026); Jev's order
and `rerank_score` (its probability) are final, chunks Jev scores alike keep
the cross-encoder's order, and its top `rerank_top_n` go on, at most
`rerank_top_n_per_page` from one page. `rerank_total`, the probability
Jev gives the passages together, is what the floor is compared with: Jev's
score, never the cross-encoder's or fusion's RRF score
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


class RerankNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        shortlist = state.pool[: settings.rerank_pool]
        if not shortlist:
            return {"reranked": []}

        titles = article_titles(list({r.article_id for r in shortlist}))
        answer = reranker.rank(
            state.ticket.subject_masked,
            state.ticket.body_masked,
            [Passage(titles.get(r.article_id, ""), r.content) for r in shortlist],
        )
        if len(answer.scores) != len(shortlist):
            raise ValueError(f"Jev returned {len(answer.scores)} scores for {len(shortlist)}")

        ranked = sorted(
            zip(answer.scores, shortlist, strict=True), key=lambda p: p[0], reverse=True
        )
        rescored = [r.model_copy(update={"rerank_score": s}) for s, r in ranked]
        return {
            "reranked": self._top_n(rescored),
            "rerank_choice": (
                None if answer.choice is None else shortlist[answer.choice].article_slug
            ),
            "rerank_confidence": answer.confidence,
            "rerank_total": min(1.0, sum(answer.scores)),
        }

    @staticmethod
    def _top_n(chunks: list[RankedChunk]) -> list[RankedChunk]:
        """Takes the first `rerank_top_n` chunks in order, at most
        `rerank_top_n_per_page` from one page."""

        taken: list[RankedChunk] = []
        per_article: Counter[uuid.UUID] = Counter()
        for chunk in chunks:
            if len(taken) == settings.rerank_top_n:
                break
            if per_article[chunk.article_id] < settings.rerank_top_n_per_page:
                per_article[chunk.article_id] += 1
                taken.append(chunk)
        return taken


rerank = RerankNode()
