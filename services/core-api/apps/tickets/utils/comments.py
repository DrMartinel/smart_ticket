"""Comments on a ticket: masked inline before they are stored, their PII quarantined, and a comment
whose masking failed held back from staff for a review (F3, BR-F3-06)."""

from __future__ import annotations

import uuid
from enum import StrEnum

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.lifecycle.utils.vocabulary import TRIAGE_STATUSES
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.tickets.models import (
    CommentAuthorKind,
    CommentVisibility,
    PiiQuarantine,
    Ticket,
    TicketComment,
)
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.utils.masking import MaskedReply, mask_reply
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import ReviewQueue

# Attempts at masking a comment whose placeholders another comment took meanwhile.
_MASK_ATTEMPTS = 3


# The status a person moves a ticket into to wait for its requester (F1, BR-F1-07).
WAITING_ON_REQUESTER = "waiting_on_requester"


class CommentRefusal(StrEnum):
    NOT_A_COMMENT_REVIEW = "not_a_comment_review"
    REVIEW_CLOSED = "review_closed"
    TICKET_IN_TRIAGE = "ticket_in_triage"
    VERSION_CONFLICT = "version_conflict"
    NO_WAITING_STATUS = "no_waiting_status"


class CommentError(CodedError):
    """A comment request core-api refuses."""


class CommentReviewChoice(StrEnum):
    SHOW = "show"
    DISCARD = "discard"


class Comments:
    """Adds comments and decides on the ones whose masking failed."""

    def add(
        self,
        ticket: Ticket,
        text: str,
        *,
        author: User | None,
        kind: CommentAuthorKind,
        visibility: CommentVisibility,
    ) -> TicketComment:
        """Masks `text` with both tiers and stores it; updates the caller's `ticket` PII fields."""
        for _ in range(_MASK_ATTEMPTS):
            masked = self.mask(ticket, text)
            with transaction.atomic():
                locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
                if set(masked.placeholder_map) & set(locked.pii_map):
                    ticket.pii_map = locked.pii_map
                    continue
                comment = self.store(
                    locked, masked, author=author, kind=kind, visibility=visibility
                )
            ticket.pii_map, ticket.pii_level = locked.pii_map, locked.pii_level
            return comment
        raise RuntimeError(f"comment placeholders on {ticket.public_id} kept colliding")

    def mask(self, ticket: Ticket, text: str) -> MaskedReply:
        """The comment masked like a ticket, numbering placeholders past the ticket's."""
        return async_to_sync(mask_reply)(
            text, settings.THRESHOLDS.masking.ner_max_share, list(ticket.pii_map)
        )

    def store(
        self,
        locked: Ticket,
        masked: MaskedReply,
        *,
        author: User | None,
        kind: CommentAuthorKind,
        visibility: CommentVisibility,
    ) -> TicketComment:
        """Writes a masked comment on a locked ticket, with its quarantine rows, review item and
        alert."""
        from apps.review.models import ReviewItem

        hidden = masked.pii_level is PIILevel.MASK_FAILED
        comment = TicketComment.objects.create(
            ticket=locked,
            author=author,
            author_kind=kind.value,
            visibility=visibility.value,
            body_masked=masked.text_masked,
            pii_level=masked.pii_level.value,
            hidden_for_review=hidden,
        )
        self.keep_pii(locked, masked)
        if hidden:
            ReviewItem.objects.create(
                ticket=locked, comment=comment, queue=ReviewQueue.MASK_FAILED.value, priority=1
            )
        AuditLog.objects.record(
            "ticket_comment_added",
            actor_type="human" if author else "system",
            actor_id=author.id if author else None,
            ticket_id=locked.id,
            payload={
                "ticket_public_id": locked.public_id,
                "comment": str(comment.id),
                "author_kind": kind.value,
                "visibility": visibility.value,
                "pii_level": masked.pii_level.value,
                "hidden_for_review": hidden,
            },
        )
        if masked.pii_level is PIILevel.CRITICAL:
            self.alert(locked, author, "credential_in_comment", str(comment.id))
        return comment

    def keep_pii(self, locked: Ticket, masked: MaskedReply) -> None:
        """Quarantines the text's raw values and raises the ticket's PII level to match."""
        quarantine = build_quarantine_entries(masked.placeholder_map)
        PiiQuarantine.objects.store(locked, quarantine)
        locked.pii_map = {**locked.pii_map, **{ph: str(e.ref) for ph, e in quarantine.items()}}
        locked.pii_level = PIILevel(locked.pii_level).worse(masked.pii_level).value
        locked.save(update_fields=["pii_map", "pii_level"])

    def alert(self, ticket: Ticket, author: User | None, reason: str, detail: str) -> None:
        """Audits a `security_alert` for a credential in requester or staff text and tells security."""
        AuditLog.objects.record(
            "security_alert",
            actor_type="human" if author else "system",
            actor_id=author.id if author else None,
            ticket_id=ticket.id,
            payload={"ticket_public_id": ticket.public_id, "reason_code": reason},
        )
        notifier.security_alert(
            reason,
            actor=author.username if author else "system",
            detail=detail,
            ticket=ticket,
        )

    def system(self, ticket: Ticket, text: str) -> TicketComment:
        """A public comment the system writes, from fixed text with nothing to mask."""
        comment = TicketComment.objects.create(
            ticket=ticket,
            author=None,
            author_kind=CommentAuthorKind.SYSTEM.value,
            visibility=CommentVisibility.PUBLIC.value,
            body_masked=text,
            pii_level=PIILevel.ROUTINE.value,
        )
        AuditLog.objects.record(
            "ticket_comment_added",
            actor_type="system",
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "comment": str(comment.id),
                "author_kind": CommentAuthorKind.SYSTEM.value,
                "visibility": CommentVisibility.PUBLIC.value,
                "pii_level": PIILevel.ROUTINE.value,
                "hidden_for_review": False,
            },
        )
        return comment

    # ── staff ──

    def by_staff(
        self,
        ticket: Ticket,
        actor: User,
        text: str,
        *,
        visibility: CommentVisibility,
        move_to_waiting: bool,
        expected_version: int | None,
    ) -> TicketComment:
        """A public comment or internal note from staff, optionally moving the ticket to
        `waiting_on_requester` in the same action (UC-F3-06)."""
        from apps.lifecycle.models import Workflow
        from apps.lifecycle.utils.engine import lifecycle
        from apps.sla.utils.clocks import sla_clocks
        from apps.teams.utils.assignment import assignment

        assignment.check_category_scope(actor, ticket)
        if ticket.status in TRIAGE_STATUSES:
            raise CommentError(
                409, CommentRefusal.TICKET_IN_TRIAGE, "the ticket is still with triage"
            )
        if expected_version is not None and ticket.version != expected_version:
            raise CommentError(
                409,
                CommentRefusal.VERSION_CONFLICT,
                f"the ticket is at version {ticket.version}, not {expected_version}",
            )
        masked = self.mask(ticket, text)
        with transaction.atomic():
            if move_to_waiting:
                waiting = (
                    Workflow.objects.of_ticket(ticket)
                    .statuses.filter(key=WAITING_ON_REQUESTER)
                    .first()
                )
                if waiting is None:
                    raise CommentError(
                        409, CommentRefusal.NO_WAITING_STATUS, "the workflow has no such status"
                    )
                lifecycle.move(
                    ticket.id,
                    waiting.id,
                    actor=actor,
                    force=False,
                    expected_version=expected_version,
                )
            locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
            comment = self.store(
                locked, masked, author=actor, kind=CommentAuthorKind.STAFF, visibility=visibility
            )
            if visibility is CommentVisibility.PUBLIC:
                sla_clocks.responded(locked, actor)
                self.announce(locked, comment, actor)
        return comment

    # ── a reviewer on a comment whose masking failed ──

    def review(
        self, item_id: uuid.UUID, reviewer: User, choice: CommentReviewChoice
    ) -> TicketComment:
        """Shows the comment to staff or discards it, and resolves its review item (UC-F3-03 3y)."""
        from apps.review.models import ReviewItem

        with transaction.atomic():
            item = (
                ReviewItem.objects.select_for_update(of=("self",))
                .select_related("comment")
                .get(id=item_id)
            )
            comment = item.comment
            if comment is None:
                raise CommentError(
                    422, CommentRefusal.NOT_A_COMMENT_REVIEW, "this review item is not a comment"
                )
            if not item.is_open:
                raise CommentError(409, CommentRefusal.REVIEW_CLOSED, "already decided")
            if choice is CommentReviewChoice.SHOW:
                comment.hidden_for_review = False
            else:
                comment.discarded_at = timezone.now()
            comment.save(update_fields=["hidden_for_review", "discarded_at"])
            item.state = "resolved"
            item.save(update_fields=["state"])
            AuditLog.objects.record(
                "comment_review_decided",
                actor_type="human",
                actor_id=reviewer.id,
                ticket_id=item.ticket_id,
                payload={"comment": str(comment.id), "choice": choice.value},
            )
            if choice is CommentReviewChoice.SHOW:
                self.announce(item.ticket, comment, reviewer)
        return comment

    def announce(self, ticket: Ticket, comment: TicketComment, actor: User | None) -> None:
        """Tells the other side about a visible public comment."""
        if comment.visibility != CommentVisibility.PUBLIC.value or comment.hidden_for_review:
            return
        if comment.author_kind == CommentAuthorKind.REQUESTER.value:
            event = NotificationEvent.TICKET_REQUESTER_REPLIED
        elif comment.author_kind == CommentAuthorKind.STAFF.value:
            event = NotificationEvent.TICKET_PUBLIC_COMMENT
        else:
            return
        author = comment.author
        notifier.emit(
            event,
            ticket,
            Notice(
                actor=author.username if author else (actor.username if actor else "system"),
                message=comment.body_masked,
                data={"comment": str(comment.id)},
            ),
            event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"comment:{comment.id}"),
        )


# --- the comments service ---

comments = Comments()
