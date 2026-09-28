from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.itsm_mock.models import RunbookExecution
from apps.itsm_mock.schemas import RunbookExecutionOut, RunbookOut
from apps.itsm_mock.services import RUNBOOK_REGISTRY, Runbook, RunbookError, execute_runbook
from apps.review.models import ReviewItem
from common.permissions import AuthedRequest

router = Router(tags=["itsm"])


@router.get("/runbooks", auth=JWTAuth(), response=dict[str, RunbookOut])
def list_runbooks(request: AuthedRequest) -> dict[str, Runbook]:
    return RUNBOOK_REGISTRY


@router.post("/review-items/{item_id}/execute", auth=JWTAuth(), response=RunbookExecutionOut)
def execute(request: AuthedRequest, item_id: int) -> RunbookExecution:
    try:
        review_item = ReviewItem.objects.select_related("ai_run", "ticket").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e

    try:
        return execute_runbook(review_item=review_item, executed_by=request.auth)
    except RunbookError as e:
        raise HttpError(422, str(e)) from e
