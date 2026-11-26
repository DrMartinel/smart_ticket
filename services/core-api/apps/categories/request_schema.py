"""Request bodies of the category endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from ninja import Schema
from pydantic import ConfigDict, Field

# A `ticket_categories` slug in another endpoint's body; the service checks it is active.
CategorySlug = Annotated[str, Field(min_length=1, max_length=20)]


class CategoryPatch(Schema):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    sort_order: int | None = Field(None, ge=0, le=32767)
    description: str | None = Field(None, min_length=1, max_length=2000)
    is_routable: bool | None = None
    # Sent as null, it clears the category's workflow; left out, it keeps it.
    workflow_id: uuid.UUID | None = None
    reason: str = Field("", max_length=500)
