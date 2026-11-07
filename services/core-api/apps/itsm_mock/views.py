import uuid

from django.db.models import QuerySet
from ninja import Header, Router, Status

from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AuthedRequest, SessionAuth, require
from apps.itsm_mock.models import ExecutionState, Runbook, RunbookExecution
from apps.itsm_mock.request_schema import (
    CallbackIn,
    ExecuteIn,
    ExecutionResolveIn,
    RunbookChangeIn,
    RunbookIn,
)
from apps.itsm_mock.response_schema import RunbookExecutionOut, RunbookOut, RunbookPanelOut
from apps.itsm_mock.utils.runbooks import RunbookPanel, runbooks

router = Router(tags=["itsm"])

# ── the catalog ──


@router.get("/runbooks", auth=SessionAuth(), response=list[RunbookOut])
@require(Permission.RUNBOOKS_CATALOG_READ)
def list_runbooks(request: AuthedRequest) -> QuerySet[Runbook]:
    return Runbook.objects.select_related("approved_by", "drafted_by")


@router.post("/runbooks", auth=SessionAuth(), response={201: RunbookOut})
@require(Permission.RUNBOOKS_CATALOG_MANAGE)
def create_runbook(request: AuthedRequest, payload: RunbookIn) -> Status[Runbook]:
    return Status(201, runbooks.create(payload.code, payload.fields(), request.auth.user))


@router.patch("/runbooks/{code}", auth=SessionAuth(), response=RunbookOut)
@require(Permission.RUNBOOKS_CATALOG_MANAGE)
def change_runbook(request: AuthedRequest, code: str, payload: RunbookChangeIn) -> Runbook:
    return runbooks.change(code, payload.changes(), request.auth.user)


@router.post("/runbooks/{code}/activate", auth=SessionAuth(), response=RunbookOut)
@require(Permission.RUNBOOKS_CATALOG_ACTIVATE)
def activate_runbook(request: AuthedRequest, code: str) -> Runbook:
    return runbooks.activate(code, request.auth.user)


# ── executions ──


@router.get("/review-items/{item_id}/runbook", auth=SessionAuth(), response=RunbookPanelOut)
@require(Permission.RUNBOOKS_EXECUTE)
def runbook_panel(request: AuthedRequest, item_id: uuid.UUID) -> RunbookPanel:
    return runbooks.panel(item_id)


@router.post("/review-items/{item_id}/execute", auth=SessionAuth(), response=RunbookExecutionOut)
@require(Permission.RUNBOOKS_EXECUTE)
def execute(request: AuthedRequest, item_id: uuid.UUID, payload: ExecuteIn) -> RunbookExecution:
    return runbooks.execute(item_id, request.auth.user, payload.payload)


@router.post("/executions/{execution_id}/resolve", auth=SessionAuth(), response=RunbookExecutionOut)
@require(Permission.RUNBOOKS_EXECUTE)
def resolve(
    request: AuthedRequest, execution_id: uuid.UUID, payload: ExecutionResolveIn
) -> RunbookExecution:
    return runbooks.resolve(
        execution_id, request.auth.user, ExecutionState(payload.state), payload.note
    )


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
