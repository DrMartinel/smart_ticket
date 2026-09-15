"""Hybrid retrieval node — spec §6.2/§6.3: BM25 + vector + RRF fusion."""

from __future__ import annotations

from ai_engine.core.budget import BudgetedNode
from ai_engine.core.config import settings
from ai_engine.core.providers.base import ConnectionSource, Embedder
from ai_engine.core.retrieval.bm25 import bm25_search
from ai_engine.core.retrieval.fusion import reciprocal_rank_fusion
from ai_engine.core.retrieval.vector import vector_search
from ai_engine.core.state import TriageState


class HybridRetrieveNode(BudgetedNode):
    def __init__(self, *, db: ConnectionSource, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder

    def __call__(self, state: TriageState) -> dict:
        ticket = state.ticket
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

        with self._db.connect() as conn:
            bm25_hits = bm25_search(conn, query)
            query_embedding = self._embedder.embed(query)
            vector_hits = vector_search(conn, query_embedding)

        candidates = reciprocal_rank_fusion(bm25_hits, vector_hits)
        return {
            "candidates": candidates[: settings.fusion_candidate_limit],
            "bm25_keyword_hit": len(bm25_hits) > 0,
        }
