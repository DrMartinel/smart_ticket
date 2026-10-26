"""
Root URLconf. core-api is the source of truth (spec §1) so every business
endpoint is mounted here, under one Django Ninja API, JWT-secured by
default (spec's "REST (JWT, RBAC)" arrow from web → core-api).
"""

from django.http import HttpRequest, HttpResponse
from django.urls import path
from ninja_extra import NinjaExtraAPI

from apps.accounts.permissions import gate_authentication
from apps.accounts.views import auth_router
from apps.core.errors import CodedError
from apps.accounts.views import router as accounts_router
from apps.tickets.views import pii_router
from apps.tickets.views import router as tickets_router
from apps.kb.views import router as kb_router
from apps.review.views import router as review_router
from apps.fewshot.views import router as fewshot_router
from apps.itsm_mock.views import router as itsm_router
from apps.metrics.views import router as metrics_router
from apps.chat.views import router as chat_router
from apps.lifecycle.views import router as lifecycle_router
from apps.notifications.views import router as notifications_router
from apps.requester.views import router as requester_router
from apps.sla.views import router as sla_router
from apps.teams.views import me_router
from apps.teams.views import router as teams_router

api = NinjaExtraAPI(title="Smart Ticket Triage — core-api", version="1.0.0")

api.add_router("/auth", auth_router)
api.add_router("/accounts", accounts_router)
api.add_router("/tickets", tickets_router)
api.add_router("/pii", pii_router)
api.add_router("/kb", kb_router)
api.add_router("/review", review_router)
api.add_router("/fewshot", fewshot_router)
api.add_router("/itsm", itsm_router)
api.add_router("/metrics", metrics_router)
api.add_router("/chat", chat_router)
api.add_router("/lifecycle", lifecycle_router)
api.add_router("/notifications", notifications_router)
api.add_router("/teams", teams_router)
api.add_router("/me", me_router)
api.add_router("/sla", sla_router)
api.add_router("/requester", requester_router)
gate_authentication(api._routers)


@api.exception_handler(CodedError)
def refused(request: HttpRequest, exc: CodedError) -> HttpResponse:
    response = api.create_response(
        request,
        {"code": exc.code.value, "message": exc.message, "details": exc.details},
        status=exc.status,
    )
    response["Cache-Control"] = "no-store"
    return response


urlpatterns = [
    path("api/", api.urls),
]
