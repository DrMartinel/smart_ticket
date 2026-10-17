"""
Ticket endpoints. `submit_ticket` is the one HTTP-facing place masking runs
inline and synchronously (spec §5); the contract for what is written before
it returns lives in `TicketManager.submit` (models.py).
"""

import uuid

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
        return Ticket.objects.select_related(
            "reporter", "assigned_to", "workflow_status__base"
        ).get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e


@router.get("/{public_id}", auth=SessionAuth(), response=TicketOut)
@require_role(*ALL_ROLES)
def get_ticket(request: AuthedRequest, public_id: str) -> Ticket:
    try:
        return Ticket.objects.visible_to(request.auth).get(public_id=public_id)
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
