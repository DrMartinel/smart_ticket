"""Turns an event into messages: the matrix's recipients, their preferences, their language (ADR-0033)."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Language, User, UserRole
from apps.audit.models import AuditLog
from apps.lifecycle.utils.templates import VARIABLES, render
from apps.notifications.models import MatrixRule, Message, Preference, Template, WebhookSubscription
from apps.notifications.utils.templates import default_template
from apps.notifications.utils.vocabulary import (
    CATALOG,
    PERSON_CHANNELS,
    REQUESTER_KINDS,
    Channel,
    FailureReason,
    MessageState,
    NotificationEvent,
    RecipientKind,
)
from apps.teams.models import MembershipRole, TeamMembership

if TYPE_CHECKING:
    from apps.lifecycle.models import Transfer
    from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)

_CAPABILITY_KINDS = {
    RecipientKind.WORKFLOW_ADMINS: "workflow_admin",
    RecipientKind.KB_EDITORS: "kb_editor",
    RecipientKind.INCIDENT_MANAGERS: "incident_manager",
}
_ROLE_KINDS = {RecipientKind.MANAGER: UserRole.MANAGER, RecipientKind.SECURITY: UserRole.SECURITY}


@dataclass(frozen=True)
class Notice:
    """What an event tells its recipients beyond the ticket: masked or account data only."""

    actor: str = "system"
    reason: str = ""
    detail: str = ""
    message: str = ""
    link: str = ""
    previous_assignee: User | None = None
    approvers: tuple[User, ...] = ()
    linked_requesters: tuple[User, ...] = ()
    # A team other than the ticket's, e.g. the fallback team.
    team: str | None = None
    transfer: Transfer | None = None
    # The webhook body's `data`.
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Delivery:
    """Who gets an event on one channel, and why: the strongest cell that reaches them."""

    user: User
    kind: RecipientKind
    default_on: bool
    mandatory: bool


class Notifier:
    """Writes an event's messages in the caller's transaction and sends the rest after commit."""

    def emit(
        self,
        event: NotificationEvent,
        ticket: Ticket | None = None,
        notice: Notice | None = None,
        *,
        event_id: uuid.UUID | None = None,
    ) -> list[Message]:
        """The messages written for `event`; a failure here is audited and never reaches the caller."""
        notice = notice or Notice()
        event_id = event_id or uuid.uuid4()
        try:
            with transaction.atomic():
                messages = self.messages_for(event, ticket, notice, event_id)
                Message.objects.bulk_create(messages, ignore_conflicts=True)
        except Exception:  # noqa: BLE001 — a notice never breaks the event that caused it
            logger.exception("notifications: emitting %s failed", event.value)
            AuditLog.objects.record(
                "notification_emit_failed",
                actor_type="system",
                ticket_id=ticket.id if ticket else None,
                payload={"event": event.value, "event_id": str(event_id)},
            )
            return []
        queued = [m.id for m in messages if m.state == MessageState.QUEUED.value]
        if queued:
            transaction.on_commit(partial(self.queue_dispatch, queued), robust=True)
        return messages

    def assignment_changed(self, ticket: Ticket, previous: User | None, actor: str) -> None:
        """Tells people a ticket was assigned, reassigned or unassigned; nothing if it wasn't."""
        current = ticket.assigned_to
        if (current.id if current else None) == (previous.id if previous else None):
            return
        if previous is None:
            event = NotificationEvent.TICKET_ASSIGNED
        elif current is None:
            event = NotificationEvent.TICKET_UNASSIGNED
        else:
            event = NotificationEvent.TICKET_REASSIGNED
        data = {
            "assignee": current.username if current else None,
            "previous_assignee": previous.username if previous else None,
            "team": ticket.assigned_team,
            "by": actor,
        }
        self.emit(event, ticket, Notice(actor=actor, previous_assignee=previous, data=data))

    def security_alert(
        self, reason: str, *, actor: str, detail: str, ticket: Ticket | None = None
    ) -> None:
        """Tells security about a `security_alert` audit row (mandatory in-app and email)."""
        self.emit(
            NotificationEvent.SECURITY_ALERT,
            ticket,
            Notice(actor=actor, reason=reason, detail=detail, data={"reason": reason}),
        )

    def queue_dispatch(self, ids: list[uuid.UUID]) -> None:
        from apps.notifications import tasks

        for message_id in ids:
            tasks.dispatch.delay(str(message_id))

    # ── who ──

    def deliveries(
        self, event: NotificationEvent, ticket: Ticket | None, notice: Notice
    ) -> dict[tuple[uuid.UUID, Channel], Delivery]:
        """Every user a cell of `event` reaches, per channel, before preferences."""
        found: dict[tuple[uuid.UUID, Channel], Delivery] = {}
        rows = MatrixRule.objects.filter(event=event.value)
        for (kind, channel), (default_on, mandatory) in self.cells(event, rows).items():
            for user in self.recipients(kind, ticket, notice):
                seen = found.get((user.id, channel))
                if seen is None:
                    found[(user.id, channel)] = Delivery(user, kind, default_on, mandatory)
                else:
                    seen.default_on |= default_on
                    seen.mandatory |= mandatory
        return found

    def cells(
        self, event: NotificationEvent, rows: Iterable[MatrixRule]
    ) -> dict[tuple[RecipientKind, Channel], tuple[bool, bool]]:
        """Each (kind, channel) of `event` with its default and whether it is mandatory, from the
        catalog and `event`'s matrix rows; a mandatory cell is always on."""
        defaults = {
            (RecipientKind(r.recipient_kind), Channel(r.channel)): r.default_on
            for r in rows
            if r.event == event.value
        }
        cells = {
            (c.kind, c.channel): (
                c.mandatory or defaults.get((c.kind, c.channel), True),
                c.mandatory,
            )
            for c in CATALOG[event].cells
        }
        for cell, default_on in defaults.items():
            cells.setdefault(cell, (default_on, False))
        return cells

    def reaches(self, kind: RecipientKind, user: User) -> bool:
        """Whether a recipient kind can ever name `user`, for their settings page."""
        if kind in _ROLE_KINDS:
            return user.role == _ROLE_KINDS[kind].value
        if kind in _CAPABILITY_KINDS:
            return _CAPABILITY_KINDS[kind] in user.capability_set()
        if kind in (RecipientKind.ASSIGNEE, RecipientKind.PREVIOUS_ASSIGNEE):
            return user.role in (UserRole.TECHNICIAN.value, UserRole.MANAGER.value)
        if kind is RecipientKind.TEAM_LEAD:
            return user.team_memberships.filter(role=MembershipRole.LEAD.value).exists()
        if kind is RecipientKind.TEAM_MEMBERS:
            return user.team_memberships.exists()
        if kind is RecipientKind.APPROVER:
            return user.is_support_staff
        return True

    def recipients(self, kind: RecipientKind, ticket: Ticket | None, notice: Notice) -> list[User]:
        """The active users a recipient kind names for this event."""
        users: list[User | None]
        if kind in _ROLE_KINDS:
            users = list(User.objects.filter(role=_ROLE_KINDS[kind].value, is_active=True))
        elif kind in _CAPABILITY_KINDS:
            users = list(
                User.objects.filter(
                    capabilities__capability=_CAPABILITY_KINDS[kind], is_active=True
                ).distinct()
            )
        elif kind in (RecipientKind.TEAM_LEAD, RecipientKind.TEAM_MEMBERS):
            team = notice.team or (ticket.assigned_team if ticket else None)
            memberships = TeamMembership.objects.filter(
                team__slug=team, team__is_active=True
            ).select_related("user")
            if kind is RecipientKind.TEAM_LEAD:
                memberships = memberships.filter(role=MembershipRole.LEAD.value)
            users = [m.user for m in memberships] if team else []
        elif kind is RecipientKind.REQUESTER:
            users = [ticket.reporter] if ticket else []
        elif kind is RecipientKind.ASSIGNEE:
            users = [ticket.assigned_to] if ticket else []
        elif kind is RecipientKind.PREVIOUS_ASSIGNEE:
            users = [notice.previous_assignee]
        elif kind is RecipientKind.APPROVER:
            users = list(notice.approvers)
        else:
            users = list(notice.linked_requesters)
        return [u for u in users if u is not None and u.is_active]

    # ── what ──

    def messages_for(
        self,
        event: NotificationEvent,
        ticket: Ticket | None,
        notice: Notice,
        event_id: uuid.UUID,
    ) -> list[Message]:
        deliveries = self.deliveries(event, ticket, notice)
        preferences = {
            (p.user_id, Channel(p.channel)): p.enabled
            for p in Preference.objects.filter(
                event=event.value, user_id__in={user_id for user_id, _ in deliveries}
            )
        }
        emission = Emission(
            event,
            ticket,
            notice,
            event_id,
            now=timezone.now(),
            variables=self.variables(ticket, notice),
            templates={
                (t.channel, t.language): t for t in Template.objects.filter(event=event.value)
            },
        )
        messages = [
            emission.person_message(delivery, channel)
            for (user_id, channel), delivery in deliveries.items()
            if channel in PERSON_CHANNELS
            and (delivery.mandatory or preferences.get((user_id, channel), delivery.default_on))
        ]
        subscriptions = WebhookSubscription.objects.filter(
            is_active=True, events__contains=[event.value]
        )
        return messages + [emission.webhook_message(s) for s in subscriptions]

    def variables(self, ticket: Ticket | None, notice: Notice) -> dict[str, str]:
        """The masked ticket, transfer and notice values a template may name."""
        from apps.lifecycle.models import Workflow
        from apps.lifecycle.utils.runner import runner

        variables = {name: "" for name in VARIABLES if not name.startswith("field.")}
        if ticket is not None:
            workflow = Workflow.objects.of_ticket(ticket)
            variables |= runner.variables(ticket, notice.transfer, workflow)
        else:
            now = timezone.now()
            variables |= {"now": now.isoformat(), "today": timezone.localdate().isoformat()}
        previous = notice.previous_assignee
        return variables | {
            "notice.actor": notice.actor,
            "notice.reason": notice.reason,
            "notice.detail": notice.detail,
            "notice.message": notice.message,
            "notice.previousAssignee": previous.username if previous else "",
        }


@dataclass(frozen=True)
class Emission:
    """One event being written as messages: what every message of it is rendered from."""

    event: NotificationEvent
    ticket: Ticket | None
    notice: Notice
    event_id: uuid.UUID
    now: datetime
    variables: dict[str, str]
    templates: dict[tuple[str, str], Template]

    def person_message(self, delivery: Delivery, channel: Channel) -> Message:
        """The notice for one user on one channel, in their language, failed on a template error."""
        user = delivery.user
        language = Language.EN if user.language == Language.EN.value else Language.VI
        link = self.notice.link or self.link(delivery.kind)
        edited = self.templates.get((channel.value, language.value))
        subject_template, body_template = (
            (edited.subject_template, edited.body_template)
            if edited
            else default_template(self.event, language)
        )
        spec = CATALOG[self.event]
        unknown: list[str] = []
        filled = self.variables | {
            "notice.event": spec.label_en if language is Language.EN else spec.label_vi,
            "notice.link": link,
        }
        message = Message(
            event_id=self.event_id,
            event=self.event.value,
            ticket=self.ticket,
            user=user,
            channel=channel.value,
            language=language.value,
            subject=" ".join(render(subject_template, filled, unknown).split())[:255],
            body=render(body_template, filled, unknown),
            link=link,
            state=MessageState.QUEUED.value,
        )
        if unknown:
            message.state = MessageState.FAILED.value
            message.last_error = (
                f"{FailureReason.TEMPLATE_ERROR}: unknown variables {sorted(set(unknown))}"
            )
        elif channel is Channel.IN_APP:
            message.state = MessageState.DELIVERED.value
            message.delivered_at = self.now
        elif not user.email:
            message.state = MessageState.FAILED.value
            message.last_error = f"{FailureReason.NO_ADDRESS}: {user.username} has no email address"
        return message

    def link(self, kind: RecipientKind) -> str:
        """The page a notice opens: the chat for a requester, the admin console for staff."""
        if self.ticket is None:
            return ""
        if kind in REQUESTER_KINDS:
            return f"/?ticket={self.ticket.public_id}"
        return f"/tickets/{self.ticket.public_id}"

    def webhook_message(self, subscription: WebhookSubscription) -> Message:
        return Message(
            event_id=self.event_id,
            event=self.event.value,
            ticket=self.ticket,
            subscription=subscription,
            channel=Channel.WEBHOOK.value,
            subject=self.event.value,
            body=self.webhook_body(),
            state=MessageState.QUEUED.value,
        )

    def webhook_body(self) -> str:
        """The fixed JSON every subscription gets, from masked fields only (BR-F4-06)."""
        ticket = self.ticket
        body = {
            "event": self.event.value,
            "event_id": str(self.event_id),
            "occurred_at": self.now.isoformat().replace("+00:00", "Z"),
            "ticket": None
            if ticket is None
            else {
                "id": ticket.public_id,
                "subject": ticket.subject_masked,
                "status": ticket.status,
                "category": ticket.category,
                "priority": None,
                "assigned_team": ticket.assigned_team,
                "assignee": ticket.assigned_to.username if ticket.assigned_to else None,
            },
            "data": self.notice.data,
        }
        return json.dumps(body, ensure_ascii=False)


# --- the notifier ---

notifier = Notifier()
