from django.db.models import QuerySet
from ninja import Router

from apps.fewshot.models import FewshotExample
from apps.fewshot.response_schema import FewshotExampleOut
from apps.accounts.permissions import AuthedRequest, SessionAuth

router = Router(tags=["fewshot"])


@router.get("/category/{category}", auth=SessionAuth(), response=list[FewshotExampleOut])
def list_active(request: AuthedRequest, category: str) -> QuerySet[FewshotExample]:
    return FewshotExample.objects.active_for_category(category)
