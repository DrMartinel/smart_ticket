"""
Root URLconf. core-api is the source of truth (spec §1) so every business
endpoint is mounted here, under one Django Ninja API, JWT-secured by
default (spec's "REST (JWT, RBAC)" arrow from web → core-api).
"""

from django.http import HttpRequest, HttpResponse
from django.urls import path
from ninja_extra import NinjaExtraAPI

from apps.accounts.permissions import AccessError
from apps.accounts.views import auth_router
from apps.accounts.views import router as accounts_router
from apps.tickets.views import router as tickets_router
from apps.kb.views import router as kb_router
from apps.review.views import router as review_router
from apps.fewshot.views import router as fewshot_router
from apps.itsm_mock.views import router as itsm_router
from apps.metrics.views import router as metrics_router
from apps.chat.views import router as chat_router
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.views import router as lifecycle_router

api = NinjaExtraAPI(title="Smart Ticket Triage — core-api", version="1.0.0")

api.add_router("/auth", auth_router)
api.add_router("/accounts", accounts_router)
api.add_router("/tickets", tickets_router)
api.add_router("/kb", kb_router)
api.add_router("/review", review_router)
api.add_router("/fewshot", fewshot_router)
api.add_router("/itsm", itsm_router)
api.add_router("/metrics", metrics_router)
api.add_router("/chat", chat_router)
api.add_router("/lifecycle", lifecycle_router)


@api.exception_handler(LifecycleError)
def lifecycle_refused(request: HttpRequest, exc: LifecycleError) -> HttpResponse:
    return api.create_response(
        request,
        {"code": exc.code.value, "message": exc.message, "details": exc.details},
        status=exc.status,
    )


@api.exception_handler(AccessError)
def access_refused(request: HttpRequest, exc: AccessError) -> HttpResponse:
    return api.create_response(
        request,
        {"code": exc.code.value, "message": exc.message, "details": exc.details},
        status=exc.status,
    )


urlpatterns = [
    path("api/", api.urls),
]
