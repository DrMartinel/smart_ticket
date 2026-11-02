"""The default subject and body of each notice, per language, and the variables a template may name."""

from __future__ import annotations

from apps.accounts.models import Language
from apps.lifecycle.utils.templates import VARIABLES, placeholders
from apps.notifications.utils.vocabulary import CATALOG, NotificationEvent

# Notice variables on top of the lifecycle's masked ticket and transfer variables.
NOTICE_VARIABLES: dict[str, str] = {
    "notice.event": "The event's label",
    "notice.actor": "Who caused the event: a username, or 'system'",
    "notice.reason": "A reason code, e.g. a security alert's",
    "notice.detail": "Extra detail the event carries, never quarantined PII",
    "notice.message": "A message the event carries, e.g. an approval's question",
    "notice.previousAssignee": "The assignee before a reassignment",
    "notice.link": "The page the notice opens",
}

TEMPLATE_VARIABLES: dict[str, str] = {**VARIABLES, **NOTICE_VARIABLES}

E = NotificationEvent
VI, EN = Language.VI, Language.EN

# (subject, body) per event and language; in-app and email share them unless overridden.
DEFAULTS: dict[NotificationEvent, dict[Language, tuple[str, str]]] = {
    E.TICKET_ASSIGNED: {
        VI: ("Bạn được giao {{ticket.id}}: {{ticket.subject}}", "{{ticket.body}}"),
        EN: ("Assigned to you: {{ticket.id}} — {{ticket.subject}}", "{{ticket.body}}"),
    },
    E.TICKET_REASSIGNED: {
        VI: (
            "{{ticket.id}} được giao lại cho {{ticket.assignee}}: {{ticket.subject}}",
            "Trước đó: {{notice.previousAssignee}}. Người giao: {{notice.actor}}. "
            "Lý do: {{notice.reason}} {{notice.detail}}\n\n{{ticket.body}}",
        ),
        EN: (
            "{{ticket.id}} reassigned to {{ticket.assignee}}: {{ticket.subject}}",
            "Previously: {{notice.previousAssignee}}. By: {{notice.actor}}. "
            "Reason: {{notice.reason}} {{notice.detail}}\n\n{{ticket.body}}",
        ),
    },
    E.TICKET_UNASSIGNED: {
        VI: (
            "{{ticket.id}} chưa có người xử lý: {{ticket.subject}}",
            "Đang chờ trong hàng đợi của nhóm {{ticket.assignedTeam}}. "
            "Người nhận trước: {{notice.previousAssignee}}.",
        ),
        EN: (
            "{{ticket.id}} has no assignee: {{ticket.subject}}",
            "Waiting in team {{ticket.assignedTeam}}'s queue. "
            "Previous assignee: {{notice.previousAssignee}}.",
        ),
    },
    E.ASSIGNMENT_FAILED: {
        VI: (
            "Không giao được {{ticket.id}}: {{notice.reason}}",
            "{{notice.detail}}. Yêu cầu đang ở nhóm {{ticket.assignedTeam}}.",
        ),
        EN: (
            "Couldn't assign {{ticket.id}}: {{notice.reason}}",
            "{{notice.detail}}. The ticket is with team {{ticket.assignedTeam}}.",
        ),
    },
    E.SLA_WARNING: {
        VI: (
            "Sắp hết hạn SLA ({{notice.reason}}): {{ticket.id}}",
            "Hạn {{notice.detail}}. {{ticket.subject}}",
        ),
        EN: (
            "SLA due soon ({{notice.reason}}): {{ticket.id}}",
            "Due {{notice.detail}}. {{ticket.subject}}",
        ),
    },
    E.SLA_BREACHED: {
        VI: (
            "Quá hạn SLA ({{notice.reason}}): {{ticket.id}}",
            "Hạn là {{notice.detail}}. {{ticket.subject}}",
        ),
        EN: (
            "SLA breached ({{notice.reason}}): {{ticket.id}}",
            "It was due {{notice.detail}}. {{ticket.subject}}",
        ),
    },
    E.SLA_BREACHED_ESCALATED: {
        VI: (
            "Quá hạn SLA kéo dài ({{notice.reason}}): {{ticket.id}}",
            "Hạn là {{notice.detail}}. Nhóm {{ticket.assignedTeam}}, người xử lý "
            "{{ticket.assignee}}. {{ticket.subject}}",
        ),
        EN: (
            "SLA breach escalated ({{notice.reason}}): {{ticket.id}}",
            "It was due {{notice.detail}}. Team {{ticket.assignedTeam}}, assignee "
            "{{ticket.assignee}}. {{ticket.subject}}",
        ),
    },
    E.SLA_HOLIDAYS_MISSING: {
        VI: (
            "Chưa nhập ngày nghỉ lễ năm {{notice.reason}}",
            "{{notice.detail}}. Hãy nhập lịch nghỉ trước khi hết năm.",
        ),
        EN: (
            "Holidays for {{notice.reason}} not entered",
            "{{notice.detail}}. Enter them before the year ends.",
        ),
    },
    E.APPROVAL_REQUESTED: {
        VI: (
            "Cần bạn phê duyệt {{ticket.id}}: {{ticket.subject}}",
            "{{notice.actor}} đề nghị chuyển sang “{{transfer.afterStatus}}”.\n{{notice.message}}",
        ),
        EN: (
            "Your approval is needed: {{ticket.id}} — {{ticket.subject}}",
            "{{notice.actor}} asks to move it to “{{transfer.afterStatus}}”.\n{{notice.message}}",
        ),
    },
    E.SECURITY_ALERT: {
        VI: ("Cảnh báo bảo mật: {{notice.reason}}", "{{notice.detail}}"),
        EN: ("Security alert: {{notice.reason}}", "{{notice.detail}}"),
    },
    E.IDENTITY_BREAK_GLASS_USED: {
        VI: (
            "Đăng nhập khẩn cấp: {{notice.actor}}",
            "Tài khoản khẩn cấp {{notice.actor}} vừa đăng nhập ({{notice.detail}}).",
        ),
        EN: (
            "Break-glass sign-in: {{notice.actor}}",
            "The break-glass account {{notice.actor}} just signed in ({{notice.detail}}).",
        ),
    },
}


def default_template(event: NotificationEvent, language: Language) -> tuple[str, str]:
    """The built-in subject and body; an event without one names its label and ticket."""
    if event in DEFAULTS:
        return DEFAULTS[event][language]
    spec = CATALOG[event]
    label = spec.label_vi if language is Language.VI else spec.label_en
    return f"{label}: {{{{ticket.id}}}}", "{{ticket.subject}}"


def unknown_variables(*texts: str) -> list[str]:
    """The placeholders in `texts` no notice can fill."""
    return [
        path
        for path in placeholders(list(texts))
        if path not in TEMPLATE_VARIABLES and not path.startswith("field.")
    ]
