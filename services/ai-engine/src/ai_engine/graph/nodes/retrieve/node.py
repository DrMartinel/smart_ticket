"""Retrieval node — spec §6.2/§6.3: three ranked lists fused with RRF, then
the first `fusion_candidate_limit` pages, one chunk each:

- vector search on the ticket;
- BM25 on the drafted answer (ADR-0021), written in the KB's vocabulary;
- vector search on the drafted answer.

No BM25 on the ticket (ADR-0020)."""

from __future__ import annotations

import uuid
from typing import Any

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode
from ai_engine.core.providers.embeddings import embedder
from ai_engine.graph.nodes.retrieve.bm25 import bm25_search
from ai_engine.graph.nodes.retrieve.fusion import reciprocal_rank_fusion
from ai_engine.graph.nodes.retrieve.vector import vector_search
from ai_engine.graph.state import Candidate, TriageState


class HybridRetrieveNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        ticket = state.ticket
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

        if not state.draft_text or not state.draft_embedding:
            raise ValueError("retrieval needs the drafted answer (DraftAnswerNode)")

        query_embedding = embedder.embed(query)
        candidates = reciprocal_rank_fusion(
            [
                vector_search(query_embedding),
                bm25_search(state.draft_text),
                vector_search(state.draft_embedding),
            ]
        )
        return {
            "candidates": self._one_per_page(candidates)[: settings.fusion_candidate_limit],
            "query_embedding": query_embedding,
        }

    @staticmethod
    def _one_per_page(candidates: list[Candidate]) -> list[Candidate]:
        """Keeps each page's best-fused chunk, in fused order."""

        seen: set[uuid.UUID] = set()
        out: list[Candidate] = []
        for c in candidates:
            if c.article_id not in seen:
                seen.add(c.article_id)
                out.append(c)
        return out


hybrid_retrieve = HybridRetrieveNode()
