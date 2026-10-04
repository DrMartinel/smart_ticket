"""
Terminal node — spec §6.2 `emit_signals`. Assembles the `TrustSignals` that
core-api's trust scorer and router act on; every path ends here. It NEVER
writes to a database, only reads best-effort for the log-only `policy` fields.
"""

from __future__ import annotations

from typing import Any

from ai_engine.schemas import (
    AutoReplyProposal,
    GenerationSignals,
    PIILevel,
    PolicySignals,
    RetrievalSignals,
    TrustSignals,
)
from ai_engine.graph.state import TriageState

from sqlalchemy import select

from ai_engine.core.db.tables import KbArticle
from ai_engine.graph.build.node import BaseNode
from ai_engine.core.db.client import db


class EmitSignalsNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        reranked = state.reranked
        proposal = state.proposal

        final = [r.final_score() for r in reranked]
        rerank_top1 = final[0] if final else 0.0
        rerank_top2 = final[1] if len(final) > 1 else 0.0
        rerank_margin = max(0.0, rerank_top1 - rerank_top2) if len(reranked) > 1 else 0.0
        docs_above_floor = sum(1 for s in final if s >= state.retrieval_floor)

        bm25_rank_of_top1: int | None = None
        if reranked and reranked[0].article_id in state.bm25_article_ids:
            bm25_rank_of_top1 = state.bm25_article_ids.index(reranked[0].article_id) + 1

        root = proposal.root if proposal is not None else None
        kb_slug = root.kb_slug if isinstance(root, AutoReplyProposal) else None
        self_confidence = getattr(root, "self_confidence", None)

        kb_auto_reply_allowed, kb_risk_tier = (False, "high")
        if kb_slug:
            try:
                statement = select(KbArticle.auto_reply_allowed, KbArticle.risk_tier).where(
                    KbArticle.slug == kb_slug, KbArticle.is_active.is_(True)
                )
                row = db.first(statement)
                if row:
                    kb_auto_reply_allowed, kb_risk_tier = bool(row[0]), row[1]
            except Exception:  # noqa: BLE001 — best-effort only, never fail the graph over this
                pass

        signals = TrustSignals(
            retrieval=RetrievalSignals(
                rerank_top1=rerank_top1,
                rerank_margin=rerank_margin,
                bm25_rank_of_top1=bm25_rank_of_top1,
                docs_above_floor=docs_above_floor,
            ),
            generation=GenerationSignals(
                schema_valid=state.schema_valid,
                quote_match_ratio=state.quote_match_ratio,
                quote_source_in_topk=state.quote_source_in_topk,
                negation_consistent=state.negation_consistent,
                category_consistent=state.category_consistent,
                quote_applicable=state.quote_applicable,
                clarify_options_in_topk=state.clarify_options_in_topk,
            ),
            policy=PolicySignals(
                kb_auto_reply_allowed=kb_auto_reply_allowed,
                kb_risk_tier=kb_risk_tier,
                pii_level=state.ticket.pii_level or PIILevel.ROUTINE,
                injection_detected=state.injection_detected,
                mass_incident=False,
            ),
            llm_self_confidence=self_confidence,
        )
        return {"signals": signals}


emit_signals = EmitSignalsNode()
