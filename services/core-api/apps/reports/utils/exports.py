"""Each report as CSV, with the numbers the JSON shows (FR-F10-013); every export is audited."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from typing import Any

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.reports.utils.reports import (
    Compliance,
    CsatLine,
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
)


def compliance_cells(c: Compliance) -> list[Any]:
    return [c.met, c.breached, c.compliance]


def csat_cells(line: CsatLine) -> list[Any]:
    return [
        line.ratings,
        line.resolved,
        line.mean,
        line.response_rate,
        *(line.distribution[str(s)] for s in range(1, 6)),
    ]


class ReportExport:
    """Turns a report into CSV rows and records the export."""

    def write(
        self, viewer: User, report: str, filters: dict[str, Any], rows: Iterable[list[Any]]
    ) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        count = -1
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            count += 1
        AuditLog.objects.record(
            "report_exported",
            actor_type="human",
            actor_id=viewer.id,
            payload={
                "report": report,
                "filters": {k: str(v) for k, v in filters.items() if v is not None},
                "rows": max(count, 0),
            },
        )
        return out.getvalue()

    def sla(self, r: SlaReport) -> Iterable[list[Any]]:
        yield [
            "dimension",
            "key",
            "response_met",
            "response_breached",
            "response_compliance",
            "resolution_met",
            "resolution_breached",
            "resolution_compliance",
        ]
        yield [
            "total",
            r.team or "",
            *compliance_cells(r.response),
            *compliance_cells(r.resolution),
        ]
        for dimension, cells in (
            ("team", r.by_team),
            ("priority", r.by_priority),
            ("category", r.by_category),
        ):
            for c in cells:
                yield [
                    dimension,
                    c.key,
                    *compliance_cells(c.response),
                    *compliance_cells(c.resolution),
                ]
        w = r.breaches_warned_in_time
        yield ["breaches_warned_in_time", "", w.warned, w.breached, w.rate, "", "", ""]
        yield ["excluded", "linked_incident", r.excluded.linked_incident, "", "", "", "", ""]
        yield ["excluded", "no_sla_data", r.excluded.no_sla_data, "", "", "", "", ""]
        yield ["open_overdue_now", "", r.open_overdue_now, "", "", "", "", ""]

    def sla_tickets(self, page: Page) -> Iterable[list[Any]]:
        yield ["ticket", "team", "priority", "category", "state", "met_at", "linked_incident"]
        for t in page.items:
            yield [
                t.public_id,
                t.team,
                t.priority,
                t.category,
                t.state,
                t.met_at.isoformat() if t.met_at else None,
                t.linked_incident,
            ]

    def team(self, r: TeamReport) -> Iterable[list[Any]]:
        yield [
            "username",
            "role",
            "open_now",
            "age_0_1",
            "age_1_3",
            "age_3_5",
            "age_over_5",
            "resolved_in_period",
            "time_to_assign_median_min",
            "time_to_assign_p90_min",
            "reassigned_in",
            "reassigned_out",
        ]
        for m in r.members:
            yield [
                m.username,
                m.role,
                m.open_now,
                *m.age_buckets.values(),
                m.resolved_in_period,
                m.time_to_assign_median_min,
                m.time_to_assign_p90_min,
                m.reassigned_in,
                m.reassigned_out,
            ]
        yield [
            "team",
            r.team,
            r.unassigned_now,
            "",
            "",
            "",
            "",
            r.tickets_assigned,
            r.time_to_assign_median_min,
            r.time_to_assign_p90_min,
            r.tickets_reassigned_cross_team,
            r.reassignment_rate,
        ]

    def reviewers(self, r: ReviewerReport) -> Iterable[list[Any]]:
        yield [
            "reviewer",
            "decisions",
            "approved",
            "approve_rate",
            "median_seconds",
            "previous_approve_rate",
            "flagged",
        ]
        for row in r.rows:
            yield [
                row.username,
                row.decisions,
                row.approved,
                row.approve_rate,
                row.median_seconds,
                row.previous_approve_rate,
                row.flagged,
            ]

    def kb(self, r: KbReport) -> Iterable[list[Any]]:
        yield ["section", "key", "value_1", "value_2", "rate"]
        for w in r.refusals:
            yield ["refusals", w.week_start.isoformat(), w.decisions, w.refused, w.refusal_rate]
        yield ["open_clusters", "", r.open_clusters, "", ""]
        for c in r.closures:
            yield ["gap_closure", c.article_slug or str(c.cluster_id), c.before, c.after, c.closure]

    def csat(self, r: CsatReport) -> Iterable[list[Any]]:
        yield [
            "team",
            "line",
            "ratings",
            "resolved",
            "mean",
            "response_rate",
            "score_1",
            "score_2",
            "score_3",
            "score_4",
            "score_5",
        ]
        yield ["all", "auto", *csat_cells(r.auto)]
        yield ["all", "person", *csat_cells(r.person)]
        for t in r.by_team:
            yield [t.team, "auto", *csat_cells(t.auto)]
            yield [t.team, "person", *csat_cells(t.person)]

    def rollout(self, r: RolloutReport) -> Iterable[list[Any]]:
        yield ["branch", "live", "decided", "agreed", "agreement", "shadow_decisions", "coverage"]
        for b in r.branches:
            yield [
                b.branch,
                b.live,
                b.agreement.decided,
                b.agreement.agreed,
                b.agreement.rate,
                b.shadow_decisions,
                b.coverage,
            ]
        a = r.automation
        yield ["automation_rate_live (not a target)", "", a.total, a.live, a.live_rate, "", ""]
        yield [
            "automation_rate_would_have (not a target)",
            "",
            a.total,
            a.would_have,
            a.would_have_rate,
            "",
            "",
        ]

    def security(self, r: SecurityReport) -> Iterable[list[Any]]:
        yield ["kind", "count", "open"]
        for k in r.by_kind:
            yield [k.kind, k.count, k.open]
        yield ["total", r.total, ""]
        if r.detail:
            yield ["ack_p50_sec", r.ack_p50_sec, ""]
            yield ["ack_p90_sec", r.ack_p90_sec, ""]
            yield ["ack_in_target", r.ack_in_target, r.acknowledged]
            yield ["false_positive_rate", r.false_positive_rate, r.closed]

    def incidents(self, r: IncidentReport) -> Iterable[list[Any]]:
        yield ["metric", "value"]
        for name in (
            "detected",
            "confirmed",
            "dismissed",
            "linked_tickets",
            "links_created",
            "links_unlinked",
            "unlink_rate",
            "confirm_p50_sec",
            "first_broadcast_p50_sec",
            "first_broadcast_p90_sec",
        ):
            yield [name, getattr(r, name)]

    def notifications(self, r: NotificationReport) -> Iterable[list[Any]]:
        yield ["channel", "messages", "delivered", "failed", "latency_p95_sec"]
        for c in r.channels:
            yield [c.channel, c.messages, c.delivered, c.failed, c.latency_p95_sec]


# --- the exporter ---

report_export = ReportExport()
