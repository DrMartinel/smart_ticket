"""
Ticket endpoints. `submit_ticket` is the one HTTP-facing place masking runs
inline and synchronously (spec §5); the contract for what is written before
it returns lives in `TicketManager.submit` (models.py).
"""

import uuid
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpResponse
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import LimitOffsetPagination, paginate

from apps.accounts.models import UserRole
from apps.tickets.models import PiiAccessLog, StaffView, Ticket, TicketBoard, TicketPage
from apps.tickets.request_schema import AccessLogFilter, RevealIn, TicketIn
from apps.tickets.response_schema import (
    AccessLogRowOut,
    RevealOut,
    StaffTicketDetail,
    StaffTicketPage,
    StaffTicketBoard,
    TicketOut,
    TicketSubmitOut,
)
from apps.accounts.permissions import ALL_ROLES, STAFF, AuthedRequest, SessionAuth, require_role
from apps.sla.request_schema import PriorityIn
from apps.sla.response_schema import TicketSlaOut
from apps.sla.utils.clocks import sla_clocks
from apps.teams.request_schema import ReassignIn, TakeIn
from apps.teams.response_schema import AssignedTicketOut
from apps.teams.utils.assignment import ReassignRequest, assignment
from apps.tickets.utils.pii_reveal import PiiReveal, Revealed

router = Router(tags=["tickets"])
pii_router = Router(tags=["pii"])

_REVEALERS = (UserRole.TECHNICIAN, UserRole.SECURITY)
_SECURITY = (UserRole.SECURITY,)


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


@router.post("/{public_id}/take", auth=SessionAuth(), response=AssignedTicketOut)
@require_role(*STAFF)
def take(request: AuthedRequest, public_id: str, payload: TakeIn) -> Ticket:
    return assignment.take(public_id, request.auth, payload.expected_version)


@router.post("/{public_id}/reassign", auth=SessionAuth(), response=AssignedTicketOut)
@require_role(*STAFF)
def reassign(request: AuthedRequest, public_id: str, payload: ReassignIn) -> Ticket:
    return assignment.reassign(
        public_id,
        request.auth,
        ReassignRequest(
            to_user=payload.to_user,
            to_team=payload.to_team,
            to_category=payload.to_category.value if payload.to_category else None,
            reason_code=payload.reason_code,
            note=payload.note,
            expected_version=payload.expected_version,
        ),
    )


@router.get("/{public_id}/sla", auth=SessionAuth(), response=TicketSlaOut)
@require_role(*ALL_ROLES)
def ticket_sla(request: AuthedRequest, public_id: str) -> dict[str, Any]:
    try:
        ticket = Ticket.objects.visible_to(request.auth).get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
    return sla_clocks.view(ticket, staff=request.auth.is_support_staff)


@router.patch("/{public_id}/priority", auth=SessionAuth(), response=TicketSlaOut)
@require_role(*STAFF)
def change_priority(request: AuthedRequest, public_id: str, payload: PriorityIn) -> dict[str, Any]:
    ticket = sla_clocks.change_priority(
        _staff_ticket(public_id),
        request.auth,
        payload.priority,
        payload.reason,
        payload.expected_version,
    )
    return sla_clocks.view(ticket, staff=True)


@router.post("/{public_id}/sla/rebuild", auth=SessionAuth(), response=TicketSlaOut)
@require_role(UserRole.MANAGER)
def rebuild_sla(request: AuthedRequest, public_id: str) -> dict[str, Any]:
    ticket = _staff_ticket(public_id)
    sla_clocks.rebuild(ticket, request.auth)
    return sla_clocks.view(ticket, staff=True)


def _staff_ticket(public_id: str) -> Ticket:
    try:
        return Ticket.objects.get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e


@router.post("/{public_id}/quarantine/reveal", auth=SessionAuth(), response=RevealOut)
@require_role(*_REVEALERS)
def reveal(
    request: AuthedRequest, public_id: str, payload: RevealIn, response: HttpResponse
) -> Revealed:
    response["Cache-Control"] = "no-store"
    return PiiReveal(settings.THRESHOLDS.pii_reveal).reveal(
        public_id=public_id,
        actor=request.auth,
        placeholder=payload.placeholder,
        reason_code=payload.reason_code,
        reason=payload.reason,
        trace_id=getattr(request, "trace_id", None),
    )


@pii_router.get("/access-log", auth=SessionAuth(), response=list[AccessLogRowOut])
@paginate(LimitOffsetPagination)
@require_role(*_SECURITY)
def access_log(request: AuthedRequest, filters: Query[AccessLogFilter]) -> QuerySet[PiiAccessLog]:
    return PiiAccessLog.objects.matching(**filters.dict())


@pii_router.get("/access-log.csv", auth=SessionAuth())
@require_role(*_SECURITY)
def access_log_csv(request: AuthedRequest, filters: Query[AccessLogFilter]) -> HttpResponse:
    criteria = filters.dict()
    body = PiiReveal(settings.THRESHOLDS.pii_reveal).export_log(
        PiiAccessLog.objects.matching(**criteria),
        request.auth,
        filters.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="pii-access-log.csv"'
    response["Cache-Control"] = "no-store"
    return response
