import uuid

from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.itsm_mock.models import RUNBOOK_REGISTRY, Runbook, RunbookError, RunbookExecution
from apps.itsm_mock.response_schema import RunbookExecutionOut, RunbookOut
from apps.review.models import ReviewItem
from common.permissions import AuthedRequest

router = Router(tags=["itsm"])


@router.get("/runbooks", auth=JWTAuth(), response=dict[str, RunbookOut])
def list_runbooks(request: AuthedRequest) -> dict[str, Runbook]:
    return RUNBOOK_REGISTRY


@router.post("/review-items/{item_id}/execute", auth=JWTAuth(), response=RunbookExecutionOut)
def execute(request: AuthedRequest, item_id: uuid.UUID) -> RunbookExecution:
    try:
        review_item = ReviewItem.objects.select_related("ai_run", "ticket").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e

    try:
        return RunbookExecution.objects.execute(review_item=review_item, executed_by=request.auth)
    except RunbookError as e:
        raise HttpError(422, str(e)) from e
