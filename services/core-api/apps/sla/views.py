"""SLA endpoints: policies, calendars, holidays, a due-time preview and the breach list (F1 §h).
A ticket's clocks, priority and rebuild are on the ticket routes."""

from __future__ import annotations

import uuid


from django.db.models import QuerySet
from ninja import Router, Status
from ninja.pagination import LimitOffsetPagination, paginate

from apps.accounts.models import Capability, UserRole
from apps.accounts.permissions import STAFF, AuthedRequest, SessionAuth, require_access
from apps.sla.models import Calendar, Clock, Holiday, Policy
from apps.sla.request_schema import (
    CalendarIn,
    CalendarPatch,
    HolidayIn,
    PolicyIn,
    PolicyPatch,
    PreviewIn,
    ReasonIn,
)
from apps.sla.response_schema import BreachOut, CalendarOut, HolidayOut, PolicyOut, PreviewOut
from apps.sla.utils.clocks import Preview, sla_clocks
from apps.sla.utils.config import SlaConfigError, SlaConfigRefusal, sla_config

router = Router(tags=["sla"])

_ADMIN = (Capability.WORKFLOW_ADMIN,)
_MANAGER = (UserRole.MANAGER,)


# ── policies ──


@router.get("/policies", auth=SessionAuth(), response=list[PolicyOut])
@require_access(roles=STAFF)
def policies(request: AuthedRequest) -> QuerySet[Policy]:
    return Policy.objects.select_related("calendar", "created_by", "approved_by")


@router.post("/policies", auth=SessionAuth(), response={201: PolicyOut})
@require_access(capabilities=_ADMIN)
def draft_policy(request: AuthedRequest, payload: PolicyIn) -> Status:
    return Status(201, sla_config.draft(request.auth, payload.model_dump(mode="json")))


@router.patch("/policies/{policy_id}", auth=SessionAuth(), response=PolicyOut)
@require_access(capabilities=_ADMIN)
def edit_policy(request: AuthedRequest, policy_id: uuid.UUID, payload: PolicyPatch) -> Policy:
    return sla_config.edit(
        request.auth, policy_id, payload.model_dump(mode="json", exclude_unset=True)
    )


@router.post("/policies/{policy_id}/approve", auth=SessionAuth(), response=PolicyOut)
@require_access(roles=_MANAGER)
def approve_policy(request: AuthedRequest, policy_id: uuid.UUID, payload: ReasonIn) -> Policy:
    return sla_config.approve(request.auth, policy_id, payload.reason)


@router.post("/policies/{policy_id}/retire", auth=SessionAuth(), response=PolicyOut)
@require_access(roles=_MANAGER)
def retire_policy(request: AuthedRequest, policy_id: uuid.UUID, payload: ReasonIn) -> Policy:
    return sla_config.retire(request.auth, policy_id, payload.reason)


# ── calendars and holidays ──


@router.get("/calendars", auth=SessionAuth(), response=list[CalendarOut])
@require_access(roles=STAFF)
def calendars(request: AuthedRequest) -> QuerySet[Calendar]:
    return Calendar.objects.all()


@router.post("/calendars", auth=SessionAuth(), response={201: CalendarOut})
@require_access(capabilities=_ADMIN)
def create_calendar(request: AuthedRequest, payload: CalendarIn) -> Status:
    return Status(201, sla_config.save_calendar(request.auth, payload.model_dump()))


@router.patch("/calendars/{calendar_id}", auth=SessionAuth(), response=CalendarOut)
@require_access(capabilities=_ADMIN)
def edit_calendar(
    request: AuthedRequest, calendar_id: uuid.UUID, payload: CalendarPatch
) -> Calendar:
    return sla_config.save_calendar(
        request.auth, payload.model_dump(exclude_unset=True), calendar_id
    )


@router.get("/calendars/{calendar_id}/holidays", auth=SessionAuth(), response=list[HolidayOut])
@require_access(roles=STAFF)
def holidays(request: AuthedRequest, calendar_id: uuid.UUID) -> QuerySet[Holiday]:
    return Holiday.objects.filter(calendar_id=calendar_id)


@router.post(
    "/calendars/{calendar_id}/holidays", auth=SessionAuth(), response={201: list[HolidayOut]}
)
@require_access(capabilities=_ADMIN)
def add_holidays(request: AuthedRequest, calendar_id: uuid.UUID, payload: HolidayIn) -> Status:
    start = payload.date or payload.from_date
    end = payload.date or payload.to_date or start
    if start is None or end is None:
        raise SlaConfigError(422, SlaConfigRefusal.BAD_INTERVAL, "give a date, or from and to")
    return Status(201, sla_config.add_holidays(request.auth, calendar_id, start, end, payload.name))


@router.delete(
    "/calendars/{calendar_id}/holidays/{holiday_id}", auth=SessionAuth(), response={204: None}
)
@require_access(capabilities=_ADMIN)
def remove_holiday(request: AuthedRequest, calendar_id: uuid.UUID, holiday_id: uuid.UUID) -> Status:
    sla_config.remove_holiday(request.auth, calendar_id, holiday_id)
    return Status(204, None)


# ── preview and breaches ──


@router.post("/preview", auth=SessionAuth(), response=PreviewOut)
@require_access(roles=STAFF)
def preview(request: AuthedRequest, payload: PreviewIn) -> Preview:
    return sla_clocks.preview(
        payload.category.value if payload.category else None, payload.priority, payload.start_at
    )


@router.get("/breaches", auth=SessionAuth(), response=list[BreachOut])
@paginate(LimitOffsetPagination)
@require_access(roles=STAFF)
def breaches(
    request: AuthedRequest, team: str | None = None, state: str | None = None
) -> QuerySet[Clock]:
    return sla_clocks.breaches(team=team, state=state)
