"""Who is told what: preferences, the matrix, templates and webhook subscriptions, each change audited."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Language, User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.notifications.models import MatrixRule, Message, Preference, Template, WebhookSubscription
from apps.notifications.utils.notifier import notifier
from apps.notifications.utils.secrets import webhook_secrets
from apps.notifications.utils.templates import (
    TEMPLATE_VARIABLES,
    default_template,
    unknown_variables,
)
from apps.notifications.utils.vocabulary import (
    CATALOG,
    PERSON_CHANNELS,
    Channel,
    NotificationEvent,
    NotificationRefusal,
    catalog_event,
)
from infrastructure.outbound import OutboundRefused, outbound


class NotificationError(CodedError):
    """A notification request core-api refuses (BR-X-08)."""


@dataclass(frozen=True)
class PreferenceView:
    event: str
    label: str
    channel: str
    enabled: bool
    default_on: bool
    mandatory: bool
    via: list[str]


@dataclass(frozen=True)
class MatrixCellView:
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


@dataclass(frozen=True)
class TemplateView:
    event: str
    channel: str
    language: str
    subject_template: str
    body_template: str
    is_default: bool
    variables: dict[str, str]


@dataclass(frozen=True)
class InboxPage:
    unread: int
    poll_sec: int
    items: list[Message]


def known_event(name: str) -> NotificationEvent:
    """The catalog event `name`; refuses one outside the catalog (BR-F4-02)."""
    event = catalog_event(name)
    if event is None:
        raise NotificationError(
            422, NotificationRefusal.UNKNOWN_EVENT, f"{name!r} is not in the event catalog"
        )
    return event


def label(event: NotificationEvent, language: str) -> str:
    spec = CATALOG[event]
    return spec.label_vi if language == Language.VI.value else spec.label_en


class Inbox:
    """A user's in-app notices."""

    def page(
        self, user: User, *, unread: bool, limit: int, before: datetime | None, poll_sec: int
    ) -> InboxPage:
        rows = Message.objects.inbox(user)
        if unread:
            rows = rows.filter(read_at__isnull=True)
        if before is not None:
            rows = rows.filter(created_at__lt=before)
        count = Message.objects.inbox(user).filter(read_at__isnull=True).count()
        return InboxPage(
            unread=count, poll_sec=poll_sec, items=list(rows.select_related("ticket")[:limit])
        )

    def read(self, user: User, message_id: uuid.UUID) -> None:
        mine = Message.objects.inbox(user).filter(pk=message_id)
        if not mine.exists():
            raise NotificationError(
                404, NotificationRefusal.NOTIFICATION_NOT_FOUND, "no such notification"
            )
        mine.filter(read_at__isnull=True).update(read_at=timezone.now())

    def read_all(self, user: User) -> int:
        return (
            Message.objects.inbox(user).filter(read_at__isnull=True).update(read_at=timezone.now())
        )


class NotificationConfig:
    """Changes to who gets which notice, on which channel, in which words."""

    # ── a user's own preferences ──

    def preferences(self, user: User) -> list[PreferenceView]:
        """Every active event and channel that can reach `user`, with their choice (UC-F4-03)."""
        chosen = {(p.event, p.channel): p.enabled for p in user.notif_preferences.all()}
        rows = list(MatrixRule.objects.all())
        views = []
        for event, spec in CATALOG.items():
            if not spec.active:
                continue
            reach: dict[Channel, tuple[bool, bool]] = {}
            via: list[str] = []
            for (kind, channel), (default_on, mandatory) in notifier.cells(event, rows).items():
                if channel not in PERSON_CHANNELS or not notifier.reaches(kind, user):
                    continue
                on, must = reach.get(channel, (False, False))
                reach[channel] = (on or default_on, must or mandatory)
                if kind.value not in via:
                    via.append(kind.value)
            for channel in PERSON_CHANNELS:
                if channel not in reach:
                    continue
                default_on, mandatory = reach[channel]
                views.append(
                    PreferenceView(
                        event=event.value,
                        label=label(event, user.language),
                        channel=channel.value,
                        enabled=mandatory or chosen.get((event.value, channel.value), default_on),
                        default_on=default_on,
                        mandatory=mandatory,
                        via=via,
                    )
                )
        return views

    def set_language(self, user: User, language: str) -> str:
        """Sets the language `user`'s notices are written in (BR-F4-07), audited."""
        with transaction.atomic():
            before = user.language
            user.language = language
            user.save(update_fields=["language"])
            AuditLog.objects.record(
                "account_language_changed",
                actor_type="human",
                actor_id=user.id,
                payload={"before": before, "after": language},
            )
        return language

    def save_preferences(self, user: User, changes: list[dict[str, Any]]) -> list[PreferenceView]:
        """Saves `user`'s choices; refuses turning off a mandatory cell (BR-F4-03)."""
        for change in changes:
            event = known_event(change["event"])
            if not change["enabled"] and CATALOG[event].is_mandatory(Channel(change["channel"])):
                raise NotificationError(
                    409,
                    NotificationRefusal.MANDATORY_CELL,
                    f"{event.value} by {change['channel']} can't be turned off",
                    {"event": event.value, "channel": change["channel"]},
                )
        with transaction.atomic():
            for change in changes:
                Preference.objects.update_or_create(
                    user=user,
                    event=change["event"],
                    channel=change["channel"],
                    defaults={"enabled": change["enabled"]},
                )
            AuditLog.objects.record(
                "notif_preferences_changed",
                actor_type="human",
                actor_id=user.id,
                payload={"changes": changes},
            )
        return self.preferences(user)

    # ── the matrix ──

    def matrix(self) -> list[MatrixCellView]:
        """Every catalog event's cells, with their defaults (UC-F4-04)."""
        rows = list(MatrixRule.objects.select_related("updated_by"))
        saved = {(r.event, r.recipient_kind, r.channel): r for r in rows}
        views = []
        for event, spec in CATALOG.items():
            for (kind, channel), (default_on, mandatory) in notifier.cells(event, rows).items():
                row = saved.get((event.value, kind.value, channel.value))
                views.append(
                    MatrixCellView(
                        event=event.value,
                        label=spec.label_en,
                        owner=spec.owner,
                        active=spec.active,
                        recipient_kind=kind.value,
                        channel=channel.value,
                        default_on=default_on,
                        mandatory=mandatory,
                        updated_by=row.updated_by.username if row and row.updated_by else None,
                        updated_at=row.updated_at if row else None,
                    )
                )
        return views

    def save_matrix(
        self, actor: User, changes: list[dict[str, Any]], reason: str
    ) -> list[MatrixCellView]:
        """Sets cells' defaults with a reason, audited before and after; a mandatory cell stays on."""
        if not reason.strip():
            raise NotificationError(
                422, NotificationRefusal.REASON_REQUIRED, "say why the matrix changes"
            )
        catalog_cells = {}
        for change in changes:
            event = known_event(change["event"])
            cells = {(c.kind.value, c.channel.value): c for c in CATALOG[event].cells}
            cell = cells.get((change["recipient_kind"], change["channel"]))
            if cell is not None and cell.mandatory and not change["default_on"]:
                raise NotificationError(
                    409,
                    NotificationRefusal.MANDATORY_CELL,
                    f"{event.value} to {cell.kind.value} by {cell.channel.value} is mandatory",
                    {key: change[key] for key in ("event", "recipient_kind", "channel")},
                )
            catalog_cells[(event.value, change["recipient_kind"], change["channel"])] = cell
        diff = []
        with transaction.atomic():
            for change in changes:
                key = (change["event"], change["recipient_kind"], change["channel"])
                cell = catalog_cells[key]
                row, _ = MatrixRule.objects.select_for_update().get_or_create(
                    event=key[0],
                    recipient_kind=key[1],
                    channel=key[2],
                    defaults={
                        "default_on": cell is not None,
                        "mandatory": bool(cell and cell.mandatory),
                    },
                )
                before = row.default_on
                row.default_on = change["default_on"]
                row.updated_by = actor
                row.save(update_fields=["default_on", "updated_by", "updated_at"])
                diff.append(
                    {
                        "event": key[0],
                        "recipient_kind": key[1],
                        "channel": key[2],
                        "before": before,
                        "after": row.default_on,
                    }
                )
            AuditLog.objects.record(
                "notif_matrix_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={"reason": reason.strip(), "changes": diff},
            )
        return self.matrix()

    # ── templates ──

    def template(self, event_name: str, channel: str, language: str) -> TemplateView:
        event = known_event(event_name)
        edited = Template.objects.filter(
            event=event.value, channel=channel, language=language
        ).first()
        subject, body = (
            (edited.subject_template, edited.body_template)
            if edited
            else default_template(event, Language(language))
        )
        return TemplateView(
            event.value, channel, language, subject, body, edited is None, TEMPLATE_VARIABLES
        )

    def save_template(
        self, actor: User, event_name: str, channel: str, language: str, texts: dict[str, str]
    ) -> TemplateView:
        """Saves an edited subject and body; refuses a variable no notice can fill (BR-F4-04)."""
        event = known_event(event_name)
        unknown = unknown_variables(texts["subject_template"], texts["body_template"])
        if unknown:
            raise NotificationError(
                422,
                NotificationRefusal.UNKNOWN_VARIABLE,
                f"unknown variables: {', '.join(sorted(set(unknown)))}",
                {"unknown": sorted(set(unknown))},
            )
        with transaction.atomic():
            before = self.template(event.value, channel, language)
            Template.objects.update_or_create(
                event=event.value,
                channel=channel,
                language=language,
                defaults={**texts, "updated_by": actor},
            )
            AuditLog.objects.record(
                "notif_template_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "event": event.value,
                    "channel": channel,
                    "language": language,
                    "before": {
                        "subject_template": before.subject_template,
                        "body_template": before.body_template,
                    },
                    "after": texts,
                },
            )
        return self.template(event.value, channel, language)

    # ── webhook subscriptions ──

    def check_subscription(self, url: str | None, events: list[str] | None) -> None:
        """Refuses a URL off the allow-list (BR-F4-06) and an event outside the catalog."""
        for name in events or []:
            known_event(name)
        if url is not None:
            try:
                outbound.check_url(url)
            except OutboundRefused as e:
                raise NotificationError(
                    422, NotificationRefusal.WEBHOOK_HOST_REFUSED, str(e), {"url": url}
                ) from e

    def subscription(self, subscription_id: uuid.UUID) -> WebhookSubscription:
        found = WebhookSubscription.objects.filter(pk=subscription_id).first()
        if found is None:
            raise NotificationError(
                404, NotificationRefusal.SUBSCRIPTION_NOT_FOUND, "no such webhook subscription"
            )
        return found

    def subscribe(self, actor: User, data: dict[str, Any]) -> WebhookSubscription:
        self.check_subscription(data["url"], data["events"])
        ciphertext, nonce = webhook_secrets.seal(data["secret"])
        with transaction.atomic():
            subscription = WebhookSubscription.objects.create(
                name=data["name"],
                url=data["url"],
                events=sorted(set(data["events"])),
                secret_ciphertext=ciphertext,
                secret_nonce=nonce,
                created_by=actor,
            )
            self.audit_subscription("notif_webhook_created", actor, subscription)
        return subscription

    def update_subscription(
        self, actor: User, subscription_id: uuid.UUID, data: dict[str, Any]
    ) -> WebhookSubscription:
        self.check_subscription(data.get("url"), data.get("events"))
        with transaction.atomic():
            subscription = self.subscription(subscription_id)
            for name in ("name", "url", "is_active"):
                if data.get(name) is not None:
                    setattr(subscription, name, data[name])
            if data.get("events") is not None:
                subscription.events = sorted(set(data["events"]))
            if data.get("secret"):
                subscription.secret_ciphertext, subscription.secret_nonce = webhook_secrets.seal(
                    data["secret"]
                )
            subscription.save()
            self.audit_subscription(
                "notif_webhook_updated",
                actor,
                subscription,
                secret_rotated=bool(data.get("secret")),
            )
        return subscription

    def unsubscribe(self, actor: User, subscription_id: uuid.UUID) -> None:
        with transaction.atomic():
            subscription = self.subscription(subscription_id)
            self.audit_subscription("notif_webhook_deleted", actor, subscription)
            subscription.delete()

    def audit_subscription(
        self, event: str, actor: User, subscription: WebhookSubscription, **extra: Any
    ) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human",
            actor_id=actor.id,
            payload={
                "subscription": str(subscription.id),
                "name": subscription.name,
                "url": subscription.url,
                "events": subscription.events,
                "is_active": subscription.is_active,
                **extra,
            },
        )


# --- the services ---

inbox = Inbox()
config = NotificationConfig()
