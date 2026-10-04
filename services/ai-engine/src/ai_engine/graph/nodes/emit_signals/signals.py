"""
What ai-engine found about one ticket, assembled by EmitSignalsNode: no
Branch, ReasonCode or trust score, since ai-engine decides and scores
nothing (ADR-0001, ADR-0003). Part of `AIRunResponse` (schemas.py); core-api
adds its own policy to make the `TrustSignals` its router reads.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_engine.graph.ticket import TicketCategory


class RetrievalSignals(BaseModel):
    rerank_top1: float = Field(ge=0, le=1)
    rerank_margin: float = Field(ge=0, le=1)
    bm25_rank_of_top1: int | None = Field(default=None, ge=1)
    docs_above_floor: int = Field(ge=0)


class GenerationSignals(BaseModel):
    quote_match_ratio: float = Field(ge=0, le=1)
    quote_source_in_topk: bool
    negation_consistent: bool
    quote_applicable: bool = True
    clarify_options_in_topk: bool = False


class ClassificationSignals(BaseModel):
    """Jev's answer to the category question (ADR-0017). The router takes
    `category_choice` as the ticket's category; the LLM proposes none
    (propose.v8). No choice (None, 0.0) means Jev wasn't
    asked: a refusal at the injection guard, or a degraded run. The router
    sends that to a human wherever it needs a category.

    No defaults, here or on `EngineSignals.classification`: no signals were
    stored before ADR-0017, so every producer must say what Jev answered."""

    category_choice: TicketCategory | None
    category_confidence: float = Field(ge=0, le=1)


class EngineSignals(BaseModel):
    """What ai-engine found about one ticket. core-api adds what it knows
    itself (the PII level, its own KB read, mass incidents) to build the
    `TrustSignals` its router and trust scorer read."""

    retrieval: RetrievalSignals
    generation: GenerationSignals
    classification: ClassificationSignals
    injection_detected: bool
    llm_self_confidence: float | None = None
