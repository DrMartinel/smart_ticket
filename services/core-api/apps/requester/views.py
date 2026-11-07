"""The requester's tickets, form and chat: list, thread, reply, reopen, rate (F3), and the tickets
of the departments a department head heads (F14)."""

from __future__ import annotations

from datetime import datetime

from ninja import Query, Router

from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AuthedRequest, SessionAuth, require
from apps.accounts.response_schema import DepartmentTicketOut
from apps.requester.request_schema import RatingIn, ReopenIn, ReplyIn
from apps.requester.response_schema import (
    RatingOut,
    ReopenOut,
    RequesterTicketList,
    RequesterTicketOut,
    RequesterTicketRow,
    ThreadCommentOut,
)
from apps.requester.utils.tickets import requester_tickets
from apps.requester.utils.vocabulary import status_label
from apps.tickets.models import Ticket, TicketRating

router = Router(tags=["requester"])


@router.get("/tickets", auth=SessionAuth(), response=RequesterTicketList)
@require(Permission.REQUESTER_TICKETS)
def my_tickets(request: AuthedRequest, before: datetime | None = None) -> RequesterTicketList:
    listing = requester_tickets.listing(request.auth.user, before)
    return RequesterTicketList(
        open=[RequesterTicketRow.of(t, request.auth.user) for t in listing.open],
        recent=[RequesterTicketRow.of(t, request.auth.user) for t in listing.recent],
        more_before=listing.more_before,
    )


@router.get("/department-tickets", auth=SessionAuth(), response=list[DepartmentTicketOut])
@require(Permission.REQUESTER_DEPARTMENT_READ)
def department_tickets(
    request: AuthedRequest, open_only: bool = True, limit: int = Query(100, ge=1, le=500)
) -> list[DepartmentTicketOut]:
    rows = Ticket.objects.in_department_of(request.auth.user).select_related(
        "reporter__department", "workflow_status", "team"
    )
    if open_only:
        rows = rows.filter(resolved_at__isnull=True)
    return [
        DepartmentTicketOut(
            public_id=t.public_id,
            subject_masked=t.subject_masked,
            requester=t.reporter.username,
            requester_name=t.reporter.get_full_name(),
            department=t.reporter.department.code if t.reporter.department else None,
            status_label=status_label(t.workflow_status, request.auth.user.language),
            team=t.team.name if t.team else None,
            created_at=t.created_at,
            resolved_at=t.resolved_at,
        )
        for t in rows.order_by("-created_at")[:limit]
    ]


@router.get("/tickets/{public_id}", auth=SessionAuth(), response=RequesterTicketOut)
@require(Permission.REQUESTER_TICKETS)
def my_ticket(request: AuthedRequest, public_id: str) -> RequesterTicketOut:
    return RequesterTicketOut.detail(
        requester_tickets.own(request.auth.user, public_id), request.auth.user
    )


@router.post("/tickets/{public_id}/replies", auth=SessionAuth(), response=ThreadCommentOut)
@require(Permission.REQUESTER_TICKETS)
def reply(request: AuthedRequest, public_id: str, payload: ReplyIn) -> ThreadCommentOut:
    comment = requester_tickets.reply(request.auth.user, public_id, payload.body)
    return ThreadCommentOut.of(comment, request.auth.user)


@router.post("/tickets/{public_id}/reopen", auth=SessionAuth(), response=ReopenOut)
@require(Permission.REQUESTER_TICKETS)
def reopen(request: AuthedRequest, public_id: str, payload: ReopenIn) -> ReopenOut:
    done = requester_tickets.reopen(request.auth.user, public_id, payload.reason)
    return ReopenOut(reopened=done.reopened, new_ticket=done.new_ticket)


@router.put("/tickets/{public_id}/rating", auth=SessionAuth(), response=RatingOut)
@require(Permission.REQUESTER_TICKETS)
def rate(request: AuthedRequest, public_id: str, payload: RatingIn) -> TicketRating:
    return requester_tickets.rate(request.auth.user, public_id, payload.score, payload.comment)
