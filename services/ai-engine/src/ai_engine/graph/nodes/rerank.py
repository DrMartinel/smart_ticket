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

from pydantic import BaseModel, ConfigDict

from ai_engine.core.budget import BudgetedNode
from ai_engine.core.config import settings
from ai_engine.core.providers.base import Reranker
from ai_engine.core.retrieval.fusion import Candidate
from ai_engine.core.state import TriageState


class RankedChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float


class RerankNode(BudgetedNode):
    class Outcome(StrEnum):
        EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
        EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"

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

    def decide(self, state: TriageState) -> RerankNode.Outcome:
        reranked = state.reranked
        if not reranked or reranked[0].score < state.retrieval_floor:
            return self.Outcome.EVIDENCE_BELOW_FLOOR
        return self.Outcome.EVIDENCE_ABOVE_FLOOR
