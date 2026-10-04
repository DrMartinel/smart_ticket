"""
What InferNode's LLM may propose: one of five shapes, told apart by
`proposed_intent`. `LLMProposalEnvelope` is the union as a model, so it can
parse a reply and give vLLM its JSON Schema to decode against. Part of
`AIRunResponse` (schemas.py). LLM-authored fields are prefixed `proposed_` /
`self_`: suggestions, not decisions (ADR-0001, ADR-0003).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel


class AutoReplyProposal(BaseModel):
    proposed_intent: Literal["auto_reply"]
    kb_slug: str
    verbatim_quote: str = Field(min_length=10, max_length=500)
    answer_draft: str
    self_confidence: float = Field(ge=0, le=100)  # log-only, never routes (ADR-0003)


class RouteProposal(BaseModel):
    proposed_intent: Literal["route_to_team"]
    rationale: str
    self_confidence: float = Field(ge=0, le=100)


class RunbookProposal(BaseModel):
    proposed_intent: Literal["runbook"]
    runbook_id: str
    draft_payload: dict[str, Any]  # never executed directly (ADR-0006)
    self_confidence: float = Field(ge=0, le=100)


class ClarificationProposal(BaseModel):
    """Several shown KB pages answer different readings of the ticket, and it
    doesn't say which (ADR-0016). A question for the requester, never an
    answer: core-api's router decides whether it is asked."""

    proposed_intent: Literal["clarify"]
    proposed_question: str = Field(min_length=10, max_length=300)
    proposed_options: list[str] = Field(min_length=2)
    rationale: str


class InsufficientContext(BaseModel):
    proposed_intent: Literal["insufficient_context"]
    missing_information: str


LLMProposal = Annotated[
    AutoReplyProposal
    | RouteProposal
    | RunbookProposal
    | ClarificationProposal
    | InsufficientContext,
    Field(discriminator="proposed_intent"),
]


class LLMProposalEnvelope(RootModel[LLMProposal]):
    """The LLM's output is the union itself; `.root` is the narrowed variant."""

    root: LLMProposal
