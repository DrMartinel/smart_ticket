"""
Terminal node — spec §6.2 `emit_signals`. Assembles the `EngineSignals` that
core-api turns into its trust signals; every path ends here, so it must not
raise. It reads nothing outside the state: what ai-engine did not find (the
PII level, the KB page's authority, mass incidents) core-api adds itself.
"""

from __future__ import annotations

from typing import Any

from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.state import TriageState
from ai_engine.graph.nodes.emit_signals.signals import (
    ClassificationSignals,
    EngineSignals,
    GenerationSignals,
    RetrievalSignals,
)


class EmitSignalsNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        reranked = state.reranked
        final = [r.final_score() for r in reranked]
        rerank_top1 = final[0] if final else 0.0
        rerank_margin = max(0.0, final[0] - final[1]) if len(final) > 1 else 0.0

        proposal = state.proposal.root if state.proposal is not None else None
        signals = EngineSignals(
            retrieval=RetrievalSignals(
                rerank_top1=rerank_top1,
                rerank_margin=rerank_margin,
                docs_above_floor=sum(1 for s in final if s >= state.retrieval_floor),
                pool_size=len(state.pool),
                rerank_confidence=state.rerank_confidence,
                rerank_chose_none=bool(reranked) and state.rerank_choice is None,
                rerank_total=state.rerank_total,
            ),
            generation=GenerationSignals(
                quote_applicable=state.quote_applicable,
                quote_match_ratio=state.quote_match_ratio,
                quote_source_in_topk=state.quote_source_in_topk,
                negation_consistent=state.negation_consistent,
                clarify_options_in_topk=state.clarify_options_in_topk,
                cited_is_rerank_choice=state.cited_is_rerank_choice,
            ),
            classification=ClassificationSignals(
                category_choice=state.category_choice,
                category_confidence=state.category_confidence,
            ),
            injection_detected=state.injection_detected,
            llm_self_confidence=getattr(proposal, "self_confidence", None),
        )
        return {"signals": signals}


emit_signals = EmitSignalsNode()
