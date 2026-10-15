"""The ticket lifecycle's states, triggers and failure codes (ADR-0028)."""

from __future__ import annotations

from enum import StrEnum


class PipelineStatus(StrEnum):
    """The statuses the triage pipeline moves a ticket into, reserved in every workflow."""

    NEW = "new"
    AWAITING_REQUESTER = "awaiting_requester"
    PENDING_REVIEW = "pending_review"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    AUTO_REPLIED = "auto_replied"
    AUTO_ROUTED = "auto_routed"
    REOPENED = "reopened"


# Pipeline statuses that mean the ticket is resolved; every other one means it is not.
COMPLETED_PIPELINE_STATUSES = frozenset({PipelineStatus.AUTO_REPLIED})

# Statuses where the pipeline or the requester owns the ticket: no person moves it out.
TRIAGE_STATUSES = frozenset({PipelineStatus.NEW, PipelineStatus.AWAITING_REQUESTER})


class TransitionPolicy(StrEnum):
    STRICT = "strict"
    OPEN = "open"


class Trigger(StrEnum):
    """Who or what asked for a status change."""

    CREATE = "create"
    MANUAL = "manual"
    ACTION = "action"
    SYSTEM = "system"
    FORCE = "force"


# Triggers whose moves are a person's or an action's, held to the workflow.
GOVERNED_TRIGGERS = frozenset({Trigger.MANUAL, Trigger.ACTION, Trigger.FORCE})


class TransferState(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


OPEN_TRANSFER_STATES = (TransferState.PENDING, TransferState.COMMITTED)


class Direction(StrEnum):
    FORWARD = "forward"
    REVERSE = "reverse"


class Position(StrEnum):
    """When a transition's action runs relative to the status change."""

    BEFORE = "before"
    AFTER = "after"
    BOTH = "both"


class Phase(StrEnum):
    """The stage of a transfer or field event an action run belongs to, in run order."""

    BEFORE = "before"
    ENTER = "enter"
    AFTER = "after"
    EVENT = "event"


TRANSFER_PHASES = (Phase.BEFORE, Phase.ENTER, Phase.AFTER)


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


DONE_RUN_STATES = (RunState.SUCCEEDED, RunState.SKIPPED)


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FailureCode(StrEnum):
    """Why a transfer, action run or request failed: the failed-transfer queue groups by it."""

    STATUS_NOT_IN_WORKFLOW = "status_not_in_workflow"
    PIPELINE_STATUS_TARGET = "pipeline_status_target"
    PIPELINE_STATUS_LOCKED = "pipeline_status_locked"
    TICKET_IN_TRIAGE = "ticket_in_triage"
    TRANSITION_NOT_ALLOWED = "transition_not_allowed"
    TRANSITION_EXISTS = "transition_exists"
    RULE_VIOLATION = "rule_violation"
    TICKET_TRANSFORMING = "ticket_transforming"
    VERSION_CONFLICT = "version_conflict"
    STATUS_IN_USE = "status_in_use"
    WORKFLOW_IN_USE = "workflow_in_use"
    FIELD_IN_USE = "field_in_use"
    SYSTEM_STATUS_IN_USE = "system_status_in_use"
    UNMAPPED_STATUSES = "unmapped_statuses"
    INVALID_CONFIG = "invalid_config"
    NAME_TAKEN = "name_taken"
    CONFLICT = "conflict"
    INVALID_FIELD_VALUE = "invalid_field_value"
    NOTHING_TO_RETRY = "nothing_to_retry"
    TRANSFER_IN_PROGRESS = "transfer_in_progress"
    NOT_FOUND = "not_found"
    SAME_WORKFLOW = "same_workflow"
    SELF_APPROVAL = "self_approval"
    STALE_TRANSFER = "stale_transfer"
    NOT_AN_APPROVER = "not_an_approver"
    NOT_AWAITING = "not_awaiting"
    BAD_CALLBACK_TOKEN = "bad_callback_token"
    INVALID_PARAM = "invalid_param"
    ACTION_FAILED = "action_failed"
    ACTION_CRASHED = "action_crashed"
    ACTION_ABORTED = "action_aborted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    CALLBACK_FAILED = "callback_failed"
    CALLBACK_TIMEOUT = "callback_timeout"
    RUN_TIMEOUT = "run_timeout"
    AUTOMATION_DEPTH_EXCEEDED = "automation_depth_exceeded"
    SUPERSEDED_BY_PIPELINE = "superseded_by_pipeline"
    WEBHOOK_HOST_REFUSED = "webhook_host_refused"


class ActionCode(StrEnum):
    """The actions a status, transition or field event can run."""

    SET_FIELD = "set_field"
    CLEAR_FIELD = "clear_field"
    ASSIGN_USER = "assign_user"
    ASSIGN_TEAM = "assign_team"
    SET_SLA = "set_sla"
    MOVE_STATUS = "move_status"
    CHANGE_WORKFLOW = "change_workflow"
    SEND_EMAIL = "send_email"
    CALL_WEBHOOK = "call_webhook"
    TRIGGER_N8N = "trigger_n8n"
    REQUIRE_APPROVAL = "require_approval"
