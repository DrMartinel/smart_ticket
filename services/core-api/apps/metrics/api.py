from typing import Any

from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.metrics.selectors import dashboard_summary
from common.permissions import AuthedRequest

router = Router(tags=["metrics"])


@router.get("/dashboard", auth=JWTAuth())
def dashboard(request: AuthedRequest, window_days: int = 30) -> dict[str, Any]:
    return dashboard_summary(window_days)
