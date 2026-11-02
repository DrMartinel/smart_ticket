"""The action catalog: what each `ActionCode` does when a run executes it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import PydanticUndefined

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.lifecycle.models import ActionRun, ApprovalRequest, Transfer, Workflow, WorkflowStatus
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.rules import FieldType, accepts, coerce
from apps.lifecycle.utils.templates import (
    VARIABLES,
    has_placeholder,
    json_template_errors,
    placeholders,
)
from apps.notifications.utils.notifier import Notice, notifier
from apps.teams.models import Team
from apps.teams.utils.assignment import assignment
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.lifecycle.utils.vocabulary import (
    ActionCode,
    ApprovalState,
    FailureCode,
    Phase,
    Trigger,
)
from infrastructure.outbound import OutboundRefused, OutboundUnavailable, outbound

if TYPE_CHECKING:
    from apps.tickets.models import Ticket


class RetryableActionError(Exception):
    """A transient failure: callers retry the run until `lifecycle.action_max_attempts`."""


class ActionError(Exception):
    """A permanent failure: callers fail the run at once."""

    def __init__(self, code: FailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActionContext:
    """What a handler acts on."""

    run: ActionRun
    ticket: Ticket
    transfer: Transfer | None
    workflow: Workflow


@dataclass(frozen=True)
class ActionResult:
    """A handler's outcome: done, aborting its transfer, or waiting for a callback until a time."""

    output: dict[str, Any] = field(default_factory=dict)
    abort: str | None = None
    awaiting_until: datetime | None = None


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


def widget(kind: str, description: str, default: Any = PydanticUndefined) -> Any:
    """A parameter field rendered as `kind` in the admin UI."""
    return Field(default, description=description, json_schema_extra={"widget": kind})


class ActionHandler:
    """One action in the catalog."""

    code: ClassVar[ActionCode]
    name: ClassVar[str]
    description: ClassVar[str]
    params_model: ClassVar[type[Params]]
    # Blocking actions may run before the status changes, and abort the move.
    blocking: ClassVar[bool] = False
    phases: ClassVar[frozenset[Phase]] = frozenset({Phase.ENTER, Phase.AFTER, Phase.EVENT})
    # Parameters holding a JSON template, filled inside its string values only.
    json_params: ClassVar[frozenset[str]] = frozenset()

    def execute(self, params: Any, ctx: ActionContext) -> ActionResult:
        raise NotImplementedError

    def config_fields(self) -> list[dict[str, Any]]:
        """The parameters the admin UI asks for."""
        return [
            {
                "name": name,
                "description": info.description or "",
                "type": (info.json_schema_extra or {}).get("widget", "text")
                if isinstance(info.json_schema_extra, dict)
                else "text",
                "required": info.is_required(),
            }
            for name, info in self.params_model.model_fields.items()
        ]

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        """What is wrong with `params` as saved configuration, placeholders allowed."""
        model_fields = self.params_model.model_fields
        errors = [f"unknown parameter {name!r}" for name in params if name not in model_fields]
        errors += [
            f"parameter {name!r} is required"
            for name, info in model_fields.items()
            if info.is_required() and params.get(name) in (None, "")
        ]
        fields = set(workflow.fields.values_list("name", flat=True))
        for path in placeholders(params):
            known = path in VARIABLES or (
                path.startswith("field.") and path.removeprefix("field.") in fields
            )
            if not known:
                errors.append(f"unknown placeholder {{{{{path}}}}}")
        for name in self.json_params:
            errors += [f"{name}: {e}" for e in json_template_errors(params.get(name))]
        if errors or any(has_placeholder(v) for v in params.values()):
            return errors
        try:
            self.params_model.model_validate(params)
        except ValidationError as e:
            return [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        return []

    def parse(self, params: dict[str, Any]) -> Any:
        """The run's resolved parameters; raises `ActionError(INVALID_PARAM)` when they don't fit."""
        try:
            return self.params_model.model_validate(params)
        except ValidationError as e:
            raise ActionError(FailureCode.INVALID_PARAM, str(e)) from e


def _check_depth(ctx: ActionContext) -> int:
    depth = ctx.run.depth + 1
    if depth > settings.THRESHOLDS.lifecycle.max_chain_depth:
        raise ActionError(
            FailureCode.AUTOMATION_DEPTH_EXCEEDED,
            f"automation chain deeper than {settings.THRESHOLDS.lifecycle.max_chain_depth}",
        )
    return depth


def _in_open_transfer(ctx: ActionContext) -> bool:
    return ctx.transfer is not None and ctx.transfer.is_open


class SetFieldParams(Params):
    field: str = widget("customfield", "The custom field's name")
    value: Any = widget("text", "The value; placeholders allowed")


class SetField(ActionHandler):
    code = ActionCode.SET_FIELD
    name = "Set custom field"
    description = "Writes a custom field, applying its rules and firing its events."
    params_model: ClassVar[type[Params]] = SetFieldParams

    def execute(self, params: SetFieldParams, ctx: ActionContext) -> ActionResult:
        from apps.lifecycle.utils.fields import field_values

        depth = _check_depth(ctx)
        try:
            field_values.write_by_name(ctx.ticket, {params.field: params.value}, depth=depth)
        except LifecycleError as e:
            raise ActionError(e.code, e.message) from e
        return ActionResult({"field": params.field})

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        name = params.get("field")
        if not name or has_placeholder(name):
            return errors
        field = workflow.fields.filter(name=name).first()
        if field is None:
            return [*errors, f"no custom field {name!r} in {workflow.name!r}"]
        value = params.get("value")
        if "value" in params and not has_placeholder(value):
            field_type = FieldType(field.field_type)
            value = coerce(field_type, value)
            if not accepts(field_type, value, list(field.options)):
                errors.append(f"{value!r} is not a valid {field_type.value} value for {name!r}")
            elif field_type is FieldType.USER and value and not active_users([value], STAFF):
                errors.append(f"no active staff user {value!r}")
        return errors


class ClearFieldParams(Params):
    field: str = widget("customfield", "The custom field's name")


class ClearField(SetField):
    code = ActionCode.CLEAR_FIELD
    name = "Clear custom field"
    description = "Empties a custom field."
    params_model = ClearFieldParams

    def execute(self, params: Any, ctx: ActionContext) -> ActionResult:
        return super().execute(SetFieldParams(field=params.field, value=None), ctx)


class AssignUserParams(Params):
    username: str = widget("user", "The technician or manager to assign")


class AssignUser(ActionHandler):
    code = ActionCode.ASSIGN_USER
    name = "Assign user"
    description = "Assigns the ticket to a user."
    params_model = AssignUserParams

    def execute(self, params: AssignUserParams, ctx: ActionContext) -> ActionResult:
        found = active_users([params.username], ASSIGNABLE)
        if not found:
            raise ActionError(
                FailureCode.INVALID_PARAM, f"no active technician or manager {params.username!r}"
            )
        user = found[0]
        previous = ctx.ticket.assigned_to
        ctx.ticket.assigned_to = user
        ctx.ticket.save(update_fields=["assigned_to"])
        notifier.assignment_changed(ctx.ticket, previous, "system")
        AuditLog.objects.record(
            "ticket_assigned",
            actor_type="system",
            ticket_id=ctx.ticket.id,
            payload={"assignee": user.username, "action_run": str(ctx.run.id)},
        )
        return ActionResult({"assignee": user.username})

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        name = params.get("username")
        if name and not has_placeholder(name) and not active_users([name], ASSIGNABLE):
            errors.append(f"no active technician or manager {name!r}")
        return errors


class AssignTeamParams(Params):
    team: str = widget("team", "The team's slug")
    pick_member: bool = widget("checkbox", "Also pick a person by the team's strategy", False)


class AssignTeam(ActionHandler):
    code = ActionCode.ASSIGN_TEAM
    name = "Assign team"
    description = "Moves the ticket to a team; optionally picks a person by the team's strategy."
    params_model = AssignTeamParams

    def execute(self, params: AssignTeamParams, ctx: ActionContext) -> ActionResult:
        team = Team.objects.filter(slug=params.team, is_active=True).first()
        if team is None:
            raise ActionError(FailureCode.INVALID_PARAM, f"no active team {params.team!r}")
        assignment.move_to_team(ctx.ticket, team, pick_member=params.pick_member)
        assignee = ctx.ticket.assigned_to
        return ActionResult(
            {"team": team.slug, "assignee": assignee.username if assignee else None}
        )

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        slug = params.get("team")
        if (
            isinstance(slug, str)
            and not has_placeholder(slug)
            and not Team.objects.filter(slug=slug, is_active=True).exists()
        ):
            errors.append(f"no active team {slug!r}")
        return errors


class SetSlaParams(Params):
    offset_hours: float = Field(
        gt=0, le=87600, description="Hours from now", json_schema_extra={"widget": "text"}
    )


class SetSla(ActionHandler):
    code = ActionCode.SET_SLA
    name = "Set SLA"
    description = "Sets the SLA due time to now plus an offset."
    params_model = SetSlaParams

    def execute(self, params: SetSlaParams, ctx: ActionContext) -> ActionResult:
        ctx.ticket.sla_due_at = timezone.now() + timedelta(hours=params.offset_hours)
        ctx.ticket.save(update_fields=["sla_due_at"])
        return ActionResult({"sla_due_at": ctx.ticket.sla_due_at.isoformat()})


class MoveStatusParams(Params):
    status: str = widget("workflowstatus", "The key of a status in this workflow")


class MoveStatus(ActionHandler):
    code = ActionCode.MOVE_STATUS
    name = "Move to status"
    description = "Moves the ticket on, through the workflow's transitions and rules."
    params_model = MoveStatusParams

    def execute(self, params: MoveStatusParams, ctx: ActionContext) -> ActionResult:
        from apps.lifecycle.utils.engine import lifecycle

        depth = _check_depth(ctx)
        target = ctx.workflow.statuses.filter(key=params.status).first()
        if target is None:
            raise ActionError(FailureCode.INVALID_PARAM, f"no status {params.status!r}")
        if ctx.ticket.workflow_status_id == target.id:
            return ActionResult({"skipped": "already there"})
        if _in_open_transfer(ctx):
            return ActionResult({"deferred_move": str(target.id)})
        try:
            transfer = lifecycle.request_move(
                ctx.ticket.id, target.id, actor=None, trigger=Trigger.ACTION, depth=depth
            )
        except LifecycleError as e:
            if e.code is FailureCode.TICKET_TRANSFORMING:
                raise RetryableActionError(e.message) from e
            raise ActionError(e.code, e.message) from e
        return ActionResult({"transfer": str(transfer.id) if transfer else None})

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        key = params.get("status")
        if key and not has_placeholder(key):
            target = workflow.statuses.filter(key=key).first()
            if target is None:
                errors.append(f"no status {key!r} in {workflow.name!r}")
            elif target.is_pipeline:
                errors.append(f"only the triage pipeline moves a ticket into {key!r}")
        return errors


class ChangeWorkflowParams(Params):
    workflow: str = widget("workflow", "The name of the workflow to move the ticket to")
    status: str = widget("workflowstatus", "The key of a status in that workflow")


class ChangeWorkflow(ActionHandler):
    code = ActionCode.CHANGE_WORKFLOW
    name = "Change workflow"
    description = (
        "Moves the ticket to another workflow, carrying over fields of the same name and type."
    )
    params_model = ChangeWorkflowParams
    phases = frozenset({Phase.ENTER, Phase.AFTER, Phase.EVENT})

    def execute(self, params: ChangeWorkflowParams, ctx: ActionContext) -> ActionResult:
        from apps.lifecycle.utils.engine import lifecycle

        target = self.target(params)
        if _in_open_transfer(ctx):
            return ActionResult({"deferred_workflow": str(target.id)})
        try:
            lifecycle.change_workflow(ctx.ticket.id, target.id, actor=None)
        except LifecycleError as e:
            if e.code is FailureCode.TICKET_TRANSFORMING:
                raise RetryableActionError(e.message) from e
            raise ActionError(e.code, e.message) from e
        return ActionResult({"workflow": params.workflow, "status": params.status})

    def target(self, params: ChangeWorkflowParams) -> WorkflowStatus:
        target = (
            WorkflowStatus.objects.select_related("workflow")
            .filter(workflow__name=params.workflow, key=params.status)
            .first()
        )
        if target is None or target.is_pipeline:
            raise ActionError(
                FailureCode.INVALID_PARAM,
                f"no movable status {params.status!r} in workflow {params.workflow!r}",
            )
        return target

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        if (
            errors
            or has_placeholder(params.get("workflow"))
            or has_placeholder(params.get("status"))
        ):
            return errors
        try:
            self.target(ChangeWorkflowParams.model_validate(params))
        except ActionError as e:
            errors.append(str(e))
        return errors


class SendEmailParams(Params):
    to: str = widget("text", "Comma-separated addresses; placeholders allowed")
    subject: str = widget("text", "The subject")
    body: str = widget("textarea", "The plain-text body")


class SendEmail(ActionHandler):
    code = ActionCode.SEND_EMAIL
    name = "Send email"
    description = "Sends a plain-text email."
    params_model = SendEmailParams

    def execute(self, params: SendEmailParams, ctx: ActionContext) -> ActionResult:
        recipients = [a.strip() for a in params.to.split(",") if a.strip()]
        bad = invalid_addresses(recipients)
        if not recipients or bad:
            raise ActionError(FailureCode.INVALID_PARAM, f"invalid recipients: {bad or 'none'}")
        subject = " ".join(params.subject.splitlines())
        try:
            send_mail(subject, params.body, None, recipients, fail_silently=False)
        except OSError as e:
            raise RetryableActionError(str(e)) from e
        return ActionResult({"recipients": len(recipients)})

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        to = params.get("to")
        if isinstance(to, str) and not has_placeholder(to):
            bad = invalid_addresses([a.strip() for a in to.split(",") if a.strip()])
            if bad:
                errors.append(f"invalid recipients: {bad}")
        subject = params.get("subject")
        if isinstance(subject, str) and ("\n" in subject or "\r" in subject):
            errors.append("the subject must be one line")
        return errors


class CallWebhookParams(Params):
    url: str = widget("text", "An http(s) URL on an allowed host")
    method: Literal["POST", "PUT", "PATCH", "GET"] = widget(
        "text", "POST, PUT, PATCH or GET", "POST"
    )
    body: str = widget("textarea", "A JSON body; placeholders allowed", "")


class CallWebhook(ActionHandler):
    code = ActionCode.CALL_WEBHOOK
    name = "Call webhook"
    description = "Calls a URL. Before a move, a 4xx answer stops the move; a 5xx is retried."
    params_model = CallWebhookParams
    blocking = True
    phases = frozenset({Phase.BEFORE, Phase.ENTER, Phase.AFTER, Phase.EVENT})
    json_params = frozenset({"body"})

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        return super().config_errors(params, workflow) + url_errors(params.get("url"))

    def execute(self, params: CallWebhookParams, ctx: ActionContext) -> ActionResult:
        response = _send(params.url, params.method, _json_or_text(params.body))
        if response.ok:
            return ActionResult({"status": response.status})
        message = f"{params.url} answered {response.status}: {response.text[:200]}"
        if response.status >= 500:
            raise RetryableActionError(message)
        if ctx.run.phase == Phase.BEFORE.value:
            return ActionResult({"status": response.status}, abort=message)
        raise ActionError(FailureCode.ACTION_FAILED, message)


class TriggerN8nParams(Params):
    webhook_url: str = widget("text", "The n8n webhook URL, on an allowed host")
    payload: str = widget("textarea", "A JSON payload; placeholders allowed", "")


class TriggerN8n(ActionHandler):
    code = ActionCode.TRIGGER_N8N
    name = "Run n8n workflow"
    description = "Starts an n8n workflow and waits for it to call back."
    params_model = TriggerN8nParams
    blocking = True
    phases = frozenset({Phase.BEFORE, Phase.ENTER, Phase.AFTER, Phase.EVENT})
    json_params = frozenset({"payload"})

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        return super().config_errors(params, workflow) + url_errors(params.get("webhook_url"))

    def execute(self, params: TriggerN8nParams, ctx: ActionContext) -> ActionResult:
        body = {
            "ticketId": ctx.ticket.public_id,
            "transferId": str(ctx.transfer.id) if ctx.transfer else None,
            "actionRunId": str(ctx.run.id),
            "callbackUrl": settings.LIFECYCLE_PUBLIC_BASE_URL.rstrip("/")
            + reverse("api-1.0.0:lifecycle_run_callback", kwargs={"run_id": ctx.run.id}),
            "callbackToken": callback_token(ctx.run),
            "payload": _json_or_text(params.payload),
        }
        response = _send(params.webhook_url, "POST", body)
        if not response.ok:
            message = f"n8n answered {response.status}: {response.text[:200]}"
            if response.status >= 500:
                raise RetryableActionError(message)
            raise ActionError(FailureCode.ACTION_FAILED, message)
        wait = timedelta(seconds=settings.LIFECYCLE_CALLBACK_WAIT_SEC)
        return ActionResult({"status": response.status}, awaiting_until=timezone.now() + wait)


class RequireApprovalParams(Params):
    approvers: str = widget("text", "Comma-separated usernames who may approve")
    message: str = widget("textarea", "What the approvers are asked", "")


class RequireApproval(ActionHandler):
    code = ActionCode.REQUIRE_APPROVAL
    name = "Require approval"
    description = "Holds the move until one of the approvers approves; a rejection stops it."
    params_model = RequireApprovalParams
    blocking = True
    phases = frozenset({Phase.BEFORE})

    def execute(self, params: RequireApprovalParams, ctx: ActionContext) -> ActionResult:
        names = [n.strip() for n in params.approvers.split(",") if n.strip()]
        approvers = active_users(names, STAFF)
        if not approvers:
            raise ActionError(FailureCode.INVALID_PARAM, f"no active staff approver among {names}")
        expires = timezone.now() + timedelta(
            hours=settings.THRESHOLDS.lifecycle.approval_wait_hours
        )
        approval, _ = ApprovalRequest.objects.update_or_create(
            run=ctx.run,
            defaults={
                "approver_ids": [str(u.id) for u in approvers],
                "message": params.message,
                "state": ApprovalState.PENDING.value,
                "expires_at": expires,
                "decided_by": None,
                "decided_at": None,
                "comment": "",
            },
        )
        AuditLog.objects.record(
            "approval_requested",
            actor_type="system",
            ticket_id=ctx.ticket.id,
            payload={"approval": str(approval.id), "approvers": [u.username for u in approvers]},
        )
        requester = ctx.transfer.actor if ctx.transfer else None
        notifier.emit(
            NotificationEvent.APPROVAL_REQUESTED,
            ctx.ticket,
            Notice(
                actor=requester.username if requester else "system",
                message=params.message,
                link=f"/tickets/{ctx.ticket.public_id}?approval={approval.id}",
                approvers=tuple(approvers),
                transfer=ctx.transfer,
                data={"approval": str(approval.id), "approvers": [u.username for u in approvers]},
            ),
            event_id=approval.id,
        )
        return ActionResult({"approval": str(approval.id)}, awaiting_until=expires)

    def config_errors(self, params: dict[str, Any], workflow: Workflow) -> list[str]:
        errors = super().config_errors(params, workflow)
        approvers = params.get("approvers")
        if isinstance(approvers, str) and not has_placeholder(approvers):
            names = [n.strip() for n in approvers.split(",") if n.strip()]
            found = {u.username for u in active_users(names, STAFF)}
            missing = [n for n in names if n not in found]
            if missing:
                errors.append(f"not active staff users: {missing}")
        return errors


def callback_token(run: ActionRun) -> str:
    """The secret an external system returns to finish `run`'s current attempt."""
    started = run.started_at.isoformat() if run.started_at else ""
    return salted_hmac("lifecycle.callback", f"{run.id}:{run.attempt}:{started}").hexdigest()


# Who may approve a move, and who may be assigned a ticket.
STAFF = (UserRole.TECHNICIAN, UserRole.MANAGER, UserRole.SECURITY)
ASSIGNABLE = (UserRole.TECHNICIAN, UserRole.MANAGER)


def active_users(names: list[str], roles: tuple[UserRole, ...]) -> list[User]:
    """The active users among `names` with one of `roles`."""
    return list(
        User.objects.filter(username__in=names, is_active=True, role__in=[r.value for r in roles])
    )


def url_errors(url: Any) -> list[str]:
    """Why a webhook URL that names no placeholder can never be called."""
    if not isinstance(url, str) or has_placeholder(url):
        return []
    try:
        outbound.check_url(url)
    except OutboundRefused as e:
        return [str(e)]
    return []


def invalid_addresses(addresses: list[str]) -> list[str]:
    """The entries of `addresses` that are not email addresses."""
    bad = []
    for address in addresses:
        try:
            validate_email(address)
        except DjangoValidationError:
            bad.append(address)
    return bad


def _json_or_text(body: str) -> Any:
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError:
        return body


def _send(url: str, method: str, body: Any) -> Any:
    try:
        return outbound.send(url, method=method, json_body=body)
    except OutboundRefused as e:
        raise ActionError(FailureCode.WEBHOOK_HOST_REFUSED, str(e)) from e
    except OutboundUnavailable as e:
        raise RetryableActionError(str(e)) from e


# --- the catalog ---

HANDLERS: dict[ActionCode, ActionHandler] = {
    handler.code: handler
    for handler in [
        SetField(),
        ClearField(),
        AssignUser(),
        AssignTeam(),
        SetSla(),
        MoveStatus(),
        ChangeWorkflow(),
        SendEmail(),
        CallWebhook(),
        TriggerN8n(),
        RequireApproval(),
    ]
}
