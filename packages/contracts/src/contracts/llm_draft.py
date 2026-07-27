"""
LLM draft — discriminated union. Spec §4.3.

Two design points:

- Every LLM-authored field carries a `proposed_` prefix. When the router
  reads `draft.proposed_category`, the name itself is the reminder that
  this is a suggestion, not an approved decision. Only `router.py` may
  write the non-prefixed `category` column on `tickets`.
- `InsufficientContext` is a *legitimate* variant, not an error path. The
  model needs a lawful way to say "I don't know" — otherwise it fabricates.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel

from contracts.enums import TicketCategory


class AutoReplyProposal(BaseModel):
    proposed_intent: Literal["auto_reply"]
    kb_slug: str
    verbatim_quote: str = Field(min_length=10, max_length=500)
    answer_draft: str
    self_confidence: float = Field(ge=0, le=100)  # log-only, never used to route


class RouteProposal(BaseModel):
    proposed_intent: Literal["route_to_team"]
    proposed_category: TicketCategory
    proposed_subcategory: str | None = None
    rationale: str
    self_confidence: float = Field(ge=0, le=100)


class RunbookProposal(BaseModel):
    proposed_intent: Literal["runbook"]
    runbook_id: str
    draft_payload: dict[str, Any]  # NEVER executed directly
    proposed_category: TicketCategory
    self_confidence: float = Field(ge=0, le=100)


class InsufficientContext(BaseModel):
    proposed_intent: Literal["insufficient_context"]
    missing_information: str


LLMProposal = Annotated[
    AutoReplyProposal | RouteProposal | RunbookProposal | InsufficientContext,
    Field(discriminator="proposed_intent"),
]


class LLMProposalEnvelope(RootModel[LLMProposal]):
    """
    RootModel because the LLM's output *is* the union, not a wrapper around
    it. `.root` gives back the narrowed instance. The discriminator lets
    Pydantic dispatch by lookup table instead of trying each member in
    turn — faster, and error messages point at the right variant.
    """

    root: LLMProposal
