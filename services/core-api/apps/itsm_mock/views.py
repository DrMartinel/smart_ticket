import uuid

from ninja import Router
from ninja.errors import HttpError

from apps.itsm_mock.models import RUNBOOK_REGISTRY, Runbook, RunbookError, RunbookExecution
from apps.itsm_mock.response_schema import RunbookExecutionOut, RunbookOut
from apps.review.models import ReviewItem
from apps.accounts.permissions import (
    TECHNICIAN_OR_MANAGER,
    AuthedRequest,
    SessionAuth,
    require_role,
)

router = Router(tags=["itsm"])


@router.get("/runbooks", auth=SessionAuth(), response=dict[str, RunbookOut])
@require_role(*TECHNICIAN_OR_MANAGER)
def list_runbooks(request: AuthedRequest) -> dict[str, Runbook]:
    return RUNBOOK_REGISTRY


@router.post("/review-items/{item_id}/execute", auth=SessionAuth(), response=RunbookExecutionOut)
@require_role(*TECHNICIAN_OR_MANAGER)
def execute(request: AuthedRequest, item_id: uuid.UUID) -> RunbookExecution:
    try:
        review_item = ReviewItem.objects.select_related("ai_run", "ticket").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e

    try:
        return RunbookExecution.objects.execute(review_item=review_item, executed_by=request.auth)
    except RunbookError as e:
        raise HttpError(422, str(e)) from e
