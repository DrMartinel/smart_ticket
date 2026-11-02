"""The F10 report endpoints, each with a CSV twin (spec F10 §h)."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse
from ninja import Query, Router

from apps.accounts.models import Capability, UserRole
from apps.accounts.permissions import AuthedRequest, SessionAuth, require_access, require_role
from apps.reports.request_schema import (
    CsatFilter,
    DaysFilter,
    MonthFilter,
    ReviewerFilter,
    SlaFilter,
    SlaTicketsFilter,
    TeamFilter,
    WeeksFilter,
)
from apps.reports.response_schema import (
    CsatReportOut,
    IncidentReportOut,
    KbReportOut,
    NotificationReportOut,
    ReviewerReportOut,
    RolloutReportOut,
    SecurityReportOut,
    SlaReportOut,
    SlaTicketPageOut,
    TeamReportOut,
)
from apps.reports.utils.exports import report_export
from apps.reports.utils.reports import (
    CsatReport,
    IncidentReport,
    KbReport,
    NotificationReport,
    Page,
    ReviewerReport,
    RolloutReport,
    SecurityReport,
    SlaReport,
    TeamReport,
    reports,
)

router = Router(tags=["reports"])

_STAFF = (UserRole.MANAGER, UserRole.TECHNICIAN)
_MANAGER = (UserRole.MANAGER,)


def csv_response(body: str, name: str) -> HttpResponse:
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    return response


# ── SLA ──


def _sla(request: AuthedRequest, f: SlaFilter) -> SlaReport:
    return reports.sla(
        request.auth, month=f.month, team=f.team, priority=f.priority, category=f.category
    )


@router.get("/sla", auth=SessionAuth(), response=SlaReportOut)
@require_role(*_STAFF)
def sla(request: AuthedRequest, filters: Query[SlaFilter]) -> SlaReport:
    return _sla(request, filters)


@router.get("/sla.csv", auth=SessionAuth())
@require_role(*_STAFF)
def sla_csv(request: AuthedRequest, filters: Query[SlaFilter]) -> HttpResponse:
    report = _sla(request, filters)
    body = report_export.write(request.auth, "sla", filters.dict(), report_export.sla(report))
    return csv_response(body, f"sla-{report.month}")


def _sla_tickets(request: AuthedRequest, f: SlaTicketsFilter, page: int | None) -> Page:
    return reports.sla_tickets(
        request.auth,
        month=f.month,
        team=f.team,
        priority=f.priority,
        category=f.category,
        kind=f.kind,
        state=f.state,
        page=page,
    )


@router.get("/sla/tickets", auth=SessionAuth(), response=SlaTicketPageOut)
@require_role(*_STAFF)
def sla_tickets(request: AuthedRequest, filters: Query[SlaTicketsFilter]) -> Page:
    return _sla_tickets(request, filters, filters.page)


@router.get("/sla/tickets.csv", auth=SessionAuth())
@require_role(*_STAFF)
def sla_tickets_csv(request: AuthedRequest, filters: Query[SlaTicketsFilter]) -> HttpResponse:
    body = report_export.write(
        request.auth,
        "sla_tickets",
        filters.dict(),
        report_export.sla_tickets(_sla_tickets(request, filters, None)),
    )
    return csv_response(body, "sla-tickets")


# ── teams ──


@router.get("/teams/{slug}.csv", auth=SessionAuth())
@require_role(*_STAFF)
def team_csv(request: AuthedRequest, slug: str, filters: Query[TeamFilter]) -> HttpResponse:
    report = reports.team(request.auth, slug, filters.start, filters.end)
    body = report_export.write(
        request.auth, "team", {"team": slug, **filters.dict()}, report_export.team(report)
    )
    return csv_response(body, f"team-{slug}")


@router.get("/teams/{slug}", auth=SessionAuth(), response=TeamReportOut)
@require_role(*_STAFF)
def team(request: AuthedRequest, slug: str, filters: Query[TeamFilter]) -> TeamReport:
    return reports.team(request.auth, slug, filters.start, filters.end)


# ── reviewers ──


def _reviewers(request: AuthedRequest, f: ReviewerFilter) -> ReviewerReport:
    days = f.days or settings.THRESHOLDS.reports.window_days
    return reports.reviewers(request.auth, days, f.reviewer)


@router.get("/reviewers", auth=SessionAuth(), response=ReviewerReportOut)
@require_role(*_STAFF)
def reviewers(request: AuthedRequest, filters: Query[ReviewerFilter]) -> ReviewerReport:
    return _reviewers(request, filters)


@router.get("/reviewers.csv", auth=SessionAuth())
@require_role(*_STAFF)
def reviewers_csv(request: AuthedRequest, filters: Query[ReviewerFilter]) -> HttpResponse:
    report = _reviewers(request, filters)
    body = report_export.write(
        request.auth, "reviewers", filters.dict(), report_export.reviewers(report)
    )
    return csv_response(body, "reviewers")


# ── KB ──


def _kb(f: WeeksFilter) -> KbReport:
    return reports.kb(f.weeks or settings.THRESHOLDS.reports.kb_weeks)


@router.get("/kb", auth=SessionAuth(), response=KbReportOut)
@require_access(roles=_MANAGER, capabilities=(Capability.KB_EDITOR,))
def kb(request: AuthedRequest, filters: Query[WeeksFilter]) -> KbReport:
    return _kb(filters)


@router.get("/kb.csv", auth=SessionAuth())
@require_access(roles=_MANAGER, capabilities=(Capability.KB_EDITOR,))
def kb_csv(request: AuthedRequest, filters: Query[WeeksFilter]) -> HttpResponse:
    body = report_export.write(request.auth, "kb", filters.dict(), report_export.kb(_kb(filters)))
    return csv_response(body, "kb")


# ── CSAT ──


def _csat(request: AuthedRequest, f: CsatFilter) -> CsatReport:
    return reports.csat(request.auth, month=f.month, team=f.team)


@router.get("/csat", auth=SessionAuth(), response=CsatReportOut)
@require_role(*_STAFF)
def csat(request: AuthedRequest, filters: Query[CsatFilter]) -> CsatReport:
    return _csat(request, filters)


@router.get("/csat.csv", auth=SessionAuth())
@require_role(*_STAFF)
def csat_csv(request: AuthedRequest, filters: Query[CsatFilter]) -> HttpResponse:
    report = _csat(request, filters)
    body = report_export.write(request.auth, "csat", filters.dict(), report_export.csat(report))
    return csv_response(body, f"csat-{report.month}")


# ── rollout ──


def _rollout(f: DaysFilter) -> RolloutReport:
    return reports.rollout(f.days or settings.THRESHOLDS.reports.rollout_days)


@router.get("/rollout", auth=SessionAuth(), response=RolloutReportOut)
@require_role(UserRole.MANAGER, UserRole.SECURITY)
def rollout(request: AuthedRequest, filters: Query[DaysFilter]) -> RolloutReport:
    return _rollout(filters)


@router.get("/rollout.csv", auth=SessionAuth())
@require_role(UserRole.MANAGER, UserRole.SECURITY)
def rollout_csv(request: AuthedRequest, filters: Query[DaysFilter]) -> HttpResponse:
    body = report_export.write(
        request.auth, "rollout", filters.dict(), report_export.rollout(_rollout(filters))
    )
    return csv_response(body, "rollout")


# ── security ──


@router.get("/security", auth=SessionAuth(), response=SecurityReportOut)
@require_role(UserRole.SECURITY, UserRole.MANAGER)
def security(request: AuthedRequest, filters: Query[MonthFilter]) -> SecurityReport:
    return reports.security(request.auth, filters.month)


@router.get("/security.csv", auth=SessionAuth())
@require_role(UserRole.SECURITY, UserRole.MANAGER)
def security_csv(request: AuthedRequest, filters: Query[MonthFilter]) -> HttpResponse:
    report = reports.security(request.auth, filters.month)
    body = report_export.write(
        request.auth, "security", filters.dict(), report_export.security(report)
    )
    return csv_response(body, f"security-{report.month}")


# ── incidents ──


@router.get("/incidents", auth=SessionAuth(), response=IncidentReportOut)
@require_access(roles=_MANAGER, capabilities=(Capability.INCIDENT_MANAGER,))
def incidents(request: AuthedRequest, filters: Query[MonthFilter]) -> IncidentReport:
    return reports.incidents(filters.month)


@router.get("/incidents.csv", auth=SessionAuth())
@require_access(roles=_MANAGER, capabilities=(Capability.INCIDENT_MANAGER,))
def incidents_csv(request: AuthedRequest, filters: Query[MonthFilter]) -> HttpResponse:
    report = reports.incidents(filters.month)
    body = report_export.write(
        request.auth, "incidents", filters.dict(), report_export.incidents(report)
    )
    return csv_response(body, f"incidents-{report.month}")


# ── notifications ──


def _notifications(f: DaysFilter) -> NotificationReport:
    return reports.notifications(f.days or settings.THRESHOLDS.reports.window_days)


@router.get("/notifications", auth=SessionAuth(), response=NotificationReportOut)
@require_access(roles=_MANAGER, capabilities=(Capability.WORKFLOW_ADMIN,))
def notifications(request: AuthedRequest, filters: Query[DaysFilter]) -> NotificationReport:
    return _notifications(filters)


@router.get("/notifications.csv", auth=SessionAuth())
@require_access(roles=_MANAGER, capabilities=(Capability.WORKFLOW_ADMIN,))
def notifications_csv(request: AuthedRequest, filters: Query[DaysFilter]) -> HttpResponse:
    body = report_export.write(
        request.auth,
        "notifications",
        filters.dict(),
        report_export.notifications(_notifications(filters)),
    )
    return csv_response(body, "notifications")
