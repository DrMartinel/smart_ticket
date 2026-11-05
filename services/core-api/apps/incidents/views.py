"""Mass incidents (F7 §h): staff read them; incident managers act on them."""

from __future__ import annotations

from django.db.models import Q
from ninja import Query, Router, Status

from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AuthedRequest, SessionAuth, require
from apps.incidents.request_schema import (
    BroadcastIn,
    ConfirmIn,
    DeclareIn,
    IncidentFilter,
    LinksIn,
    ReasonIn,
    ResolveIn,
)
from apps.incidents.response_schema import (
    BroadcastOut,
    CloseResultOut,
    IncidentDetailOut,
    IncidentRowOut,
)
from apps.incidents.utils.incidents import IncidentError, IncidentRefusal, incidents
from apps.tickets.models import Incident

router = Router(tags=["incidents"])


def _detail(public_id: str) -> IncidentDetailOut:
    incident = (
        Incident.objects.select_related("confirmed_by", "resolved_by")
        .filter(public_id=public_id)
        .first()
    )
    if incident is None:
        raise IncidentError(404, IncidentRefusal.NOT_FOUND, "no such incident")
    return IncidentDetailOut.build(incident)


@router.get("", auth=SessionAuth(), response=list[IncidentRowOut])
@require(Permission.INCIDENTS_READ)
def list_incidents(request: AuthedRequest, filters: Query[IncidentFilter]) -> list[IncidentRowOut]:
    rows = Incident.objects.order_by("-created_at")
    if filters.status:
        rows = rows.filter(status=filters.status.value)
    else:
        rows = rows.filter(Q(closed_at__isnull=True) & ~Q(status="dismissed"))
    return [IncidentRowOut.of(i) for i in rows[:200]]


@router.get("/{public_id}", auth=SessionAuth(), response=IncidentDetailOut)
@require(Permission.INCIDENTS_READ)
def get_incident(request: AuthedRequest, public_id: str) -> IncidentDetailOut:
    return _detail(public_id)


@router.post("", auth=SessionAuth(), response={201: IncidentDetailOut})
@require(Permission.INCIDENTS_MANAGE)
def declare(request: AuthedRequest, body: DeclareIn) -> Status[IncidentDetailOut]:
    incident = incidents.declare(
        request.auth,
        body.title,
        body.category,
        body.service,
        body.ticket_ids,
        body.broadcast.model_dump() if body.broadcast else None,
    )
    return Status(201, _detail(incident.public_id))


@router.post("/{public_id}/confirm", auth=SessionAuth(), response=IncidentDetailOut)
@require(Permission.INCIDENTS_MANAGE)
def confirm(request: AuthedRequest, public_id: str, body: ConfirmIn) -> IncidentDetailOut:
    incidents.confirm(public_id, request.auth, body.title, body.category, body.service)
    return _detail(public_id)


@router.post("/{public_id}/dismiss", auth=SessionAuth(), response=IncidentDetailOut)
@require(Permission.INCIDENTS_MANAGE)
def dismiss(request: AuthedRequest, public_id: str, body: ReasonIn) -> IncidentDetailOut:
    incidents.dismiss(public_id, request.auth, body.reason)
    return _detail(public_id)


@router.post("/{public_id}/broadcasts", auth=SessionAuth(), response={201: BroadcastOut})
@require(Permission.INCIDENTS_MANAGE)
def broadcast(request: AuthedRequest, public_id: str, body: BroadcastIn) -> Status[BroadcastOut]:
    sent = incidents.broadcast(public_id, request.auth, **body.model_dump())
    return Status(201, BroadcastOut.of(sent))


@router.post("/{public_id}/resolve", auth=SessionAuth(), response=CloseResultOut)
@require(Permission.INCIDENTS_MANAGE)
def resolve(request: AuthedRequest, public_id: str, body: ResolveIn) -> CloseResultOut:
    result = incidents.resolve(public_id, request.auth, body.resolution_note, body.close_all)
    return CloseResultOut(closed=result.closed, failed=result.failed)


@router.post("/{public_id}/reopen", auth=SessionAuth(), response=IncidentDetailOut)
@require(Permission.INCIDENTS_MANAGE)
def reopen(request: AuthedRequest, public_id: str, body: ReasonIn) -> IncidentDetailOut:
    incidents.reopen(public_id, request.auth, body.reason)
    return _detail(public_id)


@router.post("/{public_id}/links", auth=SessionAuth(), response=IncidentDetailOut)
@require(Permission.INCIDENTS_MANAGE)
def add_links(request: AuthedRequest, public_id: str, body: LinksIn) -> IncidentDetailOut:
    incidents.add_links(public_id, request.auth, body.ticket_ids)
    return _detail(public_id)


@router.delete("/{public_id}/links/{ticket}", auth=SessionAuth(), response={204: None})
@require(Permission.INCIDENTS_UNLINK)
def unlink(request: AuthedRequest, public_id: str, ticket: str, body: ReasonIn) -> Status[None]:
    incidents.unlink(public_id, ticket, request.auth, body.reason)
    return Status(204, None)
