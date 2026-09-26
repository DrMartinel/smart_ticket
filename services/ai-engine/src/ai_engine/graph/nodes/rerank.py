"""
Cross-encoder rerank node — spec §6.2/§6.3, where refuse-before-LLM is
decided. A top score below the per-request `retrieval_floor` routes straight
to `emit_signals`, so a model with no real source material is never asked to
fabricate one.

Thresholds apply ONLY to this node's score, never to fusion's RRF score
(ADR-0005).
"""

from __future__ import annotations

from enum import StrEnum

from ai_engine.core.budget import BudgetGuardMixin
from ai_engine.core.config import settings
from ai_engine.core.node import BaseNode
from ai_engine.core.providers.reranker import Reranker
from ai_engine.core.retrieval.fusion import Candidate
from ai_engine.core.state import RankedChunk, TriageState


class RerankOutcome(StrEnum):
    EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
    EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"


class RerankNode(BudgetGuardMixin, BaseNode):
    Outcome = RerankOutcome

    def __init__(self, *, reranker: Reranker) -> None:
        self._reranker = reranker

    def __call__(self, state: TriageState) -> dict:
        candidates: list[Candidate] = state.candidates
        if not candidates:
            return {"reranked": []}

        query = f"{state.ticket.subject_masked}\n{state.ticket.body_masked}"
        scores = self._reranker.score(query, [c.content for c in candidates])

        ranked = [
            RankedChunk(
                chunk_id=c.chunk_id,
                article_id=c.article_id,
                article_slug=c.article_slug,
                content=c.content,
                score=s,
            )
            for c, s in zip(candidates, scores)
        ]
        ranked.sort(key=lambda r: r.score, reverse=True)
        return {"reranked": ranked[: settings.rerank_top_n]}

    def decide(self, state: TriageState) -> RerankOutcome:
        reranked = state.reranked
        if not reranked or reranked[0].score < state.retrieval_floor:
            return RerankOutcome.EVIDENCE_BELOW_FLOOR
        return RerankOutcome.EVIDENCE_ABOVE_FLOOR
