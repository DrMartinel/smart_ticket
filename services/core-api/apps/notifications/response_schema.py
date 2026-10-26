"""Response shapes of the notification endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema
from pydantic import Field

from apps.notifications.models import Message, WebhookSubscription


class NotificationOut(Schema):
    id: uuid.UUID
    event: str
    subject: str
    body: str
    link: str
    ticket: str | None = Field(None)
    created_at: datetime
    read_at: datetime | None

    @staticmethod
    def resolve_ticket(obj: Message) -> str | None:
        return obj.ticket.public_id if obj.ticket else None


class InboxOut(Schema):
    unread: int
    poll_sec: int
    items: list[NotificationOut]


class PreferenceOut(Schema):
    event: str
    label: str
    channel: str
    enabled: bool
    default_on: bool
    mandatory: bool
    via: list[str]


class LanguageOut(Schema):
    language: str


class MatrixCellOut(Schema):
    event: str
    label: str
    owner: str
    active: bool
    recipient_kind: str
    channel: str
    default_on: bool
    mandatory: bool
    updated_by: str | None
    updated_at: datetime | None


class DeliveryOut(Schema):
    id: uuid.UUID
    event: str
    channel: str
    recipient: str
    ticket: str | None
    state: str
    attempts: int
    last_error: str
    created_at: datetime
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None

    @staticmethod
    def resolve_recipient(obj: Message) -> str:
        return obj.recipient_name()

    @staticmethod
    def resolve_ticket(obj: Message) -> str | None:
        return obj.ticket.public_id if obj.ticket else None


class RetryOut(Schema):
    requeued: int


class WebhookOut(Schema):
    id: uuid.UUID
    name: str
    url: str
    events: list[str]
    is_active: bool
    created_by: str
    created_at: datetime

    @staticmethod
    def resolve_created_by(obj: WebhookSubscription) -> str:
        return obj.created_by.username


class TemplateOut(Schema):
    event: str
    channel: str
    language: str
    subject_template: str
    body_template: str
    is_default: bool
    variables: dict[str, str]
