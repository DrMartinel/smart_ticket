from typing import Any

from ninja import Router

from apps.metrics.response_schema import DashboardOut
from apps.metrics.utils import dashboard_summary
from apps.accounts.permissions import AuthedRequest, SessionAuth

router = Router(tags=["metrics"])


@router.get("/dashboard", auth=SessionAuth(), response=DashboardOut)
def dashboard(request: AuthedRequest, window_days: int = 30) -> dict[str, Any]:
    return dashboard_summary(window_days)
