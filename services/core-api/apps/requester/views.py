"""The requester's tickets, form and chat: list, thread, reply, reopen, rate (F3). Every endpoint
sees only the caller's own tickets; anyone else's is a 404 (BR-F3-04)."""

from __future__ import annotations

from datetime import datetime

from ninja import Router

from apps.accounts.permissions import ALL_ROLES, AuthedRequest, SessionAuth, require_role
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
from apps.tickets.models import TicketRating

router = Router(tags=["requester"])


@router.get("/tickets", auth=SessionAuth(), response=RequesterTicketList)
@require_role(*ALL_ROLES)
def my_tickets(request: AuthedRequest, before: datetime | None = None) -> RequesterTicketList:
    listing = requester_tickets.listing(request.auth, before)
    return RequesterTicketList(
        open=[RequesterTicketRow.of(t, request.auth) for t in listing.open],
        recent=[RequesterTicketRow.of(t, request.auth) for t in listing.recent],
        more_before=listing.more_before,
    )


@router.get("/tickets/{public_id}", auth=SessionAuth(), response=RequesterTicketOut)
@require_role(*ALL_ROLES)
def my_ticket(request: AuthedRequest, public_id: str) -> RequesterTicketOut:
    return RequesterTicketOut.detail(requester_tickets.own(request.auth, public_id), request.auth)


@router.post("/tickets/{public_id}/replies", auth=SessionAuth(), response=ThreadCommentOut)
@require_role(*ALL_ROLES)
def reply(request: AuthedRequest, public_id: str, payload: ReplyIn) -> ThreadCommentOut:
    comment = requester_tickets.reply(request.auth, public_id, payload.body)
    return ThreadCommentOut.of(comment, request.auth)


@router.post("/tickets/{public_id}/reopen", auth=SessionAuth(), response=ReopenOut)
@require_role(*ALL_ROLES)
def reopen(request: AuthedRequest, public_id: str, payload: ReopenIn) -> ReopenOut:
    done = requester_tickets.reopen(request.auth, public_id, payload.reason)
    return ReopenOut(reopened=done.reopened, new_ticket=done.new_ticket)


@router.put("/tickets/{public_id}/rating", auth=SessionAuth(), response=RatingOut)
@require_role(*ALL_ROLES)
def rate(request: AuthedRequest, public_id: str, payload: RatingIn) -> TicketRating:
    return requester_tickets.rate(request.auth, public_id, payload.score, payload.comment)
