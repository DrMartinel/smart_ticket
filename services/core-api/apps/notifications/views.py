"""Notification endpoints: a user's own inbox and preferences, and the admin's matrix, deliveries,
webhooks and templates (F4 §h)."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.conf import settings
from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.pagination import LimitOffsetPagination, paginate

from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.notifications.models import Message, WebhookSubscription
from apps.notifications.request_schema import (
    DeliveryFilter,
    LanguageIn,
    MatrixIn,
    PersonChannel,
    PreferenceIn,
    RetryIn,
    TemplateIn,
    TemplateLanguage,
    WebhookIn,
    WebhookPatch,
)
from apps.notifications.response_schema import (
    DeliveryOut,
    InboxOut,
    LanguageOut,
    MatrixCellOut,
    PreferenceOut,
    RetryOut,
    TemplateOut,
    WebhookOut,
)
from apps.notifications.utils.configuration import (
    InboxPage,
    MatrixCellView,
    PreferenceView,
    TemplateView,
    config,
    inbox,
)
from apps.notifications.utils.dispatcher import dispatcher

router = Router(tags=["notifications"])


# ── a user's own ──


@router.get("", auth=SessionAuth(), response=InboxOut)
@require(Permission.SELF_NOTIFICATIONS, agent=AgentTier.NONE)
def notifications(
    request: AuthedRequest,
    unread: bool = False,
    limit: int = Query(20, ge=1, le=100),
    before: datetime | None = None,
) -> InboxPage:
    return inbox.page(
        request.auth.user,
        unread=unread,
        limit=limit,
        before=before,
        poll_sec=settings.NOTIFICATION_POLL_SEC,
    )


@router.post("/read-all", auth=SessionAuth(), response={204: None})
@require(Permission.SELF_NOTIFICATIONS, agent=AgentTier.NONE)
def read_all(request: AuthedRequest) -> Status:
    inbox.read_all(request.auth.user)
    return Status(204, None)


@router.get("/preferences", auth=SessionAuth(), response=list[PreferenceOut])
@require(Permission.SELF_NOTIFICATIONS, agent=AgentTier.NONE)
def preferences(request: AuthedRequest) -> list[PreferenceView]:
    return config.preferences(request.auth.user)


@router.put("/preferences", auth=SessionAuth(), response=list[PreferenceOut])
@require(Permission.SELF_NOTIFICATIONS, agent=AgentTier.NONE)
def save_preferences(request: AuthedRequest, payload: list[PreferenceIn]) -> list[PreferenceView]:
    return config.save_preferences(request.auth.user, [p.dict() for p in payload])


@router.put("/language", auth=SessionAuth(), response=LanguageOut)
@require(Permission.SELF_NOTIFICATIONS, agent=AgentTier.NONE)
def set_language(request: AuthedRequest, payload: LanguageIn) -> dict[str, str]:
    return {"language": config.set_language(request.auth.user, payload.language)}


# ── the matrix ──


@router.get("/matrix", auth=SessionAuth(), response=list[MatrixCellOut])
@require(Permission.NOTIFICATIONS_MATRIX_READ, agent=AgentTier.NONE)
def matrix(request: AuthedRequest) -> list[MatrixCellView]:
    return config.matrix()


@router.put("/matrix", auth=SessionAuth(), response=list[MatrixCellOut])
@require(Permission.NOTIFICATIONS_MATRIX_MANAGE, agent=AgentTier.NONE)
def save_matrix(request: AuthedRequest, payload: MatrixIn) -> list[MatrixCellView]:
    return config.save_matrix(
        request.auth.user, [c.model_dump(mode="json") for c in payload.changes], payload.reason
    )


# ── deliveries ──


@router.get("/deliveries", auth=SessionAuth(), response=list[DeliveryOut])
@paginate(LimitOffsetPagination)
@require(Permission.NOTIFICATIONS_DELIVERIES_MANAGE, agent=AgentTier.NONE)
def deliveries(request: AuthedRequest, filters: Query[DeliveryFilter]) -> QuerySet[Message]:
    return Message.objects.deliveries().matching(**filters.dict())


@router.post("/deliveries/retry", auth=SessionAuth(), response=RetryOut)
@require(Permission.NOTIFICATIONS_DELIVERIES_MANAGE, agent=AgentTier.NONE)
def retry(request: AuthedRequest, payload: RetryIn) -> dict[str, int]:
    rows = (
        Message.objects.all() if payload.all_failed else Message.objects.filter(pk__in=payload.ids)
    )
    return {"requeued": dispatcher.retry(rows, request.auth.user, all_failed=payload.all_failed)}


# ── webhooks ──


@router.get("/webhooks", auth=SessionAuth(), response=list[WebhookOut])
@require(Permission.NOTIFICATIONS_WEBHOOKS_MANAGE, agent=AgentTier.NONE)
def webhooks(request: AuthedRequest) -> QuerySet[WebhookSubscription]:
    return WebhookSubscription.objects.select_related("created_by")


@router.post("/webhooks", auth=SessionAuth(), response={201: WebhookOut})
@require(Permission.NOTIFICATIONS_WEBHOOKS_MANAGE, agent=AgentTier.NONE)
def subscribe(request: AuthedRequest, payload: WebhookIn) -> Status:
    return Status(201, config.subscribe(request.auth.user, payload.dict()))


@router.patch("/webhooks/{subscription_id}", auth=SessionAuth(), response=WebhookOut)
@require(Permission.NOTIFICATIONS_WEBHOOKS_MANAGE, agent=AgentTier.NONE)
def update_webhook(
    request: AuthedRequest, subscription_id: uuid.UUID, payload: WebhookPatch
) -> WebhookSubscription:
    return config.update_subscription(
        request.auth.user, subscription_id, payload.dict(exclude_unset=True)
    )


@router.delete("/webhooks/{subscription_id}", auth=SessionAuth(), response={204: None})
@require(Permission.NOTIFICATIONS_WEBHOOKS_MANAGE, agent=AgentTier.NONE)
def unsubscribe(request: AuthedRequest, subscription_id: uuid.UUID) -> Status:
    config.unsubscribe(request.auth.user, subscription_id)
    return Status(204, None)


# ── templates ──


@router.get("/templates/{event}/{channel}/{language}", auth=SessionAuth(), response=TemplateOut)
@require(Permission.NOTIFICATIONS_TEMPLATES_MANAGE, agent=AgentTier.NONE)
def template(
    request: AuthedRequest, event: str, channel: PersonChannel, language: TemplateLanguage
) -> TemplateView:
    return config.template(event, channel, language)


@router.put("/templates/{event}/{channel}/{language}", auth=SessionAuth(), response=TemplateOut)
@require(Permission.NOTIFICATIONS_TEMPLATES_MANAGE, agent=AgentTier.NONE)
def save_template(
    request: AuthedRequest,
    event: str,
    channel: PersonChannel,
    language: TemplateLanguage,
    payload: TemplateIn,
) -> TemplateView:
    return config.save_template(request.auth.user, event, channel, language, payload.dict())


# ── one notice; after the fixed paths ──


@router.post("/{notification_id}/read", auth=SessionAuth(), response={204: None})
@require(Permission.SELF_NOTIFICATIONS, agent=AgentTier.NONE)
def read(request: AuthedRequest, notification_id: uuid.UUID) -> Status:
    inbox.read(request.auth.user, notification_id)
    return Status(204, None)
