"""The F10 reports: what each one counts, and who may read which rows (BR-F10-05)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from django.conf import settings
from django.db.models import Count, Min, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.core.errors import CodedError
from apps.incidents.models import IncidentBroadcast, IncidentLink
from apps.kb.models import DraftState, GapState, KbDraft, KbGapCluster
from apps.kb.utils.gaps import kb_gaps, unit
from apps.kb.utils.graph import GraphHealth, kb_graph
from apps.metrics.utils import percentile
from apps.notifications.models import Message
from apps.notifications.utils.vocabulary import Channel, MessageState
from apps.reports.models import FactState, TicketFacts, TicketFactsQuerySet
from apps.reports.utils.facts import report_zone
from apps.requester.utils.tickets import requester_tickets
from apps.review.models import ReviewDecision
from apps.rollout.utils.gates import AGREEMENT_BRANCH, Agreement, GateValue, rollout_metrics
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.vocabulary import FlagBranch
from apps.security.models import SecurityAlert
from apps.security.utils.vocabulary import AlertKind, Resolution
from apps.sla.models import Clock, ClockState
from apps.teams.models import MembershipRole, Reassignment, Team, TeamMembership
from apps.tickets.models import Incident, IncidentStatus, RoutingDecision, Ticket, TicketRating
from apps.tickets.utils.router import ReasonCode

AUTOMATED_BRANCHES = ("auto_reply", "auto_route")
AGE_BUCKETS = (("0-1", 0, 1), ("1-3", 1, 3), ("3-5", 3, 5), (">5", 5, None))


class ReportRefusal(StrEnum):
    SCOPE_DENIED = "report_scope_denied"
    TEAM_NOT_FOUND = "report_team_not_found"


class ReportError(CodedError):
    pass


# ── periods ──


@dataclass(frozen=True)
class Period:
    """[start, end) in UTC, from local days of the report zone."""

    start: datetime
    end: datetime
    label: str

    @classmethod
    def month(cls, month: str | None, zone: ZoneInfo) -> Period:
        if month:
            year, mon = (int(p) for p in month.split("-"))
        else:
            today = timezone.now().astimezone(zone).date()
            year, mon = today.year, today.month
        first = date(year, mon, 1)
        nxt = date(year + mon // 12, mon % 12 + 1, 1)
        return cls(local(first, zone), local(nxt, zone), f"{year:04d}-{mon:02d}")

    @classmethod
    def days(cls, start: date, end: date, zone: ZoneInfo) -> Period:
        """`start` to `end`, both days included."""
        return cls(local(start, zone), local(end + timedelta(days=1), zone), f"{start}..{end}")

    @classmethod
    def last_days(cls, days: int) -> Period:
        now = timezone.now()
        return cls(now - timedelta(days=days), now, f"{days}d")


def local(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone)


def ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def seconds_between(pairs: Iterable[tuple[datetime | None, datetime | None]]) -> list[float]:
    return [(b - a).total_seconds() for a, b in pairs if a is not None and b is not None]


# ── the shapes the views return ──


@dataclass
class Compliance:
    met: int
    breached: int

    @property
    def compliance(self) -> float | None:
        return ratio(self.met, self.met + self.breached)


@dataclass
class Warned:
    warned: int
    breached: int

    @property
    def rate(self) -> float | None:
        return ratio(self.warned, self.breached)


@dataclass
class SlaCell:
    key: str
    response: Compliance
    resolution: Compliance


@dataclass
class SlaExcluded:
    linked_incident: int
    no_sla_data: int


@dataclass
class SlaReport:
    month: str
    team: str | None
    priority: str | None
    category: str | None
    response: Compliance
    resolution: Compliance
    breaches_warned_in_time: Warned
    excluded: SlaExcluded
    open_overdue_now: int
    by_team: list[SlaCell]
    by_priority: list[SlaCell]
    by_category: list[SlaCell]


@dataclass
class SlaTicket:
    id: Any
    public_id: str
    subject: str
    team: str | None
    priority: str | None
    category: str | None
    state: str
    met_at: datetime | None
    linked_incident: bool


@dataclass
class Page:
    items: list[Any]
    total: int
    page: int
    page_size: int


@dataclass
class MemberRow:
    username: str
    display_name: str
    role: str
    open_now: int
    age_buckets: dict[str, int]
    resolved_in_period: int
    time_to_assign_median_min: float | None
    time_to_assign_p90_min: float | None
    reassigned_in: int
    reassigned_out: int


@dataclass
class TeamReport:
    team: str
    start: date
    end: date
    members: list[MemberRow]
    tickets_assigned: int
    tickets_reassigned_cross_team: int
    unassigned_now: int
    time_to_assign_median_min: float | None
    time_to_assign_p90_min: float | None

    @property
    def reassignment_rate(self) -> float | None:
        return ratio(self.tickets_reassigned_cross_team, self.tickets_assigned)


@dataclass
class ReviewerRow:
    username: str
    decisions: int
    approved: int
    median_seconds: float | None
    previous_approve_rate: float | None
    flagged: bool

    @property
    def approve_rate(self) -> float | None:
        return ratio(self.approved, self.decisions)


@dataclass
class ReviewerReport:
    days: int
    min_decisions_for_flag: int
    approve_rate_max: float
    median_time_min_sec: int
    rows: list[ReviewerRow]


@dataclass
class RefusalWeek:
    week_start: date
    decisions: int
    refused: int

    @property
    def refusal_rate(self) -> float | None:
        return ratio(self.refused, self.decisions)


@dataclass
class GapClosure:
    cluster_id: Any
    label: str
    size: int
    article_slug: str | None
    published_at: datetime
    before: int
    after: int
    complete: bool

    @property
    def closure(self) -> float | None:
        return 1 - self.after / self.before if self.before else None


@dataclass
class KbReport:
    weeks: int
    refusals: list[RefusalWeek]
    open_clusters: int
    open_by_label: dict[str, int]
    closures: list[GapClosure]
    graph: GraphHealth


@dataclass
class CsatLine:
    ratings: int
    resolved: int
    mean: float | None
    distribution: dict[str, int]

    @property
    def response_rate(self) -> float | None:
        return ratio(self.ratings, self.resolved)


@dataclass
class CsatTeam:
    team: str
    auto: CsatLine
    person: CsatLine


@dataclass
class LowRating:
    ticket_public_id: str
    team: str | None
    score: int
    comment: str
    rated_at: datetime


@dataclass
class CsatReport:
    month: str
    team: str | None
    auto: CsatLine
    person: CsatLine
    by_team: list[CsatTeam]
    low_rated: list[LowRating]


@dataclass
class BranchReadiness:
    branch: str
    decision_branch: str
    live: bool
    agreement: Agreement
    shadow_decisions: int
    gates: list[GateValue]
    total_decisions: int

    @property
    def coverage(self) -> float | None:
        return ratio(self.shadow_decisions, self.total_decisions)


@dataclass
class Automation:
    total: int
    live: int
    would_have: int

    @property
    def live_rate(self) -> float | None:
        return ratio(self.live, self.total)

    @property
    def would_have_rate(self) -> float | None:
        return ratio(self.would_have, self.total)


@dataclass
class RolloutReport:
    days: int
    branches: list[BranchReadiness]
    automation: Automation


@dataclass
class SecurityKind:
    kind: str
    count: int
    open: int


@dataclass
class SecurityReport:
    month: str
    detail: bool
    total: int
    by_kind: list[SecurityKind]
    ack_p50_sec: float | None = None
    ack_p90_sec: float | None = None
    ack_in_target: int | None = None
    acknowledged: int | None = None
    closed: int | None = None
    false_positive: int | None = None

    @property
    def false_positive_rate(self) -> float | None:
        return ratio(self.false_positive or 0, self.closed or 0) if self.detail else None


@dataclass
class IncidentReport:
    month: str
    detected: int
    confirmed: int
    dismissed: int
    linked_tickets: int
    links_created: int
    links_unlinked: int
    confirm_p50_sec: float | None
    first_broadcast_p50_sec: float | None
    first_broadcast_p90_sec: float | None

    @property
    def unlink_rate(self) -> float | None:
        return ratio(self.links_unlinked, self.links_created)


@dataclass
class ChannelRow:
    channel: str
    messages: int
    delivered: int
    failed: int
    latency_p95_sec: float | None


@dataclass
class NotificationReport:
    days: int
    channels: list[ChannelRow]


@dataclass
class WeeklySummary:
    week: str
    response: Compliance
    resolution: Compliance
    breaches_warned_in_time: Warned
    time_to_assign_median_min: float | None
    reassignment_rate: float | None
    csat_auto: float | None
    csat_person: float | None
    reopen_rate_after_autoreply: float | None
    extra: dict[str, Any] = field(default_factory=dict)


# ── the service ──


class Reports:
    """Every F10 report, read from the facts table for past days and live for now."""

    # ── scope (BR-F10-05) ──

    def lead_teams(self, user: User) -> set[str]:
        return set(
            TeamMembership.objects.filter(user=user, role=MembershipRole.LEAD.value).values_list(
                "team__slug", flat=True
            )
        )

    def team_scope(self, viewer: User, team: str | None) -> list[str] | None:
        """The teams `viewer` may read with `team` asked for; None means every team."""
        if viewer.is_manager:
            return [team] if team else None
        led = self.lead_teams(viewer)
        if team is None and led:
            return sorted(led)
        if team is not None and team in led:
            return [team]
        raise ReportError(403, ReportRefusal.SCOPE_DENIED, "only a manager or the team's lead")

    def team_facts(self, teams: list[str] | None) -> TicketFactsQuerySet:
        rows = TicketFacts.objects.all()
        return rows if teams is None else rows.filter(team__in=teams)

    def team_tickets(self, teams: list[str] | None, prefix: str = "") -> Q:
        """Tickets of `teams` by the team row, else the routed team name."""
        if teams is None:
            return Q()
        return Q(**{f"{prefix}team__slug__in": teams}) | Q(
            **{f"{prefix}team__isnull": True, f"{prefix}assigned_team__in": teams}
        )

    # ── SLA (UC-F10-01) ──

    def compliance(self, rows: TicketFactsQuerySet, kind: str, period: Period) -> Compliance:
        stopped = rows.filter(linked_incident=False).stopped(kind, period.start, period.end)
        counts = Counter(stopped.values_list(f"{kind}_state", flat=True))
        return Compliance(counts[FactState.MET.value], counts[FactState.BREACHED.value])

    def warned(self, rows: TicketFactsQuerySet, period: Period) -> Warned:
        warned = breached = 0
        for kind in ("response", "resolution"):
            stopped = rows.filter(linked_incident=False).stopped(kind, period.start, period.end)
            flags = stopped.filter(**{f"{kind}_state": FactState.BREACHED.value}).values_list(
                f"{kind}_warned_in_time", flat=True
            )
            breached += len(flags)
            warned += sum(1 for f in flags if f)
        return Warned(warned, breached)

    def in_period(self, rows: TicketFactsQuerySet, period: Period) -> TicketFactsQuerySet:
        """Rows with a clock that stopped in the period, or created or resolved in it."""
        return rows.filter(
            Q(response_met_at__gte=period.start, response_met_at__lt=period.end)
            | Q(resolution_met_at__gte=period.start, resolution_met_at__lt=period.end)
            | Q(resolved_at__gte=period.start, resolved_at__lt=period.end)
            | Q(
                created_day__gte=period.start.date(),
                created_day__lt=period.end.date(),
            )
        )

    def filtered(
        self,
        viewer: User,
        team: str | None,
        priority: str | None,
        category: str | None,
    ) -> tuple[list[str] | None, TicketFactsQuerySet]:
        teams = self.team_scope(viewer, team)
        rows = self.team_facts(teams)
        if priority:
            rows = rows.filter(priority=priority)
        if category:
            rows = rows.filter(category=category)
        return teams, rows

    def sla(
        self,
        viewer: User,
        *,
        month: str | None,
        team: str | None = None,
        priority: str | None = None,
        category: str | None = None,
    ) -> SlaReport:
        period = Period.month(month, report_zone())
        teams, rows = self.filtered(viewer, team, priority, category)
        touched = self.in_period(rows, period)
        no_data = touched.filter(
            response_state=FactState.NONE.value, resolution_state=FactState.NONE.value
        )
        return SlaReport(
            month=period.label,
            team=team,
            priority=priority,
            category=category,
            response=self.compliance(rows, "response", period),
            resolution=self.compliance(rows, "resolution", period),
            breaches_warned_in_time=self.warned(rows, period),
            excluded=SlaExcluded(
                linked_incident=touched.filter(linked_incident=True).count(),
                no_sla_data=no_data.filter(linked_incident=False).count(),
            ),
            open_overdue_now=self.open_overdue(teams, priority, category),
            by_team=self.cells(rows, "team", period),
            by_priority=self.cells(rows, "priority", period),
            by_category=self.cells(rows, "category", period),
        )

    def cells(self, rows: TicketFactsQuerySet, key: str, period: Period) -> list[SlaCell]:
        """One cell per value of `key` with at least one clock stopped in the period."""
        keys = sorted(
            {k for k in self.in_period(rows, period).values_list(key, flat=True) if k is not None}
        )
        cells = [
            SlaCell(
                key=k,
                response=self.compliance(rows.filter(**{key: k}), "response", period),
                resolution=self.compliance(rows.filter(**{key: k}), "resolution", period),
            )
            for k in keys
        ]
        return [
            c
            for c in cells
            if c.response.met + c.response.breached + c.resolution.met + c.resolution.breached
        ]

    def open_overdue(
        self, teams: list[str] | None, priority: str | None, category: str | None
    ) -> int:
        """Clocks breached and still open now (FR-F10-003), read live."""
        now = timezone.now()
        clocks = Clock.objects.filter(
            Q(state=ClockState.BREACHED.value) | Q(state=ClockState.RUNNING.value, due_at__lt=now)
        ).filter(self.team_tickets(teams, "ticket__"))
        if priority:
            clocks = clocks.filter(ticket__priority=priority)
        if category:
            clocks = clocks.filter(ticket__category=category)
        return clocks.values("ticket").distinct().count()

    def sla_tickets(
        self,
        viewer: User,
        *,
        month: str | None,
        team: str | None = None,
        priority: str | None = None,
        category: str | None = None,
        kind: str = "resolution",
        state: str | None = None,
        page: int | None = 1,
    ) -> Page:
        """The tickets behind an SLA cell: stopped clocks, or `excluded` for the left-out ones."""
        period = Period.month(month, report_zone())
        _, rows = self.filtered(viewer, team, priority, category)
        if state == "excluded":
            rows = self.in_period(rows, period).filter(
                Q(linked_incident=True)
                | Q(response_state=FactState.NONE.value, resolution_state=FactState.NONE.value)
            )
        else:
            rows = rows.filter(linked_incident=False).stopped(kind, period.start, period.end)
            if state:
                rows = rows.filter(**{f"{kind}_state": state})
        size = settings.THRESHOLDS.reports.list_page_size
        rows = rows.select_related("ticket").order_by(f"{kind}_met_at", "ticket__public_id")
        total = rows.count()
        shown = rows if page is None else rows[(page - 1) * size : page * size]
        items = [
            SlaTicket(
                id=f.ticket.id,
                public_id=f.ticket.public_id,
                subject=f.ticket.subject_masked,
                team=f.team,
                priority=f.priority,
                category=f.category,
                state=getattr(f, f"{kind}_state"),
                met_at=getattr(f, f"{kind}_met_at"),
                linked_incident=f.linked_incident,
            )
            for f in shown
        ]
        return Page(items=items, total=total, page=page or 1, page_size=size)

    # ── teams (UC-F10-02) ──

    def team(self, viewer: User, slug: str, start: date | None, end: date | None) -> TeamReport:
        team = Team.objects.filter(slug=slug).select_related("calendar").first()
        if team is None:
            raise ReportError(404, ReportRefusal.TEAM_NOT_FOUND, "team not found")
        zone = report_zone()
        today = timezone.now().astimezone(zone).date()
        end = end or today
        start = start or end - timedelta(days=6)
        period = Period.days(start, end, zone)
        memberships = TeamMembership.objects.filter(team=team).select_related("user")
        own = memberships.filter(user=viewer).first()
        if viewer.is_manager or (own is not None and own.role == MembershipRole.LEAD.value):
            shown = list(memberships.order_by("user__username"))
        elif own is not None:
            shown = [own]
        else:
            raise ReportError(403, ReportRefusal.SCOPE_DENIED, "not a member of this team")
        facts = TicketFacts.objects.filter(
            team=slug,
            first_assigned_at__gte=period.start,
            first_assigned_at__lt=period.end,
        )
        minutes = [m for m in facts.values_list("time_to_assign_business_min", flat=True) if m]
        return TeamReport(
            team=slug,
            start=start,
            end=end,
            members=[self.member_row(m, team, period) for m in shown],
            tickets_assigned=facts.count(),
            tickets_reassigned_cross_team=facts.filter(cross_team_reassign_count__gt=0).count(),
            unassigned_now=self.open_tickets()
            .filter(self.team_tickets([slug]), assigned_to__isnull=True)
            .count(),
            time_to_assign_median_min=percentile(minutes, 0.5),
            time_to_assign_p90_min=percentile(minutes, 0.9),
        )

    def open_tickets(self) -> QuerySet[Ticket]:
        return Ticket.objects.filter(resolved_at__isnull=True).exclude(
            workflow_status__base__is_completed=True
        )

    def member_row(self, membership: TeamMembership, team: Team, period: Period) -> MemberRow:
        user = membership.user
        now = timezone.now()
        buckets = dict.fromkeys((b[0] for b in AGE_BUCKETS), 0)
        for ticket in self.open_tickets().filter(assigned_to=user).select_related("team__calendar"):
            age = requester_tickets.calendar(ticket).whole_days(ticket.created_at, now)
            for name, low, high in AGE_BUCKETS:
                if age >= low and (high is None or age < high):
                    buckets[name] += 1
                    break
        assigned = TicketFacts.objects.filter(
            ticket__assigned_to=user,
            first_assigned_at__gte=period.start,
            first_assigned_at__lt=period.end,
        )
        minutes = [m for m in assigned.values_list("time_to_assign_business_min", flat=True) if m]
        moved = Reassignment.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
        return MemberRow(
            username=user.username,
            display_name=user.get_full_name() or user.username,
            role=membership.role,
            open_now=sum(buckets.values()),
            age_buckets=buckets,
            resolved_in_period=Ticket.objects.filter(
                assigned_to=user, resolved_at__gte=period.start, resolved_at__lt=period.end
            ).count(),
            time_to_assign_median_min=percentile(minutes, 0.5),
            time_to_assign_p90_min=percentile(minutes, 0.9),
            reassigned_in=moved.filter(to_user=user).count(),
            reassigned_out=moved.filter(from_user=user).count(),
        )

    # ── reviewers (UC-F10-03) ──

    def reviewers(self, viewer: User, days: int, reviewer: str | None = None) -> ReviewerReport:
        """Every reviewer for a manager; anyone else gets their own row, and asking for someone
        else's is refused."""
        if not viewer.is_manager:
            if reviewer not in (None, viewer.username):
                raise ReportError(403, ReportRefusal.SCOPE_DENIED, "a reviewer sees only themself")
            reviewer = viewer.username
        th = settings.THRESHOLDS
        now = timezone.now()
        current = self.reviewer_counts(now - timedelta(days=days), now, reviewer)
        previous = self.reviewer_counts(
            now - timedelta(days=2 * days), now - timedelta(days=days), reviewer
        )
        rows = []
        for username, (decisions, approved, seconds) in sorted(current.items()):
            median = percentile(seconds, 0.5)
            rate = ratio(approved, decisions)
            before = previous.get(username)
            rows.append(
                ReviewerRow(
                    username=username,
                    decisions=decisions,
                    approved=approved,
                    median_seconds=median,
                    previous_approve_rate=ratio(before[1], before[0]) if before else None,
                    flagged=decisions >= th.reports.min_decisions_for_flag
                    and rate is not None
                    and rate > th.alerts.reviewer_approve_rate_max
                    and median is not None
                    and median < th.alerts.reviewer_median_time_min_sec,
                )
            )
        if reviewer and not rows:
            rows.append(ReviewerRow(reviewer, 0, 0, None, None, False))
        return ReviewerReport(
            days=days,
            min_decisions_for_flag=th.reports.min_decisions_for_flag,
            approve_rate_max=th.alerts.reviewer_approve_rate_max,
            median_time_min_sec=th.alerts.reviewer_median_time_min_sec,
            rows=rows,
        )

    def reviewer_counts(
        self, start: datetime, end: datetime, reviewer: str | None
    ) -> dict[str, tuple[int, int, list[float]]]:
        rows = ReviewDecision.objects.filter(decided_at__gte=start, decided_at__lt=end)
        if reviewer:
            rows = rows.filter(reviewer__username=reviewer)
        out: dict[str, tuple[int, int, list[float]]] = {}
        for username, action, seconds in rows.values_list(
            "reviewer__username", "action_taken", "time_spent_sec"
        ):
            n, approved, times = out.get(username, (0, 0, []))
            times.append(float(seconds))
            out[username] = (n + 1, approved + (action == "approve"), times)
        return out

    # ── KB (UC-F10-04) ──

    def kb(self, weeks: int) -> KbReport:
        zone = report_zone()
        today = timezone.now().astimezone(zone).date()
        monday = today - timedelta(days=today.weekday())
        refusals = []
        for i in range(weeks - 1, -1, -1):
            start = monday - timedelta(weeks=i)
            period = Period.days(start, start + timedelta(days=6), zone)
            routed = RoutingDecision.objects.filter(
                decided_at__gte=period.start, decided_at__lt=period.end
            )
            refusals.append(
                RefusalWeek(
                    week_start=start,
                    decisions=routed.count(),
                    refused=routed.filter(reason_code=ReasonCode.RETRIEVAL_FLOOR.value).count(),
                )
            )
        open_clusters = KbGapCluster.objects.filter(state=GapState.OPEN.value)
        return KbReport(
            weeks=weeks,
            refusals=refusals,
            open_clusters=open_clusters.count(),
            open_by_label=dict(Counter(open_clusters.values_list("label", flat=True))),
            closures=self.gap_closures(),
            graph=kb_graph.health(local(monday - timedelta(weeks=weeks - 1), zone)),
        )

    def gap_closures(self) -> list[GapClosure]:
        """Clusters whose drafted page was published: matching refusals in the weeks after
        publication against the weeks before (BR-F10-07)."""
        th = settings.THRESHOLDS
        span = timedelta(weeks=th.reports.gap_closure_weeks)
        now = timezone.now()
        out = []
        for draft in (
            KbDraft.objects.filter(
                state=DraftState.PUBLISHED.value,
                gap_cluster__isnull=False,
                published_at__isnull=False,
            )
            .select_related("gap_cluster", "article")
            .order_by("-published_at")
        ):
            cluster = draft.gap_cluster
            assert cluster is not None and draft.published_at is not None
            if cluster.centroid is None:
                continue
            centroid = unit(cluster.centroid)
            published = draft.published_at
            out.append(
                GapClosure(
                    cluster_id=cluster.id,
                    label=cluster.label,
                    size=cluster.size,
                    article_slug=draft.article.slug if draft.article else None,
                    published_at=published,
                    before=self.matching_refusals(centroid, published - span, published),
                    after=self.matching_refusals(centroid, published, min(published + span, now)),
                    complete=published + span <= now,
                )
            )
        return out

    def matching_refusals(self, centroid: np.ndarray, start: datetime, end: datetime) -> int:
        bar = settings.THRESHOLDS.kb_gaps.cluster_similarity
        if end <= start:
            return 0
        return sum(1 for _, v in kb_gaps.refused(start, end) if float(v @ centroid) >= bar)

    # ── CSAT (UC-F10-05) ──

    def csat(self, viewer: User, *, month: str | None, team: str | None = None) -> CsatReport:
        period = Period.month(month, report_zone())
        teams = self.team_scope(viewer, team)
        rows = self.team_facts(teams)
        teams_seen = sorted(
            {
                t
                for t in rows.filter(
                    resolved_at__gte=period.start, resolved_at__lt=period.end
                ).values_list("team", flat=True)
                if t
            }
        )
        low = settings.THRESHOLDS.requester.low_rating_at_most
        ratings = (
            TicketRating.objects.filter(
                rated_at__gte=period.start,
                rated_at__lt=period.end,
                score__lte=low,
            )
            .exclude(comment_masked="")
            .filter(self.team_tickets(teams, "ticket__"))
            .select_related("ticket__team")
            .order_by("-rated_at")
        )
        return CsatReport(
            month=period.label,
            team=team,
            auto=self.csat_line(rows.filter(auto_replied=True), period),
            person=self.csat_line(rows.filter(auto_replied=False), period),
            by_team=[
                CsatTeam(
                    team=t,
                    auto=self.csat_line(rows.filter(team=t, auto_replied=True), period),
                    person=self.csat_line(rows.filter(team=t, auto_replied=False), period),
                )
                for t in teams_seen
            ],
            low_rated=[
                LowRating(
                    ticket_public_id=r.ticket.public_id,
                    team=r.ticket.team.slug if r.ticket.team else r.ticket.assigned_team,
                    score=r.score,
                    comment=r.comment_masked or "",
                    rated_at=r.rated_at,
                )
                for r in ratings[: settings.THRESHOLDS.reports.list_page_size]
            ],
        )

    def csat_line(self, rows: TicketFactsQuerySet, period: Period) -> CsatLine:
        scores = [
            s
            for s in rows.filter(csat_at__gte=period.start, csat_at__lt=period.end).values_list(
                "csat_score", flat=True
            )
            if s is not None
        ]
        counts = Counter(scores)
        return CsatLine(
            ratings=len(scores),
            resolved=rows.filter(resolved_at__gte=period.start, resolved_at__lt=period.end).count(),
            mean=mean(scores) if scores else None,
            distribution={str(s): counts[s] for s in range(1, 6)},
        )

    # ── rollout (UC-F10-06) ──

    def automation(self, start: datetime, end: datetime) -> Automation:
        """Live counts automation carried out; would-have counts every automation the router
        chose, live or shadow (BR-F10-09)."""
        routed = RoutingDecision.objects.filter(decided_at__gte=start, decided_at__lt=end)
        automated = routed.filter(branch__in=AUTOMATED_BRANCHES)
        return Automation(
            total=routed.count(),
            live=automated.filter(shadow_mode=False).count(),
            would_have=automated.count(),
        )

    def rollout(self, days: int) -> RolloutReport:
        period = Period.last_days(days)
        snapshot = rollout.snapshot()
        routed = RoutingDecision.objects.filter(
            decided_at__gte=period.start, decided_at__lt=period.end
        )
        total = routed.count()
        shadow = dict(
            routed.filter(shadow_mode=True)
            .values_list("branch")
            .annotate(n=Count("id"))
            .values_list("branch", "n")
        )
        branches = []
        for branch in FlagBranch:
            flag = rollout.flag(branch.value)
            decision_branch = AGREEMENT_BRANCH[branch]
            branches.append(
                BranchReadiness(
                    branch=branch.value,
                    decision_branch=decision_branch,
                    live=rollout.is_live(branch, snapshot),
                    agreement=rollout_metrics.shadow_agreement(decision_branch, days),
                    shadow_decisions=shadow.get(decision_branch, 0),
                    gates=rollout_metrics.snapshot(branch, rollout.entered_on(flag)),
                    total_decisions=total,
                )
            )
        return RolloutReport(
            days=days, branches=branches, automation=self.automation(period.start, period.end)
        )

    # ── security (UC-F10-07) ──

    def security(self, viewer: User, month: str | None) -> SecurityReport:
        """Counts by kind for a manager; acknowledgement times and false positives for security
        only (BR-F8-01)."""
        period = Period.month(month, report_zone())
        alerts = SecurityAlert.objects.filter(
            first_seen_at__gte=period.start, first_seen_at__lt=period.end
        )
        by_kind = {
            row["kind"]: row
            for row in alerts.values("kind").annotate(
                n=Count("id"), open=Count("id", filter=Q(closed_at__isnull=True))
            )
        }
        kinds = [
            SecurityKind(k.value, by_kind[k.value]["n"], by_kind[k.value]["open"])
            for k in AlertKind
            if k.value in by_kind
        ]
        report = SecurityReport(
            month=period.label, detail=False, total=alerts.count(), by_kind=kinds
        )
        if viewer.role != UserRole.SECURITY.value:
            return report
        acked = list(
            alerts.filter(acknowledged_at__isnull=False).values_list(
                "first_seen_at", "acknowledged_at", "ack_due_at"
            )
        )
        times = seconds_between([(a, b) for a, b, _ in acked])
        report.detail = True
        report.ack_p50_sec = percentile(times, 0.5)
        report.ack_p90_sec = percentile(times, 0.9)
        report.acknowledged = len(acked)
        report.ack_in_target = sum(1 for _, at, due in acked if at is not None and at <= due)
        resolved = alerts.exclude(resolution__isnull=True).exclude(resolution="")
        report.closed = resolved.count()
        report.false_positive = resolved.filter(resolution=Resolution.FALSE_POSITIVE.value).count()
        return report

    # ── incidents (UC-F10-07) ──

    def incidents(self, month: str | None) -> IncidentReport:
        period = Period.month(month, report_zone())
        incidents = Incident.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
        confirmed = incidents.filter(confirmed_at__isnull=False)
        first_broadcast = {
            row["incident"]: row["first"]
            for row in IncidentBroadcast.objects.filter(incident__in=confirmed)
            .values("incident")
            .annotate(first=Min("sent_at"))
        }
        to_broadcast = seconds_between(
            [(i.confirmed_at, first_broadcast.get(i.id)) for i in confirmed]
        )
        links = IncidentLink.objects.filter(linked_at__gte=period.start, linked_at__lt=period.end)
        return IncidentReport(
            month=period.label,
            detected=incidents.count(),
            confirmed=confirmed.count(),
            dismissed=incidents.filter(status=IncidentStatus.DISMISSED.value).count(),
            linked_tickets=links.filter(unlinked_at__isnull=True)
            .values("ticket")
            .distinct()
            .count(),
            links_created=links.count(),
            links_unlinked=links.filter(unlinked_at__isnull=False).count(),
            confirm_p50_sec=percentile(
                seconds_between([(i.created_at, i.confirmed_at) for i in confirmed]), 0.5
            ),
            first_broadcast_p50_sec=percentile(to_broadcast, 0.5),
            first_broadcast_p90_sec=percentile(to_broadcast, 0.9),
        )

    # ── notifications (FR-F10-012) ──

    def notifications(self, days: int) -> NotificationReport:
        period = Period.last_days(days)
        messages = Message.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
        rows = []
        for channel in Channel:
            mine = messages.filter(channel=channel.value)
            delivered = list(
                mine.filter(state=MessageState.DELIVERED.value).values_list(
                    "created_at", "delivered_at"
                )
            )
            rows.append(
                ChannelRow(
                    channel=channel.value,
                    messages=mine.count(),
                    delivered=len(delivered),
                    failed=mine.filter(state=MessageState.FAILED.value).count(),
                    latency_p95_sec=percentile(seconds_between(delivered), 0.95),
                )
            )
        return NotificationReport(days=days, channels=rows)

    # ── weekly summary (FR-F10-014) ──

    def weekly(self, today: date | None = None) -> WeeklySummary:
        """K1–K7 for the last full week (Monday to Sunday, report zone)."""
        zone = report_zone()
        today = today or timezone.now().astimezone(zone).date()
        monday = today - timedelta(days=today.weekday() + 7)
        period = Period.days(monday, monday + timedelta(days=6), zone)
        rows = TicketFacts.objects.all()
        assigned = rows.filter(
            first_assigned_at__gte=period.start, first_assigned_at__lt=period.end
        )
        minutes = [m for m in assigned.values_list("time_to_assign_business_min", flat=True) if m]
        auto = self.csat_line(rows.filter(auto_replied=True), period)
        person = self.csat_line(rows.filter(auto_replied=False), period)
        auto_resolved = rows.filter(
            auto_replied=True, resolved_at__gte=period.start, resolved_at__lt=period.end
        )
        year, week, _ = monday.isocalendar()
        return WeeklySummary(
            week=f"{year}-{week:02d}",
            response=self.compliance(rows, "response", period),
            resolution=self.compliance(rows, "resolution", period),
            breaches_warned_in_time=self.warned(rows, period),
            time_to_assign_median_min=percentile(minutes, 0.5),
            reassignment_rate=ratio(
                assigned.filter(cross_team_reassign_count__gt=0).count(), assigned.count()
            ),
            csat_auto=auto.mean,
            csat_person=person.mean,
            reopen_rate_after_autoreply=ratio(
                auto_resolved.filter(reopened=True).count(), auto_resolved.count()
            ),
        )


# --- the reports ---

reports = Reports()
