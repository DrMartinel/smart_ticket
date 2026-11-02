"""What a requester is told when their ticket's status changes: received at handoff, waiting for
them, resolved (F3 FR-F3-013)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent

if TYPE_CHECKING:
    from apps.lifecycle.models import Transfer, WorkflowStatus
    from apps.tickets.models import Ticket


def _is_work(status: WorkflowStatus) -> bool:
    """Whether a status is support's work: neither intake nor completed."""
    return not status.base.is_backlog and not status.base.is_completed


class TicketNotices:
    """Emits the requester's status events after a committed status change."""

    def on_status_entered(self, ticket: Ticket, transfer: Transfer) -> None:
        before, after = transfer.before_status, transfer.after_status
        if after is None:
            return
        if _is_work(after) and (before is None or before.base.is_backlog):
            self.emit(NotificationEvent.TICKET_RECEIVED, ticket, "received")
        if after.pauses_sla and not (before is not None and before.pauses_sla):
            self.emit(
                NotificationEvent.TICKET_STATUS_CHANGED,
                ticket,
                f"waiting:{transfer.id}",
                Notice(data={"status": "waiting_on_requester"}),
            )
        if after.base.is_completed and not (before is not None and before.base.is_completed):
            self.emit(
                NotificationEvent.TICKET_RESOLVED,
                ticket,
                f"resolved:{ticket.resolution_seq}",
                Notice(data={"resolution_seq": ticket.resolution_seq}),
            )

    def emit(
        self, event: NotificationEvent, ticket: Ticket, key: str, notice: Notice | None = None
    ) -> None:
        notifier.emit(
            event, ticket, notice, event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{ticket.id}:{key}")
        )


# --- the ticket notices service ---

ticket_notices = TicketNotices()
