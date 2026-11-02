"""What a requester sees of their tickets (F3): a row per ticket, the public thread, the rating."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.utils import timezone
from ninja import Schema

from apps.accounts.models import User
from apps.lifecycle.utils.vocabulary import TRIAGE_STATUSES
from apps.requester.utils.tickets import requester_tickets
from apps.requester.utils.vocabulary import CommentState, status_label
from apps.tickets.models import CommentAuthorKind, Ticket, TicketComment


class RatingOut(Schema):
    score: int
    comment_masked: str | None
    resolution_seq: int
    rated_at: datetime
    updated_at: datetime


class RequesterTicketRow(Schema):
    public_id: str
    subject_masked: str
    source: str
    # From the system status base, in the requester's language (BR-F3-05).
    status_label: str
    team: str | None
    resolution_due_at: datetime | None
    sla_paused: bool
    unread_comments: int
    created_at: datetime
    resolved_at: datetime | None
    # Until when the ticket may be reopened or rated; None while it is open.
    can_reopen_until: datetime | None
    rating: int | None

    @classmethod
    def of(cls, ticket: Ticket, viewer: User) -> RequesterTicketRow:
        """One ticket's row for its requester."""
        status = ticket.workflow_status
        rating = requester_tickets.rating(ticket)
        return cls(
            public_id=ticket.public_id,
            subject_masked=ticket.subject_masked,
            source=ticket.source,
            status_label=status_label(
                status.base.name if status else None,
                bool(status and status.pauses_sla),
                viewer.language,
            ),
            team=ticket.team.name if ticket.team else None,
            **requester_tickets.resolution_clock(ticket),
            unread_comments=requester_tickets.unread(ticket),
            created_at=ticket.created_at,
            resolved_at=ticket.resolved_at,
            can_reopen_until=requester_tickets.reopen_until(ticket),
            rating=rating.score if rating else None,
        )


class RequesterTicketList(Schema):
    open: list[RequesterTicketRow]
    recent: list[RequesterTicketRow]
    # Pass as `before` for older completed tickets ("Xem thêm"); None when there are none.
    more_before: datetime | None


class ThreadCommentOut(Schema):
    id: uuid.UUID
    author_kind: str
    # Support's username, "you" for the requester's own, "system" for the system's.
    author: str
    mine: bool
    state: CommentState
    # Masked as stored; empty while it is held for a check or after it was discarded.
    body_masked: str
    # True when the text held a password or similar: the requester is asked not to send one.
    credential_masked: bool
    created_at: datetime

    @classmethod
    def of(cls, comment: TicketComment, viewer: User) -> ThreadCommentOut:
        mine = comment.author_id == viewer.id
        if comment.discarded_at is not None:
            state = CommentState.DISCARDED
        elif comment.hidden_for_review:
            state = CommentState.CHECKING
        else:
            state = CommentState.SHOWN
        if comment.author_kind == CommentAuthorKind.SYSTEM.value:
            author = "system"
        elif mine:
            author = "you"
        else:
            author = comment.author.username if comment.author else "support"
        return cls(
            id=comment.id,
            author_kind=comment.author_kind,
            author=author,
            mine=mine,
            state=state,
            body_masked=comment.body_masked if state is CommentState.SHOWN else "",
            credential_masked=comment.pii_level == "critical",
            created_at=comment.created_at,
        )


class RequesterTicketOut(RequesterTicketRow):
    body_masked: str
    thread: list[ThreadCommentOut]
    rating_detail: RatingOut | None
    can_reply: bool
    can_rate: bool
    reopened_count: int
    reopened_from: str | None

    @classmethod
    def detail(cls, ticket: Ticket, viewer: User) -> RequesterTicketOut:
        """The ticket page: its row, body, public thread and rating (UC-F3-03)."""
        row = RequesterTicketRow.of(ticket, viewer)
        until = row.can_reopen_until
        rating = requester_tickets.rating(ticket)
        open_window = until is not None and until >= timezone.now()
        return cls(
            **row.model_dump(),
            body_masked=ticket.body_masked,
            thread=[ThreadCommentOut.of(c, viewer) for c in requester_tickets.thread(ticket)],
            rating_detail=RatingOut.model_validate(rating, from_attributes=True)
            if rating
            else None,
            can_reply=ticket.resolved_at is None and ticket.status not in TRIAGE_STATUSES,
            can_rate=open_window,
            reopened_count=ticket.reopened_count,
            reopened_from=ticket.reopened_from.public_id if ticket.reopened_from else None,
        )


class ReopenOut(Schema):
    reopened: bool
    new_ticket: str | None = None
