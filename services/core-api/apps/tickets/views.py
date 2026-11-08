"""
Ticket endpoints. `submit_ticket` is the one HTTP-facing place masking runs
inline and synchronously (spec §5); the contract for what is written before
it returns lives in `TicketIntake.submit` (utils/intake.py).
"""

import uuid
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpResponse
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import LimitOffsetPagination, paginate

from apps.tickets.utils.intake import ticket_intake
from apps.tickets.models import (
    CommentVisibility,
    PiiAccessLog,
    StaffView,
    Ticket,
    TicketBoard,
    TicketPage,
)
from apps.tickets.request_schema import AccessLogFilter, CommentIn, RevealIn, TicketIn
from apps.tickets.response_schema import (
    CommentOut,
    AccessLogRowOut,
    RevealOut,
    StaffTicketDetail,
    StaffTicketPage,
    StaffTicketBoard,
    TicketOut,
    TicketSubmitOut,
)
from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import (
    AgentTier,
    AuthedRequest,
    SessionAuth,
    require,
)
from apps.sla.request_schema import PriorityIn
from apps.sla.response_schema import TicketSlaOut
from apps.sla.utils.clocks import sla_clocks
from apps.teams.request_schema import ReassignIn, TakeIn
from apps.teams.response_schema import AssignedTicketOut
from apps.teams.utils.assignment import ReassignRequest, assignment
from apps.tickets.utils.comments import comments
from apps.tickets.utils.pii_reveal import PiiReveal, Revealed

router = Router(tags=["tickets"])
pii_router = Router(tags=["pii"])


@router.post("/submit", auth=SessionAuth(), response=TicketSubmitOut)
@require(Permission.REQUESTER_SUBMIT, agent=AgentTier.NONE)
def submit_ticket(request: AuthedRequest, payload: TicketIn) -> Ticket:
    # Ninja validates `payload` against TicketIn's limits and answers 422
    # itself, so an invalid submission never reaches masking.
    return ticket_intake.submit(
        reporter=request.auth.user, ticket_in=payload, trace_id=getattr(request, "trace_id", None)
    )


@router.get("", auth=SessionAuth(), response=StaffTicketPage)
@require(Permission.TICKETS_READ, agent=AgentTier.READ)
def list_tickets(
    request: AuthedRequest,
    view: StaffView = StaffView.ALL,
    q: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> TicketPage:
    return Ticket.objects.page(view, request.auth.user, query=q, number=page, size=limit)


@router.get("/board", auth=SessionAuth(), response=StaffTicketBoard)
@require(Permission.TICKETS_READ, agent=AgentTier.READ)
def ticket_board(
    request: AuthedRequest,
    workflow: uuid.UUID,
    q: str = "",
    per_column: int = Query(50, ge=1, le=200),
) -> TicketBoard:
    return Ticket.objects.board(workflow, request.auth.user, query=q, per_column=per_column)


@router.get("/{public_id}/detail", auth=SessionAuth(), response=StaffTicketDetail)
@require(Permission.TICKETS_READ, agent=AgentTier.READ)
def ticket_detail(request: AuthedRequest, public_id: str) -> Ticket:
    try:
        ticket = Ticket.objects.for_detail().get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
    request.auth.require_covering(Permission.TICKETS_READ, ticket)
    return ticket


@router.get("/{public_id}", auth=SessionAuth(), response=TicketOut)
@require(Permission.REQUESTER_TICKET_STATUS, agent=AgentTier.READ)
def get_ticket(request: AuthedRequest, public_id: str) -> Ticket:
    try:
        return Ticket.objects.visible_to(request.auth.user).get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e


@router.post("/{public_id}/take", auth=SessionAuth(), response=AssignedTicketOut)
@require(Permission.TICKETS_TAKE, agent=AgentTier.CONFIRM)
def take(request: AuthedRequest, public_id: str, payload: TakeIn) -> Ticket:
    _staff_ticket(request, public_id, Permission.TICKETS_TAKE)
    return assignment.take(public_id, request.auth.user, payload.expected_version)


@router.post("/{public_id}/reassign", auth=SessionAuth(), response=AssignedTicketOut)
@require(Permission.TICKETS_REASSIGN, agent=AgentTier.HUMAN_ONLY)
def reassign(request: AuthedRequest, public_id: str, payload: ReassignIn) -> Ticket:
    _staff_ticket(request, public_id, Permission.TICKETS_REASSIGN)
    return assignment.reassign(
        public_id,
        request.auth.user,
        ReassignRequest(
            to_user=payload.to_user,
            to_team=payload.to_team,
            to_category=payload.to_category.value if payload.to_category else None,
            reason_code=payload.reason_code,
            note=payload.note,
            expected_version=payload.expected_version,
        ),
    )


@router.get("/{public_id}/comments", auth=SessionAuth(), response=list[CommentOut])
@require(Permission.TICKETS_READ, agent=AgentTier.READ)
def ticket_comments(request: AuthedRequest, public_id: str) -> list[CommentOut]:
    ticket = _staff_ticket(request, public_id, Permission.TICKETS_READ)
    assignment.check_category_scope(request.auth.user, ticket)
    rows = ticket.comments.select_related("author").prefetch_related("review_items")
    rows = rows.order_by("created_at")
    return [CommentOut.of(c) for c in rows]


@router.post("/{public_id}/comments", auth=SessionAuth(), response=CommentOut)
@require(Permission.TICKETS_COMMENT, agent=AgentTier.CONFIRM)
def add_comment(request: AuthedRequest, public_id: str, payload: CommentIn) -> CommentOut:
    comment = comments.by_staff(
        _staff_ticket(request, public_id, Permission.TICKETS_COMMENT),
        request.auth.user,
        payload.body,
        visibility=CommentVisibility(payload.visibility),
        move_to_waiting=payload.move_to_waiting,
        expected_version=payload.expected_version,
    )
    return CommentOut.of(comment)


@router.get("/{public_id}/sla", auth=SessionAuth(), response=TicketSlaOut)
@require(Permission.REQUESTER_TICKET_STATUS, agent=AgentTier.READ)
def ticket_sla(request: AuthedRequest, public_id: str) -> dict[str, Any]:
    try:
        ticket = Ticket.objects.visible_to(request.auth.user).get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
    return sla_clocks.view(ticket, staff=request.auth.user.is_support_staff)


@router.patch("/{public_id}/priority", auth=SessionAuth(), response=TicketSlaOut)
@require(Permission.TICKETS_PRIORITY, agent=AgentTier.HUMAN_ONLY)
def change_priority(request: AuthedRequest, public_id: str, payload: PriorityIn) -> dict[str, Any]:
    ticket = sla_clocks.change_priority(
        _staff_ticket(request, public_id, Permission.TICKETS_PRIORITY),
        request.auth.user,
        payload.priority,
        payload.reason,
        payload.expected_version,
    )
    return sla_clocks.view(ticket, staff=True)


@router.post("/{public_id}/sla/rebuild", auth=SessionAuth(), response=TicketSlaOut)
@require(Permission.TICKETS_SLA_REBUILD, agent=AgentTier.HUMAN_ONLY)
def rebuild_sla(request: AuthedRequest, public_id: str) -> dict[str, Any]:
    ticket = _staff_ticket(request, public_id, Permission.TICKETS_SLA_REBUILD)
    sla_clocks.rebuild(ticket, request.auth.user)
    return sla_clocks.view(ticket, staff=True)


def _staff_ticket(request: AuthedRequest, public_id: str, permission: Permission) -> Ticket:
    try:
        ticket = Ticket.objects.select_related("reporter").get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
    request.auth.require_covering(permission, ticket)
    return ticket


@router.post("/{public_id}/quarantine/reveal", auth=SessionAuth(), response=RevealOut)
@require(Permission.PII_REVEAL, agent=AgentTier.HUMAN_ONLY)
def reveal(
    request: AuthedRequest, public_id: str, payload: RevealIn, response: HttpResponse
) -> Revealed:
    response["Cache-Control"] = "no-store"
    return PiiReveal(settings.THRESHOLDS.pii_reveal).reveal(
        public_id=public_id,
        actor=request.auth.user,
        placeholder=payload.placeholder,
        reason_code=payload.reason_code,
        reason=payload.reason,
        trace_id=getattr(request, "trace_id", None),
    )


@pii_router.get("/access-log", auth=SessionAuth(), response=list[AccessLogRowOut])
@paginate(LimitOffsetPagination)
@require(Permission.PII_ACCESS_LOG_READ, agent=AgentTier.NONE)
def access_log(request: AuthedRequest, filters: Query[AccessLogFilter]) -> QuerySet[PiiAccessLog]:
    return PiiAccessLog.objects.matching(**filters.dict())


@pii_router.get("/access-log.csv", auth=SessionAuth())
@require(Permission.PII_ACCESS_LOG_READ, agent=AgentTier.NONE)
def access_log_csv(request: AuthedRequest, filters: Query[AccessLogFilter]) -> HttpResponse:
    criteria = filters.dict()
    body = PiiReveal(settings.THRESHOLDS.pii_reveal).export_log(
        PiiAccessLog.objects.matching(**criteria),
        request.auth.user,
        filters.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="pii-access-log.csv"'
    response["Cache-Control"] = "no-store"
    return response
