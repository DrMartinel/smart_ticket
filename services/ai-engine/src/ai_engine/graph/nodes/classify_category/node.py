"""
Category node (ADR-0017), and where refuse-before-LLM is decided (spec
§6.2/§6.3). Jev chooses the ticket's category on every path past the
injection guard, so it runs before the floor splits the graph: a ticket the
KB can't answer still gets a category, from its own text.

Whether Jev sees a page and whether the LLM runs are the same question,
asked in `__call__` and `decide` alike: did Jev choose a passage, and is its
top chunk at or above the floor? If not, the graph goes straight to `emit_signals`, so a model with
no real source material is never asked to fabricate one. The floor is
compared only with Jev's `rerank_score` (`final_score`), never the
cross-encoder's or fusion's RRF score (ADR-0005).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.candidate_pool.links import article_titles
from ai_engine.graph.nodes.classify_category.classifier import classifier
from ai_engine.graph.state import TriageState


class ClassifyCategoryOutcome(StrEnum):
    EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
    EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"


class ClassifyCategoryNode(BaseNode):
    """Below the floor goes to `emit_signals` (refuse-before-LLM); above it,
    to the LLM. A Jev failure raises: the LLM's category is not a fallback,
    a silent switch of classifier would hide the outage (ADR-0017)."""

    Outcome = ClassifyCategoryOutcome

    def __call__(self, state: TriageState) -> dict[str, Any]:
        title = None
        if self._evidence_above_floor(state):
            top = state.reranked[0]
            title = article_titles([top.article_id]).get(top.article_id)
        choice = classifier.classify(state.ticket.subject_masked, state.ticket.body_masked, title)
        return {"category_choice": choice.category, "category_confidence": choice.confidence}

    def decide(self, state: TriageState) -> ClassifyCategoryOutcome:
        if self._evidence_above_floor(state):
            return ClassifyCategoryOutcome.EVIDENCE_ABOVE_FLOOR
        return ClassifyCategoryOutcome.EVIDENCE_BELOW_FLOOR

    @staticmethod
    def _evidence_above_floor(state: TriageState) -> bool:
        """Jev chose a passage, and its top chunk is at or above the floor."""
        return (
            bool(state.reranked)
            and state.rerank_choice is not None
            and state.reranked[0].final_score() >= state.retrieval_floor
        )


classify_category = ClassifyCategoryNode()
