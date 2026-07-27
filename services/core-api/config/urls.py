"""
Root URLconf. core-api is the source of truth (spec §1) so every business
endpoint is mounted here, under one Django Ninja API, JWT-secured by
default (spec's "REST (JWT, RBAC)" arrow from web → core-api).
"""

from django.urls import path
from ninja_jwt.controller import NinjaJWTDefaultController
from ninja_extra import NinjaExtraAPI

from apps.accounts.api import router as accounts_router
from apps.tickets.api import router as tickets_router
from apps.kb.api import router as kb_router
from apps.review.api import router as review_router
from apps.fewshot.api import router as fewshot_router
from apps.itsm_mock.api import router as itsm_router
from apps.metrics.api import router as metrics_router

api = NinjaExtraAPI(title="Smart Ticket Triage — core-api", version="1.0.0")
api.register_controllers(NinjaJWTDefaultController)

api.add_router("/accounts", accounts_router)
api.add_router("/tickets", tickets_router)
api.add_router("/kb", kb_router)
api.add_router("/review", review_router)
api.add_router("/fewshot", fewshot_router)
api.add_router("/itsm", itsm_router)
api.add_router("/metrics", metrics_router)

urlpatterns = [
    path("api/", api.urls),
]
