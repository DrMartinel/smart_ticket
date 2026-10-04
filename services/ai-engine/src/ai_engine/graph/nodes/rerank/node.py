"""
Final rerank node — spec §6.3. Jev's scores are the ones the floor and the
trust signals read; ClassifyCategoryNode, next, compares the floor and
decides refuse-before-LLM (spec §6.2).

The pool arrives in cross-encoder order (CandidatePoolNode). Jev scores its
top `rerank_pool` chunks (ADR-0015); Jev's order and `rerank_score` are
final, and its top `rerank_top_n` go on. The floor is compared only with
`rerank_score`, never with the cross-encoder's or fusion's RRF score
(ADR-0005).
"""

from __future__ import annotations

from typing import Any

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.rerank.reranker import Passage, reranker
from ai_engine.graph.nodes.candidate_pool.links import article_titles
from ai_engine.graph.state import TriageState


class RerankNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        shortlist = state.pool[: settings.rerank_pool]
        if not shortlist:
            return {"reranked": []}

        titles = article_titles(list({r.article_id for r in shortlist}))
        # A Jev failure raises: falling back to the cross-encoder's order
        # would put its scores against a floor set for Jev's.
        scores = reranker.score(
            state.ticket.subject_masked,
            state.ticket.body_masked,
            [Passage(titles.get(r.article_id, ""), r.content) for r in shortlist],
        )
        if len(scores) != len(shortlist):
            raise ValueError(f"Jev returned {len(scores)} scores for {len(shortlist)}")

        # Jev's score goes beside the cross-encoder's, which stays. Stable:
        # ties keep the cross-encoder's order.
        ranked = sorted(zip(scores, shortlist, strict=True), key=lambda p: p[0], reverse=True)
        rescored = [r.model_copy(update={"rerank_score": s}) for s, r in ranked]
        return {"reranked": rescored[: settings.rerank_top_n]}


rerank = RerankNode()
