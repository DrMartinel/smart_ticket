"""Test helpers for triage: ai-engine's signals for a ticket it found nothing for."""

from __future__ import annotations

from infrastructure.dtos import (
    ClassificationSignals,
    EngineSignals,
    GenerationSignals,
    RetrievalSignals,
)


def nothing_found(*, injection_detected: bool = False) -> EngineSignals:
    """ai-engine's signals with every check failed and nothing found."""
    return EngineSignals(
        retrieval=RetrievalSignals(rerank_top1=0.0, rerank_margin=0.0, docs_above_floor=0),
        generation=GenerationSignals(
            quote_match_ratio=0.0,
            quote_source_in_topk=False,
            negation_consistent=False,
        ),
        classification=ClassificationSignals(category_choice=None, category_confidence=0.0),
        injection_detected=injection_detected,
    )
