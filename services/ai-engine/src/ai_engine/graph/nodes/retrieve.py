"""Hybrid retrieval node — spec §6.2/§6.3: BM25 + vector + RRF fusion."""

from __future__ import annotations

from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.node import BaseNode, StateUpdate
from ai_engine.core.providers.embeddings import embedder
from ai_engine.core.retrieval.bm25 import bm25_search
from ai_engine.core.retrieval.fusion import reciprocal_rank_fusion
from ai_engine.core.retrieval.vector import vector_search
from ai_engine.core.state import TriageState


class HybridRetrieveNode(BaseNode):
    def __call__(self, state: TriageState) -> StateUpdate:
        ticket = state.ticket
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

        with db.connect() as session:
            bm25_hits = bm25_search(session, query)
            query_embedding = embedder.embed(query)
            vector_hits = vector_search(session, query_embedding)

        candidates = reciprocal_rank_fusion(bm25_hits, vector_hits)
        return {
            "candidates": candidates[: settings.fusion_candidate_limit],
            "bm25_keyword_hit": len(bm25_hits) > 0,
        }


hybrid_retrieve = HybridRetrieveNode()
