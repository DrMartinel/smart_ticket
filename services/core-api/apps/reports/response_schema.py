"""Response shapes of the F10 report endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from ninja import Schema


class ComplianceOut(Schema):
    met: int
    breached: int
    compliance: float | None


class WarnedOut(Schema):
    warned: int
    breached: int
    rate: float | None


class SlaCellOut(Schema):
    key: str
    response: ComplianceOut
    resolution: ComplianceOut


class SlaExcludedOut(Schema):
    linked_incident: int
    no_sla_data: int


class SlaReportOut(Schema):
    month: str
    team: str | None
    priority: str | None
    category: str | None
    response: ComplianceOut
    resolution: ComplianceOut
    breaches_warned_in_time: WarnedOut
    excluded: SlaExcludedOut
    open_overdue_now: int
    by_team: list[SlaCellOut]
    by_priority: list[SlaCellOut]
    by_category: list[SlaCellOut]


class SlaTicketOut(Schema):
    id: uuid.UUID
    public_id: str
    subject: str
    team: str | None
    priority: str | None
    category: str | None
    state: str
    met_at: datetime | None
    linked_incident: bool


class SlaTicketPageOut(Schema):
    items: list[SlaTicketOut]
    total: int
    page: int
    page_size: int


class MemberRowOut(Schema):
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


class TeamReportOut(Schema):
    team: str
    start: date
    end: date
    members: list[MemberRowOut]
    tickets_assigned: int
    tickets_reassigned_cross_team: int
    reassignment_rate: float | None
    unassigned_now: int
    time_to_assign_median_min: float | None
    time_to_assign_p90_min: float | None


class ReviewerRowOut(Schema):
    username: str
    decisions: int
    approved: int
    approve_rate: float | None
    median_seconds: float | None
    previous_approve_rate: float | None
    flagged: bool


class ReviewerReportOut(Schema):
    days: int
    min_decisions_for_flag: int
    approve_rate_max: float
    median_time_min_sec: int
    rows: list[ReviewerRowOut]


class RefusalWeekOut(Schema):
    week_start: date
    decisions: int
    refused: int
    refusal_rate: float | None


class GapClosureOut(Schema):
    cluster_id: uuid.UUID
    label: str
    size: int
    article_slug: str | None
    published_at: datetime
    before: int
    after: int
    closure: float | None
    complete: bool


class GraphHealthOut(Schema):
    pages: int
    pages_with_edges: int
    edges: int
    stale_edges: int
    hidden: int
    added: int
    pending_requests: int
    failed_requests: int
    auto_replies: int
    auto_replies_from_expansion: int
    expansion_share: float | None


class KbReportOut(Schema):
    weeks: int
    refusals: list[RefusalWeekOut]
    open_clusters: int
    open_by_label: dict[str, int]
    closures: list[GapClosureOut]
    graph: GraphHealthOut


class CsatLineOut(Schema):
    ratings: int
    resolved: int
    mean: float | None
    response_rate: float | None
    distribution: dict[str, int]


class CsatTeamOut(Schema):
    team: str
    auto: CsatLineOut
    person: CsatLineOut


class LowRatingOut(Schema):
    ticket_public_id: str
    team: str | None
    score: int
    comment: str
    rated_at: datetime


class CsatReportOut(Schema):
    month: str
    team: str | None
    auto: CsatLineOut
    person: CsatLineOut
    by_team: list[CsatTeamOut]
    low_rated: list[LowRatingOut]


class AgreementReportOut(Schema):
    decided: int
    agreed: int
    rerouted: int
    rate: float | None
    reroute_rate: float | None


class GateValueReportOut(Schema):
    metric: str
    comparator: str
    threshold: float
    window_days: int | None
    phase: str
    value: float | None
    met: bool
    entered: bool


class BranchReadinessOut(Schema):
    branch: str
    decision_branch: str
    live: bool
    agreement: AgreementReportOut
    shadow_decisions: int
    total_decisions: int
    coverage: float | None
    gates: list[GateValueReportOut]


class AutomationOut(Schema):
    total: int
    live: int
    would_have: int
    live_rate: float | None
    would_have_rate: float | None


class RolloutReportOut(Schema):
    days: int
    branches: list[BranchReadinessOut]
    automation: AutomationOut


class SecurityKindOut(Schema):
    kind: str
    count: int
    open: int


class SecurityReportOut(Schema):
    month: str
    detail: bool
    total: int
    by_kind: list[SecurityKindOut]
    ack_p50_sec: float | None
    ack_p90_sec: float | None
    ack_in_target: int | None
    acknowledged: int | None
    closed: int | None
    false_positive: int | None
    false_positive_rate: float | None


class IncidentReportOut(Schema):
    month: str
    detected: int
    confirmed: int
    dismissed: int
    linked_tickets: int
    links_created: int
    links_unlinked: int
    unlink_rate: float | None
    confirm_p50_sec: float | None
    first_broadcast_p50_sec: float | None
    first_broadcast_p90_sec: float | None


class ChannelRowOut(Schema):
    channel: str
    messages: int
    delivered: int
    failed: int
    latency_p95_sec: float | None


class NotificationReportOut(Schema):
    days: int
    channels: list[ChannelRowOut]
