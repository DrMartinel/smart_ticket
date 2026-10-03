"""Hybrid retrieval node — spec §6.2/§6.3: BM25 + vector + RRF fusion."""

from __future__ import annotations

from typing import Any

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode
from ai_engine.core.providers.embeddings import embedder
from ai_engine.graph.nodes.retrieve.bm25 import bm25_search
from ai_engine.graph.nodes.retrieve.fusion import reciprocal_rank_fusion
from ai_engine.graph.nodes.retrieve.vector import vector_search
from ai_engine.graph.state import TriageState


class HybridRetrieveNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        ticket = state.ticket
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

        bm25_hits = bm25_search(query)
        query_embedding = embedder.embed(query)
        vector_hits = vector_search(query_embedding)

        candidates = reciprocal_rank_fusion(bm25_hits, vector_hits)
        return {
            "candidates": candidates[: settings.fusion_candidate_limit],
            # Article level: an article with three matching chunks is one
            # answer, not three, so it must not push the next article to 4th.
            "bm25_article_ids": list(dict.fromkeys(h.article_id for h in bm25_hits)),
            "query_embedding": query_embedding,
        }


hybrid_retrieve = HybridRetrieveNode()
