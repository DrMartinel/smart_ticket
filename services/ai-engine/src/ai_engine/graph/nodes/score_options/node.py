"""
Clarify options node (ADR-0023, ADR-0026). For a clarify proposal whose
options passed the validator, Jev scores each chunk of `reranked` with a
yes/no question; core-api offers the pages within
`clarification.option_margin` of the best of these scores. Every other
proposal is not scored.
"""

from __future__ import annotations

from typing import Any

from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.candidate_pool.links import article_titles
from ai_engine.graph.nodes.infer.proposals import ClarificationProposal
from ai_engine.graph.nodes.rerank.reranker import Passage
from ai_engine.graph.nodes.score_options.scorer import option_scorer
from ai_engine.graph.state import TriageState


class ScoreOptionsNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        proposal = state.proposal.root if state.proposal else None
        if not isinstance(proposal, ClarificationProposal) or not state.clarify_options_in_topk:
            return {"option_scores": []}

        chunks = state.reranked
        titles = article_titles(list({c.article_id for c in chunks}))
        scores = option_scorer.score(
            state.ticket.subject_masked,
            state.ticket.body_masked,
            [Passage(titles.get(c.article_id, ""), c.content) for c in chunks],
        )
        if len(scores) != len(chunks):
            raise ValueError(f"Jev returned {len(scores)} option scores for {len(chunks)}")
        return {"option_scores": scores}


score_options = ScoreOptionsNode()
