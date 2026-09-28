from django.db.models import QuerySet
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.fewshot.models import FewshotExample
from apps.fewshot.response_schema import FewshotExampleOut
from common.permissions import AuthedRequest

router = Router(tags=["fewshot"])


@router.get("/category/{category}", auth=JWTAuth(), response=list[FewshotExampleOut])
def list_active(request: AuthedRequest, category: str) -> QuerySet[FewshotExample]:
    return FewshotExample.objects.active_for_category(category)
