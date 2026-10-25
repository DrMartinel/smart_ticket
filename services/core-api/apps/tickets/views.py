"""
Ticket endpoints. `submit_ticket` is the one HTTP-facing place masking runs
inline and synchronously (spec §5); the contract for what is written before
it returns lives in `TicketManager.submit` (models.py).
"""

import uuid

from ninja import Query, Router
from ninja.errors import HttpError

from apps.tickets.models import StaffView, Ticket, TicketBoard, TicketPage
from apps.tickets.request_schema import TicketIn
from apps.tickets.response_schema import (
    StaffTicketDetail,
    StaffTicketPage,
    StaffTicketBoard,
    TicketOut,
    TicketSubmitOut,
)
from apps.accounts.permissions import ALL_ROLES, STAFF, AuthedRequest, SessionAuth, require_role

router = Router(tags=["tickets"])


@router.post("/submit", auth=SessionAuth(), response=TicketSubmitOut)
@require_role(*ALL_ROLES)
def submit_ticket(request: AuthedRequest, payload: TicketIn) -> Ticket:
    # Ninja validates `payload` against TicketIn's limits and answers 422
    # itself, so an invalid submission never reaches masking.
    return Ticket.objects.submit(
        reporter=request.auth, ticket_in=payload, trace_id=getattr(request, "trace_id", None)
    )


@router.get("", auth=SessionAuth(), response=StaffTicketPage)
@require_role(*STAFF)
def list_tickets(
    request: AuthedRequest,
    view: StaffView = StaffView.ALL,
    q: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> TicketPage:
    return Ticket.objects.page(view, request.auth, query=q, number=page, size=limit)


@router.get("/board", auth=SessionAuth(), response=StaffTicketBoard)
@require_role(*STAFF)
def ticket_board(
    request: AuthedRequest,
    workflow: uuid.UUID,
    q: str = "",
    per_column: int = Query(50, ge=1, le=200),
) -> TicketBoard:
    return Ticket.objects.board(workflow, query=q, per_column=per_column)


@router.get("/{public_id}/detail", auth=SessionAuth(), response=StaffTicketDetail)
@require_role(*STAFF)
def ticket_detail(request: AuthedRequest, public_id: str) -> Ticket:
    try:
        return Ticket.objects.for_detail().get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e


@router.get("/{public_id}", auth=SessionAuth(), response=TicketOut)
@require_role(*ALL_ROLES)
def get_ticket(request: AuthedRequest, public_id: str) -> Ticket:
    try:
        return Ticket.objects.visible_to(request.auth).get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
