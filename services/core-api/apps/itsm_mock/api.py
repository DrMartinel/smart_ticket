from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.itsm_mock.services import RUNBOOK_REGISTRY, RunbookError, execute_runbook
from apps.review.models import ReviewItem

router = Router(tags=["itsm"])


@router.get("/runbooks", auth=JWTAuth())
def list_runbooks(request):
    return RUNBOOK_REGISTRY


@router.post("/review-items/{item_id}/execute", auth=JWTAuth())
def execute(request, item_id: int):
    try:
        review_item = ReviewItem.objects.select_related("ai_run", "ticket").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e

    try:
        execution = execute_runbook(review_item=review_item, executed_by=request.auth)
    except RunbookError as e:
        raise HttpError(422, str(e)) from e

    return {
        "id": execution.id,
        "runbook_id": execution.runbook_id,
        "status": execution.status,
        "result": execution.result,
    }
