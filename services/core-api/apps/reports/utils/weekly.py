"""The Monday summary email to managers (FR-F10-014): one `report.weekly` event per ISO week."""

from __future__ import annotations

import uuid
from datetime import date

from apps.audit.models import AuditLog
from apps.notifications.models import Message
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.reports.utils.reports import WeeklySummary, reports


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


def number(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


class WeeklyReport:
    """Builds and sends the week's K1–K7 summary."""

    def event_id(self, week: str) -> uuid.UUID:
        """The same id for every send of one week, so a retry writes no second message."""
        return uuid.uuid5(uuid.NAMESPACE_URL, f"report:{week}")

    def body(self, s: WeeklySummary) -> str:
        w = s.breaches_warned_in_time
        return "\n".join(
            [
                f"K1 Phản hồi đúng SLA · Response SLA: {percent(s.response.compliance)}"
                f" ({s.response.met}/{s.response.met + s.response.breached})",
                f"K2 Giải quyết đúng SLA · Resolution SLA: {percent(s.resolution.compliance)}"
                f" ({s.resolution.met}/{s.resolution.met + s.resolution.breached})",
                f"K3 Cảnh báo trước khi trễ · Breaches warned in time: {percent(w.rate)}"
                f" ({w.warned}/{w.breached})",
                f"K4 Thời gian giao việc (trung vị, phút làm việc) · Time to assign: "
                f"{number(s.time_to_assign_median_min)}",
                f"K5 Tỷ lệ chuyển nhóm · Reassignment rate: {percent(s.reassignment_rate)}",
                f"K6 CSAT tự động / nhân viên · auto / person: {number(s.csat_auto)} / "
                f"{number(s.csat_person)}",
                f"K7 Mở lại sau trả lời tự động · Reopen after auto-reply: "
                f"{percent(s.reopen_rate_after_autoreply)}",
            ]
        )

    def send(self, today: date | None = None) -> bool:
        """Emits the last full week's summary; False when this week's was already sent."""
        summary = reports.weekly(today)
        event_id = self.event_id(summary.week)
        if Message.objects.filter(event_id=event_id).exists():
            return False
        messages = notifier.emit(
            NotificationEvent.REPORT_WEEKLY,
            notice=Notice(
                reason=summary.week,
                message=self.body(summary),
                link="/admin/dashboard",
                data={"week": summary.week},
            ),
            event_id=event_id,
        )
        if not messages:
            return False
        AuditLog.objects.record(
            "report_weekly_sent",
            actor_type="system",
            payload={"week": summary.week, "messages": len(messages)},
        )
        return True


# --- the weekly report ---

weekly_report = WeeklyReport()
