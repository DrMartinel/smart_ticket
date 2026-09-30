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
from uuid import UUID

from ai_engine.core.config import settings
from ai_engine.core.node import BaseNode, StateUpdate
from ai_engine.core.providers.reranker import reranker
from ai_engine.core.retrieval.fusion import Candidate
from ai_engine.core.state import RankedChunk, TriageState


class RerankOutcome(StrEnum):
    EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
    EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"


def _best_chunk_per_article(ranked: list[RankedChunk]) -> list[RankedChunk]:
    """Keeps each article's highest-scoring chunk, in `ranked`'s order.

    Articles average ~8 chunks, and without this one article's chunks can
    fill every `rerank_top_n` slot (evals/HISTORY.md, 2026-09-29): the LLM
    sees one source and `rerank_margin` compares a page with itself.
    `ranked` must already be sorted by cross-encoder score (ADR-0005), so
    the chunk kept is the best-scoring one and `ranked[0]`, which the floor
    decision reads, is never dropped.
    """

    seen: set[UUID] = set()
    best: list[RankedChunk] = []
    for chunk in ranked:
        if chunk.article_id not in seen:
            seen.add(chunk.article_id)
            best.append(chunk)
    return best


class RerankNode(BaseNode):
    Outcome = RerankOutcome

    def __call__(self, state: TriageState) -> StateUpdate:
        candidates: list[Candidate] = state.candidates
        if not candidates:
            return {"reranked": []}

        query = f"{state.ticket.subject_masked}\n{state.ticket.body_masked}"
        scores = reranker.score(query, [c.content for c in candidates])

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
        return {"reranked": _best_chunk_per_article(ranked)[: settings.rerank_top_n]}

    def decide(self, state: TriageState) -> RerankOutcome:
        reranked = state.reranked
        if not reranked or reranked[0].score < state.retrieval_floor:
            return RerankOutcome.EVIDENCE_BELOW_FLOOR
        return RerankOutcome.EVIDENCE_ABOVE_FLOOR


rerank = RerankNode()
