from django.db.models import QuerySet
from ninja import Router

from apps.fewshot.models import FewshotExample
from apps.fewshot.response_schema import FewshotExampleOut
from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require

router = Router(tags=["fewshot"])


@router.get("/category/{category}", auth=SessionAuth(), response=list[FewshotExampleOut])
@require(Permission.REVIEW_FEWSHOT_READ, agent=AgentTier.NONE)
def list_active(request: AuthedRequest, category: str) -> QuerySet[FewshotExample]:
    return FewshotExample.objects.active_for_category(category)
