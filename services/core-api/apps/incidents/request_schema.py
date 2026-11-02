"""What an incident manager sends (F7 §h)."""

from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field

from apps.tickets.models import IncidentStage, IncidentStatus


class IncidentFilter(Schema):
    status: IncidentStatus | None = None


class ConfirmIn(Schema):
    title: str = Field(min_length=3, max_length=255)
    category: str | None = None
    service: str = Field(default="", max_length=120)


class ReasonIn(Schema):
    reason: str = Field(max_length=2000)


class BroadcastIn(Schema):
    stage: IncidentStage = IncidentStage.INVESTIGATING
    body_vi: str = Field(max_length=4000)
    body_en: str = Field(default="", max_length=4000)
    eta: datetime | None = None
    eta_unknown: bool = False


class DeclareIn(ConfirmIn):
    ticket_ids: list[str] = Field(default_factory=list, max_length=500)
    broadcast: BroadcastIn | None = None


class ResolveIn(Schema):
    resolution_note: str = Field(max_length=4000)
    close_all: bool = True


class LinksIn(Schema):
    ticket_ids: list[str] = Field(min_length=1, max_length=500)
