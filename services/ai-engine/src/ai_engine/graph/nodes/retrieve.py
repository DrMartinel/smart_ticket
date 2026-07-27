"""Hybrid retrieval node — spec §6.2/§6.3: BM25 + vector + RRF fusion."""

from __future__ import annotations

from ai_engine.config import settings
from ai_engine.db import get_connection
from ai_engine.graph.budget import check_budget
from ai_engine.graph.state import TriageState
from ai_engine.providers.embeddings import embed_text
from ai_engine.retrieval.bm25 import bm25_search
from ai_engine.retrieval.fusion import reciprocal_rank_fusion
from ai_engine.retrieval.vector import vector_search


def hybrid_retrieve(state: TriageState) -> dict:
    degraded = check_budget(state)
    if degraded:
        return {"candidates": [], "degraded_reason": degraded}

    ticket = state["ticket"]
    query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

    with get_connection() as conn:
        bm25_hits = bm25_search(conn, query, settings.bm25_top_k)
        query_embedding = embed_text(query)
        vector_hits = vector_search(conn, query_embedding, settings.vector_top_k)

    candidates = reciprocal_rank_fusion(bm25_hits, vector_hits, k=settings.rrf_k)
    return {"candidates": candidates[:10], "bm25_keyword_hit": len(bm25_hits) > 0}
