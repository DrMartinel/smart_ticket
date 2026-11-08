"""Request bodies for the agent's routes (F15 §h.2)."""

from __future__ import annotations

import uuid

from ninja import Schema
from pydantic import ConfigDict, Field

from apps.agent.models import AgentSurface


class AgentTurnIn(Schema):
    """One message to the agent."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: str = Field(min_length=1, max_length=4_000)
    surface: AgentSurface
    # The conversation the message continues; none starts a new one.
    conversation_id: uuid.UUID | None = None
