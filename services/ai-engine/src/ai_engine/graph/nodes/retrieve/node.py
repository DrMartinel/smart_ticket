"""Retrieval node — spec §6.2/§6.3: vector search on the ticket, through RRF,
then the first `fusion_candidate_limit` pages, one chunk each.

No BM25 on the ticket since 2026-10-11 (ADR-0020): a ticket describes
symptoms in the requester's words, and keyword matching on them added more
wrong pages than right ones (evals/HISTORY.md). Fusion takes a list of ranked
lists, so other lists join it without changing this contract."""

from __future__ import annotations

import uuid
from typing import Any

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode
from ai_engine.core.providers.embeddings import embedder
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

        query_embedding = embedder.embed(query)
        candidates = reciprocal_rank_fusion([vector_search(query_embedding)])
        return {
            "candidates": _one_per_page(candidates)[: settings.fusion_candidate_limit],
            "query_embedding": query_embedding,
        }


hybrid_retrieve = HybridRetrieveNode()
