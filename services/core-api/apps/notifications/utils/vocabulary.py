"""The notification catalog: events, recipient kinds, channels, states and refusal codes (ADR-0033)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Channel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"


# Channels a matrix cell and a preference can name; webhooks go by subscription.
PERSON_CHANNELS = (Channel.IN_APP, Channel.EMAIL)


class RecipientKind(StrEnum):
    REQUESTER = "requester"
    ASSIGNEE = "assignee"
    TEAM_LEAD = "team_lead"
    TEAM_MEMBERS = "team_members"
    MANAGER = "manager"
    SECURITY = "security"
    WORKFLOW_ADMINS = "workflow_admins"
    KB_EDITORS = "kb_editors"
    INCIDENT_MANAGERS = "incident_managers"
    APPROVER = "approver"
    LINKED_REQUESTERS = "linked_requesters"
    PREVIOUS_ASSIGNEE = "previous_assignee"


# Kinds whose notices open in the chat app rather than the admin console.
REQUESTER_KINDS = frozenset({RecipientKind.REQUESTER, RecipientKind.LINKED_REQUESTERS})


class MessageState(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationEvent(StrEnum):
    TICKET_RECEIVED = "ticket.received"
    TICKET_ASSIGNED = "ticket.assigned"
    TICKET_REASSIGNED = "ticket.reassigned"
    TICKET_UNASSIGNED = "ticket.unassigned"
    TICKET_PUBLIC_COMMENT = "ticket.public_comment"
    TICKET_REQUESTER_REPLIED = "ticket.requester_replied"
    TICKET_STATUS_CHANGED = "ticket.status_changed"
    TICKET_RESOLVED = "ticket.resolved"
    TICKET_REOPENED = "ticket.reopened"
    TICKET_RATED_LOW = "ticket.rated_low"
    SLA_WARNING = "sla.warning"
    SLA_BREACHED = "sla.breached"
    SLA_BREACHED_ESCALATED = "sla.breached_escalated"
    SLA_HOLIDAYS_MISSING = "sla.holidays_missing"
    ASSIGNMENT_FAILED = "assignment.failed"
    APPROVAL_REQUESTED = "approval.requested"
    SECURITY_ALERT = "security.alert"
    IDENTITY_BREAK_GLASS_USED = "identity.break_glass_used"
    INCIDENT_BROADCAST = "incident.broadcast"
    INCIDENT_PROPOSED = "incident.proposed"
    INCIDENT_SLA_BREACHED = "incident.sla_breached"
    SECURITY_CREDENTIAL_EXPOSED = "security.credential_exposed"
    SECURITY_ACK_OVERDUE = "security.ack_overdue"
    KB_REVIEW_REQUESTED = "kb.review_requested"
    KB_AUTHORITY_NEEDED = "kb.authority_needed"
    KB_GAPS_READY = "kb.gaps_ready"
    ROLLOUT_FLAG_REQUESTED = "rollout.flag_requested"
    ROLLOUT_FLAG_CHANGED = "rollout.flag_changed"
    ROLLOUT_GATE_UNMET = "rollout.gate_unmet"
    THRESHOLDS_CR_PENDING = "thresholds.cr_pending"
    THRESHOLDS_UNAPPROVED = "thresholds.unapproved"
    REPORT_WEEKLY = "report.weekly"


class NotificationRefusal(StrEnum):
    MANDATORY_CELL = "mandatory_cell"
    REASON_REQUIRED = "reason_required"
    UNKNOWN_EVENT = "unknown_event"
    UNKNOWN_VARIABLE = "unknown_variable"
    WEBHOOK_HOST_REFUSED = "webhook_host_refused"
    NOTIFICATION_NOT_FOUND = "notification_not_found"
    SUBSCRIPTION_NOT_FOUND = "subscription_not_found"


class FailureReason(StrEnum):
    """Why a message failed, at the start of its `last_error`."""

    TEMPLATE_ERROR = "template_error"
    NO_ADDRESS = "no_address"
    SEND_FAILED = "send_failed"
    SEND_REFUSED = "send_refused"


@dataclass(frozen=True)
class Cell:
    """A default recipient and channel of an event; a mandatory one can't be turned off."""

    kind: RecipientKind
    channel: Channel
    mandatory: bool = False


@dataclass(frozen=True)
class EventSpec:
    """One catalog event: the feature that emits it, whether it emits yet, and its cells."""

    owner: str
    active: bool
    label_en: str
    label_vi: str
    cells: tuple[Cell, ...]

    def is_mandatory(self, channel: Channel) -> bool:
        return any(c.mandatory and c.channel is channel for c in self.cells)


def _cells(
    kinds: tuple[RecipientKind, ...],
    channels: tuple[Channel, ...],
    mandatory: tuple[Channel, ...] = (),
) -> tuple[Cell, ...]:
    return tuple(Cell(k, c, c in mandatory) for k in kinds for c in channels)


K = RecipientKind
BOTH = (Channel.IN_APP, Channel.EMAIL)
IN_APP = (Channel.IN_APP,)
E = NotificationEvent

# Spec F4 §f's catalog. Events of features not built yet stay inactive: nothing emits them.
CATALOG: dict[NotificationEvent, EventSpec] = {
    E.TICKET_RECEIVED: EventSpec(
        "F3", False, "Ticket received", "Đã nhận yêu cầu", _cells((K.REQUESTER,), BOTH)
    ),
    E.TICKET_ASSIGNED: EventSpec(
        "F2", True, "Ticket assigned", "Được giao yêu cầu", _cells((K.ASSIGNEE,), BOTH)
    ),
    E.TICKET_REASSIGNED: EventSpec(
        "F2",
        True,
        "Ticket reassigned",
        "Yêu cầu được giao lại",
        _cells((K.ASSIGNEE,), BOTH) + _cells((K.PREVIOUS_ASSIGNEE, K.TEAM_LEAD), IN_APP),
    ),
    E.TICKET_UNASSIGNED: EventSpec(
        "F2", True, "Ticket unassigned", "Yêu cầu chưa có người xử lý", _cells((K.TEAM_LEAD,), BOTH)
    ),
    E.TICKET_PUBLIC_COMMENT: EventSpec(
        "F3",
        False,
        "Reply from support",
        "Phản hồi từ bộ phận hỗ trợ",
        _cells((K.REQUESTER,), BOTH),
    ),
    E.TICKET_REQUESTER_REPLIED: EventSpec(
        "F3", False, "Requester replied", "Người yêu cầu đã trả lời", _cells((K.ASSIGNEE,), BOTH)
    ),
    E.TICKET_STATUS_CHANGED: EventSpec(
        "F3", False, "Status changed", "Trạng thái thay đổi", _cells((K.REQUESTER,), IN_APP)
    ),
    E.TICKET_RESOLVED: EventSpec(
        "F3", False, "Ticket resolved", "Yêu cầu đã được giải quyết", _cells((K.REQUESTER,), BOTH)
    ),
    E.TICKET_REOPENED: EventSpec(
        "F3",
        False,
        "Ticket reopened",
        "Yêu cầu được mở lại",
        _cells((K.ASSIGNEE, K.TEAM_LEAD), IN_APP),
    ),
    E.TICKET_RATED_LOW: EventSpec(
        "F3", False, "Low rating", "Đánh giá thấp", _cells((K.TEAM_LEAD,), BOTH)
    ),
    E.SLA_WARNING: EventSpec(
        "F1",
        False,
        "SLA warning",
        "Cảnh báo SLA",
        _cells((K.ASSIGNEE,), BOTH) + _cells((K.TEAM_LEAD,), IN_APP),
    ),
    E.SLA_BREACHED: EventSpec(
        "F1", False, "SLA breached", "Vi phạm SLA", _cells((K.ASSIGNEE, K.TEAM_LEAD), BOTH)
    ),
    E.SLA_BREACHED_ESCALATED: EventSpec(
        "F1",
        False,
        "SLA breach escalated",
        "Vi phạm SLA được báo cấp trên",
        _cells((K.MANAGER,), BOTH),
    ),
    E.SLA_HOLIDAYS_MISSING: EventSpec(
        "F1",
        False,
        "Holiday calendar missing",
        "Thiếu lịch nghỉ lễ",
        _cells((K.WORKFLOW_ADMINS,), BOTH),
    ),
    E.ASSIGNMENT_FAILED: EventSpec(
        "F2", False, "Assignment failed", "Không giao được yêu cầu", _cells((K.TEAM_LEAD,), IN_APP)
    ),
    E.APPROVAL_REQUESTED: EventSpec(
        "lifecycle",
        True,
        "Approval requested",
        "Cần phê duyệt",
        _cells((K.APPROVER,), BOTH, mandatory=IN_APP),
    ),
    E.SECURITY_ALERT: EventSpec(
        "F5, F13, F8",
        True,
        "Security alert",
        "Cảnh báo bảo mật",
        _cells((K.SECURITY,), BOTH, mandatory=BOTH),
    ),
    E.IDENTITY_BREAK_GLASS_USED: EventSpec(
        "F13",
        True,
        "Break-glass sign-in",
        "Đăng nhập khẩn cấp",
        _cells((K.SECURITY,), BOTH, mandatory=BOTH),
    ),
    E.INCIDENT_BROADCAST: EventSpec(
        "F7",
        False,
        "Incident update",
        "Cập nhật sự cố",
        _cells((K.LINKED_REQUESTERS,), BOTH, mandatory=BOTH),
    ),
    E.INCIDENT_PROPOSED: EventSpec(
        "F7",
        False,
        "Incident proposed",
        "Đề xuất sự cố",
        _cells((K.INCIDENT_MANAGERS,), BOTH, mandatory=BOTH),
    ),
    E.INCIDENT_SLA_BREACHED: EventSpec(
        "F7", False, "Incident SLA breached", "Sự cố vi phạm SLA", _cells((K.MANAGER,), BOTH)
    ),
    E.SECURITY_CREDENTIAL_EXPOSED: EventSpec(
        "F8",
        False,
        "Credential exposed",
        "Lộ thông tin đăng nhập",
        _cells((K.REQUESTER,), BOTH, mandatory=BOTH),
    ),
    E.SECURITY_ACK_OVERDUE: EventSpec(
        "F8",
        False,
        "Security alert unacknowledged",
        "Cảnh báo bảo mật chưa được xác nhận",
        _cells((K.SECURITY,), BOTH, mandatory=BOTH),
    ),
    E.KB_REVIEW_REQUESTED: EventSpec(
        "F6",
        False,
        "KB review requested",
        "Cần duyệt trang KB",
        _cells((K.KB_EDITORS, K.MANAGER), IN_APP),
    ),
    E.KB_AUTHORITY_NEEDED: EventSpec(
        "F6",
        False,
        "KB authority needed",
        "Cần cấp quyền trả lời tự động",
        _cells((K.MANAGER,), BOTH),
    ),
    E.KB_GAPS_READY: EventSpec(
        "F6", False, "KB gaps ready", "Danh sách thiếu KB", _cells((K.KB_EDITORS,), BOTH)
    ),
    E.ROLLOUT_FLAG_REQUESTED: EventSpec(
        "F9",
        False,
        "Rollout change requested",
        "Yêu cầu thay đổi triển khai",
        _cells((K.MANAGER,), BOTH),
    ),
    E.ROLLOUT_FLAG_CHANGED: EventSpec(
        "F9",
        False,
        "Rollout changed",
        "Thay đổi triển khai",
        _cells((K.MANAGER, K.SECURITY), BOTH, mandatory=IN_APP),
    ),
    E.ROLLOUT_GATE_UNMET: EventSpec(
        "F9",
        False,
        "Rollout gate unmet",
        "Chưa đạt điều kiện triển khai",
        _cells((K.MANAGER,), BOTH),
    ),
    E.THRESHOLDS_CR_PENDING: EventSpec(
        "F9",
        False,
        "Threshold change pending",
        "Thay đổi ngưỡng chờ duyệt",
        _cells((K.MANAGER,), IN_APP),
    ),
    E.THRESHOLDS_UNAPPROVED: EventSpec(
        "F9",
        False,
        "Unapproved thresholds",
        "Ngưỡng chưa được duyệt",
        _cells((K.MANAGER, K.SECURITY), BOTH, mandatory=BOTH),
    ),
    E.REPORT_WEEKLY: EventSpec(
        "F10", False, "Weekly report", "Báo cáo tuần", _cells((K.MANAGER,), (Channel.EMAIL,))
    ),
}


def catalog_event(name: str) -> NotificationEvent | None:
    """The catalog event called `name`, or None."""
    try:
        return NotificationEvent(name)
    except ValueError:
        return None
