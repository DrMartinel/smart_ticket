"""
Lifecycle endpoints (ADR-0028): workflow configuration, which managers
change, and ticket moves, field values, retries and approvals.
"""

import uuid

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from ninja import Header, Router, Status
from ninja.errors import HttpError

from apps.accounts.models import UserRole
from apps.accounts.permissions import AuthedRequest, SessionAuth, require_role
from apps.lifecycle.models import (
    ApprovalRequest,
    CustomField,
    SystemStatus,
    Transfer,
    Transition,
    Workflow,
    WorkflowStatus,
)
from apps.lifecycle.request_schema import (
    AdoptIn,
    AssignIn,
    ApprovalDecisionIn,
    CallbackIn,
    ChangeWorkflowIn,
    FieldIn,
    FieldPatch,
    FieldValuesIn,
    MoveIn,
    PositionIn,
    ReorderIn,
    StatusIn,
    StatusPatch,
    SystemStatusIn,
    SystemStatusPatch,
    TransitionIn,
    TransitionPatch,
    ValidateFieldsIn,
    WorkflowIn,
    WorkflowPatch,
)
from apps.lifecycle.response_schema import (
    AdoptOut,
    ApprovalOut,
    CatalogOut,
    FieldOut,
    MoveOptionOut,
    StatusOut,
    SystemStatusOut,
    TicketLifecycleOut,
    TransferOut,
    TransitionOut,
    ValidationOut,
    WorkflowDetailOut,
    WorkflowOut,
)
from apps.lifecycle.utils.config import Catalog, workflow_config
from apps.lifecycle.utils.engine import Adoption, lifecycle
from apps.lifecycle.utils.fields import FieldCheck, field_values
from apps.lifecycle.utils.resolver import MoveOption
from apps.tickets.models import Ticket

router = Router(tags=["lifecycle"])

_READ = (UserRole.MANAGER, UserRole.TECHNICIAN)
_MANAGE = (UserRole.MANAGER,)


# ── catalog and system statuses ──


@router.get("/catalog", auth=SessionAuth(), response=CatalogOut)
@require_role(*_READ)
def get_catalog(request: AuthedRequest) -> Catalog:
    return workflow_config.catalog()


@router.get("/system-statuses", auth=SessionAuth(), response=list[SystemStatusOut])
@require_role(*_READ)
def list_system_statuses(request: AuthedRequest) -> QuerySet[SystemStatus]:
    return SystemStatus.objects.all()


@router.post("/system-statuses", auth=SessionAuth(), response={201: SystemStatusOut})
@require_role(*_MANAGE)
def create_system_status(request: AuthedRequest, payload: SystemStatusIn) -> Status[SystemStatus]:
    return Status(201, workflow_config.create_system_status(payload))


@router.post("/system-statuses/reorder", auth=SessionAuth(), response=list[SystemStatusOut])
@require_role(*_MANAGE)
def reorder_system_statuses(request: AuthedRequest, payload: ReorderIn) -> list[SystemStatus]:
    return workflow_config.reorder_system_statuses(payload.ids)


@router.patch("/system-statuses/{status_id}", auth=SessionAuth(), response=SystemStatusOut)
@require_role(*_MANAGE)
def update_system_status(
    request: AuthedRequest, status_id: uuid.UUID, payload: SystemStatusPatch
) -> SystemStatus:
    return workflow_config.update_system_status(
        get_object_or_404(SystemStatus, pk=status_id), payload
    )


@router.delete("/system-statuses/{status_id}", auth=SessionAuth(), response={204: None})
@require_role(*_MANAGE)
def delete_system_status(request: AuthedRequest, status_id: uuid.UUID) -> Status[None]:
    workflow_config.delete_system_status(get_object_or_404(SystemStatus, pk=status_id))
    return Status(204, None)


# ── workflows ──


def _workflow(workflow_id: uuid.UUID) -> Workflow:
    return get_object_or_404(
        Workflow.objects.prefetch_related(
            "statuses__base",
            "statuses__actions",
            "transitions__rules",
            "transitions__actions",
            "fields__rules",
            "fields__events__actions",
        ),
        pk=workflow_id,
    )


@router.get("/workflows", auth=SessionAuth(), response=list[WorkflowOut])
@require_role(*_READ)
def list_workflows(request: AuthedRequest) -> QuerySet[Workflow]:
    return Workflow.objects.all()


@router.post("/workflows", auth=SessionAuth(), response={201: WorkflowDetailOut})
@require_role(*_MANAGE)
def create_workflow(request: AuthedRequest, payload: WorkflowIn) -> Status[Workflow]:
    workflow = workflow_config.create_workflow(payload, actor=request.auth)
    return Status(201, _workflow(workflow.id))


@router.get("/workflows/{workflow_id}", auth=SessionAuth(), response=WorkflowDetailOut)
@require_role(*_READ)
def get_workflow(request: AuthedRequest, workflow_id: uuid.UUID) -> Workflow:
    return _workflow(workflow_id)


@router.patch("/workflows/{workflow_id}", auth=SessionAuth(), response=WorkflowOut)
@require_role(*_MANAGE)
def update_workflow(
    request: AuthedRequest, workflow_id: uuid.UUID, payload: WorkflowPatch
) -> Workflow:
    return workflow_config.update_workflow(
        get_object_or_404(Workflow, pk=workflow_id), payload, actor=request.auth
    )


@router.delete("/workflows/{workflow_id}", auth=SessionAuth(), response={204: None})
@require_role(*_MANAGE)
def delete_workflow(request: AuthedRequest, workflow_id: uuid.UUID) -> Status[None]:
    workflow_config.delete_workflow(get_object_or_404(Workflow, pk=workflow_id), actor=request.auth)
    return Status(204, None)


@router.post("/workflows/{workflow_id}/adopt", auth=SessionAuth(), response=AdoptOut)
@require_role(*_MANAGE)
def adopt_tickets(request: AuthedRequest, workflow_id: uuid.UUID, payload: AdoptIn) -> Adoption:
    return lifecycle.adopt_tickets(
        get_object_or_404(Workflow, pk=payload.source_workflow_id),
        get_object_or_404(Workflow, pk=workflow_id),
        payload.status_mapping,
        actor=request.auth,
    )


# ── statuses ──


def _status(status_id: uuid.UUID) -> WorkflowStatus:
    return get_object_or_404(
        WorkflowStatus.objects.select_related("base", "workflow").prefetch_related("actions"),
        pk=status_id,
    )


@router.post("/workflows/{workflow_id}/statuses", auth=SessionAuth(), response={201: StatusOut})
@require_role(*_MANAGE)
def add_status(
    request: AuthedRequest, workflow_id: uuid.UUID, payload: StatusIn
) -> Status[WorkflowStatus]:
    status = workflow_config.add_status(get_object_or_404(Workflow, pk=workflow_id), payload)
    return Status(201, _status(status.id))


@router.post(
    "/workflows/{workflow_id}/statuses/reorder", auth=SessionAuth(), response=list[StatusOut]
)
@require_role(*_MANAGE)
def reorder_statuses(
    request: AuthedRequest, workflow_id: uuid.UUID, payload: ReorderIn
) -> list[WorkflowStatus]:
    return workflow_config.reorder_statuses(
        get_object_or_404(Workflow, pk=workflow_id), payload.ids
    )


@router.get("/statuses/by-base", auth=SessionAuth(), response=list[StatusOut])
@require_role(*_READ)
def statuses_by_base(
    request: AuthedRequest, system_status_id: uuid.UUID, workflow_id: uuid.UUID
) -> QuerySet[WorkflowStatus]:
    return (
        WorkflowStatus.objects.filter(workflow_id=workflow_id, base_id=system_status_id)
        .select_related("base")
        .prefetch_related("actions")
    )


@router.patch("/statuses/{status_id}", auth=SessionAuth(), response=StatusOut)
@require_role(*_MANAGE)
def update_status(
    request: AuthedRequest, status_id: uuid.UUID, payload: StatusPatch
) -> WorkflowStatus:
    workflow_config.update_status(_status(status_id), payload)
    return _status(status_id)


@router.post("/statuses/{status_id}/position", auth=SessionAuth(), response=StatusOut)
@require_role(*_MANAGE)
def set_status_position(
    request: AuthedRequest, status_id: uuid.UUID, payload: PositionIn
) -> WorkflowStatus:
    return workflow_config.set_position(_status(status_id), payload.x, payload.y)


@router.delete("/statuses/{status_id}", auth=SessionAuth(), response={204: None})
@require_role(*_MANAGE)
def delete_status(
    request: AuthedRequest, status_id: uuid.UUID, migrate_to: uuid.UUID | None = None
) -> Status[None]:
    workflow_config.delete_status(_status(status_id), migrate_to=migrate_to, actor=request.auth)
    return Status(204, None)


# ── transitions ──


def _transition(transition_id: uuid.UUID) -> Transition:
    return get_object_or_404(
        Transition.objects.select_related("workflow", "from_status", "to_status").prefetch_related(
            "rules", "actions"
        ),
        pk=transition_id,
    )


@router.post(
    "/workflows/{workflow_id}/transitions", auth=SessionAuth(), response={201: TransitionOut}
)
@require_role(*_MANAGE)
def add_transition(
    request: AuthedRequest, workflow_id: uuid.UUID, payload: TransitionIn
) -> Status[Transition]:
    transition = workflow_config.add_transition(
        get_object_or_404(Workflow, pk=workflow_id), payload
    )
    return Status(201, _transition(transition.id))


@router.patch("/transitions/{transition_id}", auth=SessionAuth(), response=TransitionOut)
@require_role(*_MANAGE)
def update_transition(
    request: AuthedRequest, transition_id: uuid.UUID, payload: TransitionPatch
) -> Transition:
    workflow_config.update_transition(_transition(transition_id), payload)
    return _transition(transition_id)


@router.delete("/transitions/{transition_id}", auth=SessionAuth(), response={204: None})
@require_role(*_MANAGE)
def delete_transition(request: AuthedRequest, transition_id: uuid.UUID) -> Status[None]:
    _transition(transition_id).delete()
    return Status(204, None)


# ── custom fields ──


def _field(field_id: uuid.UUID) -> CustomField:
    return get_object_or_404(
        CustomField.objects.select_related("workflow").prefetch_related("rules", "events__actions"),
        pk=field_id,
    )


@router.post("/workflows/{workflow_id}/fields", auth=SessionAuth(), response={201: FieldOut})
@require_role(*_MANAGE)
def add_field(
    request: AuthedRequest, workflow_id: uuid.UUID, payload: FieldIn
) -> Status[CustomField]:
    field = workflow_config.add_field(get_object_or_404(Workflow, pk=workflow_id), payload)
    return Status(201, _field(field.id))


@router.post("/fields/validate", auth=SessionAuth(), response=ValidationOut)
@require_role(*_READ)
def validate_fields(request: AuthedRequest, payload: ValidateFieldsIn) -> FieldCheck:
    return field_values.validate(
        get_object_or_404(Workflow, pk=payload.workflow_id), payload.values
    )


@router.patch("/fields/{field_id}", auth=SessionAuth(), response=FieldOut)
@require_role(*_MANAGE)
def update_field(request: AuthedRequest, field_id: uuid.UUID, payload: FieldPatch) -> CustomField:
    workflow_config.update_field(_field(field_id), payload)
    return _field(field_id)


@router.delete("/fields/{field_id}", auth=SessionAuth(), response={204: None})
@require_role(*_MANAGE)
def delete_field(request: AuthedRequest, field_id: uuid.UUID) -> Status[None]:
    workflow_config.delete_field(_field(field_id))
    return Status(204, None)


# ── tickets ──


def _ticket(public_id: str) -> Ticket:
    return get_object_or_404(Ticket, public_id=public_id)


def _lifecycle_of(public_id: str) -> Ticket:
    return get_object_or_404(
        Ticket.objects.select_related("workflow_status").prefetch_related("field_values__field"),
        public_id=public_id,
    )


@router.get("/tickets/{public_id}", auth=SessionAuth(), response=TicketLifecycleOut)
@require_role(*_READ)
def get_ticket_lifecycle(request: AuthedRequest, public_id: str) -> Ticket:
    return _lifecycle_of(public_id)


@router.get("/tickets/{public_id}/transitions", auth=SessionAuth(), response=list[MoveOptionOut])
@require_role(*_READ)
def list_moves(request: AuthedRequest, public_id: str) -> list[MoveOption]:
    return lifecycle.options(_ticket(public_id))


@router.post("/tickets/{public_id}/assign", auth=SessionAuth(), response=TicketLifecycleOut)
@require_role(*_READ)
def assign_ticket(request: AuthedRequest, public_id: str, payload: AssignIn) -> Ticket:
    lifecycle.assign(
        _ticket(public_id).id, username=payload.assignee, team=payload.team, actor=request.auth
    )
    return _lifecycle_of(public_id)


@router.post("/tickets/{public_id}/move", auth=SessionAuth(), response=TicketLifecycleOut)
@require_role(*_READ)
def move_ticket(request: AuthedRequest, public_id: str, payload: MoveIn) -> Ticket:
    if payload.force and not request.auth.is_manager:
        raise HttpError(403, "only a manager may force a move")
    lifecycle.move(
        _ticket(public_id).id,
        payload.status_id,
        actor=request.auth,
        force=payload.force,
        expected_version=payload.expected_version,
    )
    return _lifecycle_of(public_id)


@router.post(
    "/tickets/{public_id}/change-workflow", auth=SessionAuth(), response=TicketLifecycleOut
)
@require_role(*_MANAGE)
def change_ticket_workflow(
    request: AuthedRequest, public_id: str, payload: ChangeWorkflowIn
) -> Ticket:
    lifecycle.change_workflow(_ticket(public_id).id, payload.status_id, actor=request.auth)
    return _lifecycle_of(public_id)


@router.put("/tickets/{public_id}/fields", auth=SessionAuth(), response=TicketLifecycleOut)
@require_role(*_READ)
def write_fields(request: AuthedRequest, public_id: str, payload: FieldValuesIn) -> Ticket:
    field_values.write(_ticket(public_id).id, payload.values, actor=request.auth)
    return _lifecycle_of(public_id)


@router.get("/tickets/{public_id}/transfers", auth=SessionAuth(), response=list[TransferOut])
@require_role(*_READ)
def list_transfers(request: AuthedRequest, public_id: str) -> QuerySet[Transfer]:
    return (
        Transfer.objects.filter(ticket=_ticket(public_id))
        .select_related("ticket", "before_status", "after_status", "actor")
        .prefetch_related("runs")
        .order_by("-created_at")
    )


@router.post("/tickets/{public_id}/retry", auth=SessionAuth(), response=TransferOut)
@require_role(*_READ)
def retry_transfer(request: AuthedRequest, public_id: str) -> Transfer:
    transfer = lifecycle.retry(_ticket(public_id).id, request.auth)
    return (
        Transfer.objects.select_related("ticket", "before_status", "after_status", "actor")
        .prefetch_related("runs")
        .get(pk=transfer.id)
    )


@router.get("/transfers/failed", auth=SessionAuth(), response=list[TransferOut])
@require_role(*_READ)
def failed_transfers(request: AuthedRequest) -> QuerySet[Transfer]:
    return Transfer.objects.failed_queue().prefetch_related("runs")


# ── answers from outside ──


@router.post(
    "/action-runs/{run_id}/callback",
    auth=None,
    response={204: None},
    url_name="lifecycle_run_callback",
)
def run_callback(
    request: AuthedRequest,
    run_id: uuid.UUID,
    payload: CallbackIn,
    x_lifecycle_token: str = Header(...),
) -> Status[None]:
    lifecycle.complete_callback(
        run_id,
        token=x_lifecycle_token,
        success=payload.success,
        message=payload.message,
        output=payload.output,
    )
    return Status(204, None)


@router.get("/approvals/mine", auth=SessionAuth(), response=list[ApprovalOut])
@require_role(*UserRole)
def my_approvals(request: AuthedRequest) -> QuerySet[ApprovalRequest]:
    return ApprovalRequest.objects.pending_for(request.auth)


@router.post("/approvals/{approval_id}/approve", auth=SessionAuth(), response=ApprovalOut)
@require_role(*UserRole)
def approve(
    request: AuthedRequest, approval_id: uuid.UUID, payload: ApprovalDecisionIn
) -> ApprovalRequest:
    return lifecycle.decide_approval(
        approval_id, user=request.auth, approve=True, comment=payload.comment
    )


@router.post("/approvals/{approval_id}/reject", auth=SessionAuth(), response=ApprovalOut)
@require_role(*UserRole)
def reject(
    request: AuthedRequest, approval_id: uuid.UUID, payload: ApprovalDecisionIn
) -> ApprovalRequest:
    return lifecycle.decide_approval(
        approval_id, user=request.auth, approve=False, comment=payload.comment
    )
