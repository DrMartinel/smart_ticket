"""
Cross-encoder rerank node — spec §6.2/§6.3. This is where the refuse-
before-LLM decision actually happens: if the top reranked score is below
`retrieval_floor` (passed in per-request from core-api, spec §8/§13),
the graph routes straight to `emit_signals` and the LLM is never called.
That's both the biggest cost saver and the biggest safety property in the
graph — a model given no real source material has nothing to do but
fabricate one (spec §6.2 comment).

Thresholds apply ONLY to this node's output (the cross-encoder score),
never to the RRF score from fusion.py — see ADR-0005.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ai_engine.core.budget import BudgetedNode
from ai_engine.core.config import settings
from ai_engine.core.providers import Reranker
from ai_engine.core.state import TriageState
from ai_engine.retrieval.fusion import Candidate


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
