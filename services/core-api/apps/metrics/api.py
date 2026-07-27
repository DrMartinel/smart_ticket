from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.metrics.services import dashboard_summary

router = Router(tags=["metrics"])


@router.get("/dashboard", auth=JWTAuth())
def dashboard(request, window_days: int = 30):
    return dashboard_summary(window_days)
