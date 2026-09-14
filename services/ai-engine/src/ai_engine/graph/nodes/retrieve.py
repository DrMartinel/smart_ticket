"""Hybrid retrieval node — spec §6.2/§6.3: BM25 + vector + RRF fusion."""

from __future__ import annotations

from ai_engine.graph.base import BaseNode
from ai_engine.graph.budget import check_budget
from ai_engine.graph.state import TriageState
from ai_engine.providers.protocols import ConnectionSource, Embedder
from ai_engine.retrieval.bm25 import bm25_search
from ai_engine.retrieval.fusion import reciprocal_rank_fusion
from ai_engine.retrieval.vector import vector_search


class HybridRetrieveNode(BaseNode):
    def __init__(
        self,
        *,
        db: ConnectionSource,
        embedder: Embedder,
        bm25_top_k: int,
        vector_top_k: int,
        rrf_k: int,
        candidate_limit: int,
    ) -> None:
        self._db = db
        self._embedder = embedder
        # Keyword-only and undefaulted: these are three same-typed ints, and
        # a positional swap would be silent forever.
        self._bm25_top_k = bm25_top_k
        self._vector_top_k = vector_top_k
        self._rrf_k = rrf_k
        self._candidate_limit = candidate_limit

    def __call__(self, state: TriageState) -> dict:
        degraded = check_budget(state)
        if degraded:
            # Return BEFORE the embedding round-trip: a ticket that has
            # already blown its budget must not buy one more.
            return {"candidates": [], "degraded_reason": degraded}

        ticket = state["ticket"]
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

        with self._db.connect() as conn:
            bm25_hits = bm25_search(conn, query, self._bm25_top_k)
            query_embedding = self._embedder.embed(query)
            vector_hits = vector_search(conn, query_embedding, self._vector_top_k)

        # This list is ORDERED by the RRF score and then SLICED — never
        # thresholded. ADR-0005: RRF is rank-derived, so its magnitude means
        # nothing; the only score a floor is ever compared against is the
        # cross-encoder's, one node downstream.
        candidates = reciprocal_rank_fusion(bm25_hits, vector_hits, k=self._rrf_k)
        return {
            "candidates": candidates[: self._candidate_limit],
            "bm25_keyword_hit": len(bm25_hits) > 0,
        }
