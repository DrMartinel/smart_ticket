"""Request bodies and filters of the notification endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import Field

from apps.notifications.utils.vocabulary import Channel, MessageState, RecipientKind

PersonChannel = Literal["in_app", "email"]
TemplateLanguage = Literal["vi", "en"]


class PreferenceIn(Schema):
    event: str = Field(max_length=64)
    channel: PersonChannel
    enabled: bool


class LanguageIn(Schema):
    language: TemplateLanguage


class MatrixChangeIn(Schema):
    event: str = Field(max_length=64)
    recipient_kind: RecipientKind
    channel: PersonChannel
    default_on: bool


class MatrixIn(Schema):
    changes: list[MatrixChangeIn] = Field(min_length=1, max_length=500)
    reason: str = Field("", max_length=500)


class DeliveryFilter(Schema):
    state: MessageState | None = None
    channel: Channel | None = None
    event: str | None = Field(None, max_length=64)
    since: datetime | None = None
    until: datetime | None = None


class RetryIn(Schema):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    all_failed: bool = False


class WebhookIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)
    events: list[str] = Field(min_length=1, max_length=50)
    secret: str = Field(min_length=16, max_length=200)


class WebhookPatch(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = Field(None, min_length=1, max_length=500)
    events: list[str] | None = Field(None, min_length=1, max_length=50)
    secret: str | None = Field(None, min_length=16, max_length=200)
    is_active: bool | None = None


class TemplateIn(Schema):
    subject_template: str = Field(min_length=1, max_length=255)
    body_template: str = Field(min_length=1, max_length=5000)
