import uuid

from django.db.models import QuerySet
from ninja import Header, Router, Status

from apps.accounts.models import Capability, UserRole
from apps.accounts.permissions import (
    TECHNICIAN_OR_MANAGER,
    AuthedRequest,
    SessionAuth,
    require_access,
    require_role,
)
from apps.itsm_mock.models import ExecutionState, Runbook, RunbookExecution
from apps.itsm_mock.request_schema import (
    CallbackIn,
    ExecuteIn,
    ExecutionResolveIn,
    RunbookChangeIn,
    RunbookIn,
)
from apps.itsm_mock.response_schema import RunbookExecutionOut, RunbookOut, RunbookPanelOut
from apps.itsm_mock.utils.executors import RunbookError, RunbookRefusal
from apps.itsm_mock.utils.runbooks import RunbookPanel, runbooks

router = Router(tags=["itsm"])

# ── the catalog ──


@router.get("/runbooks", auth=SessionAuth(), response=list[RunbookOut])
@require_access(roles=TECHNICIAN_OR_MANAGER, capabilities=(Capability.WORKFLOW_ADMIN,))
def list_runbooks(request: AuthedRequest) -> QuerySet[Runbook]:
    return Runbook.objects.select_related("approved_by", "drafted_by")


@router.post("/runbooks", auth=SessionAuth(), response={201: RunbookOut})
@require_access(capabilities=(Capability.WORKFLOW_ADMIN,))
def create_runbook(request: AuthedRequest, payload: RunbookIn) -> Status[Runbook]:
    return Status(201, runbooks.create(payload.code, payload.fields(), request.auth))


@router.patch("/runbooks/{code}", auth=SessionAuth(), response=RunbookOut)
@require_access(capabilities=(Capability.WORKFLOW_ADMIN,))
def change_runbook(request: AuthedRequest, code: str, payload: RunbookChangeIn) -> Runbook:
    return runbooks.change(code, payload.changes(), request.auth)


@router.post("/runbooks/{code}/approve", auth=SessionAuth(), response=RunbookOut)
@require_role(UserRole.MANAGER)
def approve_runbook(request: AuthedRequest, code: str) -> Runbook:
    return runbooks.approve(code, request.auth)


# ── executions ──


@router.get("/review-items/{item_id}/runbook", auth=SessionAuth(), response=RunbookPanelOut)
@require_role(*TECHNICIAN_OR_MANAGER)
def runbook_panel(request: AuthedRequest, item_id: uuid.UUID) -> RunbookPanel:
    return runbooks.panel(item_id)


@router.post("/review-items/{item_id}/execute", auth=SessionAuth(), response=RunbookExecutionOut)
@require_role(*TECHNICIAN_OR_MANAGER)
def execute(request: AuthedRequest, item_id: uuid.UUID, payload: ExecuteIn) -> RunbookExecution:
    execution = runbooks.execute(item_id, request.auth, payload.payload)
    if execution.state == ExecutionState.AWAITING_SECOND_APPROVAL.value:
        raise RunbookError(
            409,
            RunbookRefusal.SECOND_APPROVAL_REQUIRED,
            "a high-risk runbook runs after a second manager approves it",
            details={"execution": str(execution.id)},
        )
    return execution


@router.post(
    "/executions/{execution_id}/second-approval",
    auth=SessionAuth(),
    response=RunbookExecutionOut,
)
@require_role(UserRole.MANAGER)
def second_approval(request: AuthedRequest, execution_id: uuid.UUID) -> RunbookExecution:
    return runbooks.second_approve(execution_id, request.auth)


@router.post("/executions/{execution_id}/resolve", auth=SessionAuth(), response=RunbookExecutionOut)
@require_role(*TECHNICIAN_OR_MANAGER)
def resolve(
    request: AuthedRequest, execution_id: uuid.UUID, payload: ExecutionResolveIn
) -> RunbookExecution:
    return runbooks.resolve(execution_id, request.auth, ExecutionState(payload.state), payload.note)


@router.post(
    "/executions/{execution_id}/callback",
    auth=None,
    response={204: None},
    url_name="itsm_execution_callback",
)
def callback(
    request: AuthedRequest,
    execution_id: uuid.UUID,
    payload: CallbackIn,
    x_itsm_token: str = Header(...),
) -> Status[None]:
    runbooks.complete_callback(
        execution_id,
        token=x_itsm_token,
        state=ExecutionState(payload.state),
        external_ref=payload.external_ref,
        error=payload.error,
    )
    return Status(204, None)
