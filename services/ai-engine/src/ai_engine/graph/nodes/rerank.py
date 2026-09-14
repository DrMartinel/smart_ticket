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

from dataclasses import dataclass

from ai_engine.graph.budget import check_budget
from ai_engine.graph.state import TriageState
from ai_engine.providers.protocols import Reranker
from ai_engine.retrieval.fusion import Candidate


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float  # cross-encoder score — the ONLY score thresholds compare against


class RerankNode:
    """Read-only after __init__; one instance is shared across FastAPI's
    threadpool."""

    def __init__(self, *, reranker: Reranker, top_n: int) -> None:
        self._reranker = reranker
        self._top_n = top_n

    def __call__(self, state: TriageState) -> dict:
        degraded = check_budget(state)
        if degraded:
            return {"reranked": [], "degraded_reason": degraded}

        candidates: list[Candidate] = state.get("candidates", [])
        if not candidates:
            # No degraded_reason here on purpose: "the KB had nothing to
            # rerank" is an ordinary refuse-before-LLM, and core-api gives it
            # a different reason code from an infrastructure degrade.
            return {"reranked": []}

        query = f"{state['ticket'].subject_masked}\n{state['ticket'].body_masked}"
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
        # Sorted by the CROSS-ENCODER score, discarding the RRF order the
        # candidates arrived in — ADR-0005. `reranked[0].score` is what
        # build.py compares against `retrieval_floor`.
        ranked.sort(key=lambda r: r.score, reverse=True)
        return {"reranked": ranked[: self._top_n]}
