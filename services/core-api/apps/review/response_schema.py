"""
Response shapes for the HITL review endpoints.
"""

from __future__ import annotations

import uuid

from datetime import datetime
from typing import Any

from ninja import Field, Schema

from infrastructure.dtos import TrustSignals

from apps.review.models import ReviewItem
from apps.tickets.models import RoutingDecision
from apps.tickets.utils.trust_scorer import score as compute_trust


class DecisionOut(Schema):
    id: uuid.UUID
    action_taken: str


class RoutingDecisionOut(Schema):
    branch: str
    reason_code: str
    reason_detail: str
    gate_failed: str | None
    shadow_mode: bool


class ReviewItemOut(Schema):
    id: uuid.UUID
    ticket_public_id: str = Field(alias="ticket.public_id")
    subject_masked: str = Field(alias="ticket.subject_masked")
    body_masked: str = Field(alias="ticket.body_masked")
    queue: str
    priority: int
    state: str
    claimed_by: uuid.UUID | None = Field(alias="claimed_by_id")
    created_at: datetime
    ai_run_id: uuid.UUID | None
    trust_signals: dict[str, Any] | None
    trust_score: float | None
    trust_contributions: dict[str, float] | None
    proposed_draft: dict[str, Any] | None
    routing_decisions: list[RoutingDecisionOut]

    @staticmethod
    def resolve_trust_signals(item: ReviewItem) -> dict[str, Any] | None:
        return item.ai_run.trust_signals if item.ai_run is not None else None

    @staticmethod
    def resolve_trust_score(item: ReviewItem) -> float | None:
        ai_run = item.ai_run
        if ai_run is None or ai_run.trust_score is None:
            return None
        return float(ai_run.trust_score)

    @staticmethod
    def resolve_trust_contributions(item: ReviewItem) -> dict[str, float] | None:
        # `contributions` is deliberately NOT stored on ai_runs — it's
        # deterministically recomputable from trust_signals + the active
        # model file, so recomputing at read time avoids duplicating data
        # that could drift from the model that actually produced it. This is
        # what lets TrustSignalsPanel answer "why 0.62" on the UI, not just
        # display a bare number (spec §4.4 comment on TrustScore.contributions).
        ai_run = item.ai_run
        if ai_run is None or not ai_run.trust_signals:
            return None
        return compute_trust(TrustSignals(**ai_run.trust_signals)).contributions

    @staticmethod
    def resolve_proposed_draft(item: ReviewItem) -> dict[str, Any] | None:
        return item.ai_run.proposed_draft if item.ai_run is not None else None

    @staticmethod
    def resolve_routing_decisions(item: ReviewItem) -> list[RoutingDecision]:
        """Only the latest decision, in a one-item list."""
        return list(item.ticket.routing_decisions.order_by("-decided_at")[:1])
