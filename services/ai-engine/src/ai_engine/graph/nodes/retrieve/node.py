"""Retrieval node — spec §6.2/§6.3: three ranked lists fused with RRF, then
the first `fusion_candidate_limit` pages, one chunk each:

- vector search on the ticket;
- BM25 on the drafted answer (ADR-0021), written in the KB's vocabulary;
- vector search on the drafted answer.

No BM25 on the ticket (ADR-0020): keyword matching on a ticket's symptom
wording added more wrong pages than right ones. The draft only chooses
candidates; nothing downstream scores against it."""

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


def _one_per_page(candidates: list[Candidate]) -> list[Candidate]:
    """Each page's best-fused chunk, in fused order. The candidate limit
    counts pages: several chunks of one page would otherwise fill the slots
    another page needed (2026-10-11: 7 distinct pages in 10 chunks at the
    median, evals/HISTORY.md)."""

    seen: set[uuid.UUID] = set()
    out: list[Candidate] = []
    for c in candidates:
        if c.article_id not in seen:
            seen.add(c.article_id)
            out.append(c)
    return out


class HybridRetrieveNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        ticket = state.ticket
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()

        if not state.draft_text or not state.draft_embedding:
            # A wiring bug, never a ticket without a draft: retrieving on the
            # ticket alone would run the weaker pipeline with nothing saying so.
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
            "candidates": _one_per_page(candidates)[: settings.fusion_candidate_limit],
            "query_embedding": query_embedding,
        }


hybrid_retrieve = HybridRetrieveNode()
