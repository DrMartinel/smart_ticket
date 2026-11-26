"""The infra read routes (F17 §h.1), split into two routers so every endpoint carries one
permission: `/api/infra/*` for staff (`infra:read`, every project) and `/api/requester/infra/*`
for customers (`infra:read:own`, only their Keystone projects); and the customer routes
(`infra:customers:manage`, F17 §o.9)."""

import uuid

from django.conf import settings
from ninja import Router, Status

from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.accounts.domain.catalog import Permission
from apps.infra.domain.catalog import Catalog, Listing, Surface
from apps.infra.models import Customer
from apps.infra.request_schema import (
    CustomerIn,
    CustomerPatch,
    LogSearchIn,
    MetricQueryIn,
    PromQLIn,
    TraceSearchIn,
)
from apps.infra.response_schema import (
    AlertOut,
    CatalogOut,
    CustomerListingOut,
    CustomerOut,
    LogAnswerOut,
    MetricAnswerOut,
    NetworkDetailOut,
    NetworkOut,
    ProjectOut,
    ServerDetailOut,
    ServerOut,
    SilenceOut,
    TraceAnswerOut,
    VolumeOut,
)
from apps.infra.services.customers import CustomerListing, customers
from apps.infra.services.inventory import Inventory
from apps.infra.services.observability import (
    LogAnswer,
    MetricAnswer,
    Observability,
    TraceAnswer,
)
from apps.infra.domain.resources import Alert, Network, Project, Server, Silence, Volume

router = Router(tags=["infra"])
requester_router = Router(tags=["requester-infra"])


# ── staff / console (`/api/infra/*`) ──


@router.get("/projects", auth=SessionAuth(), response=list[ProjectOut])
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def list_projects(request: AuthedRequest) -> list[Project]:
    return Inventory.for_all(request.auth).projects()


@router.get("/servers", auth=SessionAuth(), response=list[ServerOut])
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def list_servers(request: AuthedRequest, project_id: str | None = None) -> list[Server]:
    return Inventory.for_all(request.auth).servers(project_id)


@router.get("/servers/{server_id}", auth=SessionAuth(), response=ServerDetailOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def get_server(request: AuthedRequest, server_id: str) -> Server:
    return Inventory.for_all(request.auth).server(server_id)


@router.get("/volumes", auth=SessionAuth(), response=list[VolumeOut])
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def list_volumes(request: AuthedRequest, project_id: str | None = None) -> list[Volume]:
    return Inventory.for_all(request.auth).volumes(project_id)


@router.get("/volumes/{volume_id}", auth=SessionAuth(), response=VolumeOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def get_volume(request: AuthedRequest, volume_id: str) -> Volume:
    return Inventory.for_all(request.auth).volume(volume_id)


@router.get("/networks", auth=SessionAuth(), response=list[NetworkOut])
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def list_networks(request: AuthedRequest, project_id: str | None = None) -> list[Network]:
    return Inventory.for_all(request.auth).networks(project_id)


@router.get("/networks/{network_id}", auth=SessionAuth(), response=NetworkDetailOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def get_network(request: AuthedRequest, network_id: str) -> Network:
    return Inventory.for_all(request.auth).network(network_id)


@router.get("/alerts", auth=SessionAuth(), response=list[AlertOut])
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def list_alerts(request: AuthedRequest, project_id: str | None = None) -> list[Alert]:
    return Inventory.for_all(request.auth).alerts(project_id)


@router.get("/alerts/silences", auth=SessionAuth(), response=list[SilenceOut])
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def list_silences(request: AuthedRequest, project_id: str | None = None) -> list[Silence]:
    return Inventory.for_all(request.auth).silences(project_id)


@router.get("/catalog", auth=SessionAuth(), response=CatalogOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def get_catalog(request: AuthedRequest) -> Listing:
    return Catalog(Surface.STAFF).listing(settings.THRESHOLDS.infra)


@router.post("/metrics/query", auth=SessionAuth(), response=MetricAnswerOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def query_metrics(request: AuthedRequest, body: MetricQueryIn) -> MetricAnswer:
    return Observability.for_all(request.auth).metrics(body.query(), body.project_id)


@router.post("/metrics/promql", auth=SessionAuth(), response=MetricAnswerOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def run_promql(request: AuthedRequest, body: PromQLIn) -> MetricAnswer:
    return Observability.for_all(request.auth).promql(body.query(), body.project_id)


@router.post("/logs/search", auth=SessionAuth(), response=LogAnswerOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def search_logs(request: AuthedRequest, body: LogSearchIn) -> LogAnswer:
    return Observability.for_all(request.auth).logs(body.query(), body.project_id)


@router.post("/traces/search", auth=SessionAuth(), response=TraceAnswerOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def search_traces(request: AuthedRequest, body: TraceSearchIn) -> TraceAnswer:
    return Observability.for_all(request.auth).traces(body.query(), body.project_id)


@router.get("/traces/{trace_id}", auth=SessionAuth(), response=TraceAnswerOut)
@require(Permission.INFRA_READ, agent=AgentTier.READ)
def get_trace(request: AuthedRequest, trace_id: str) -> TraceAnswer:
    return Observability.for_all(request.auth).trace(trace_id)


# ── customers (`/api/infra/customers`) ──


@router.get("/customers", auth=SessionAuth(), response=CustomerListingOut)
@require(Permission.INFRA_CUSTOMERS_MANAGE, agent=AgentTier.NONE)
def list_customers(request: AuthedRequest) -> CustomerListing:
    return customers.listing()


@router.post("/customers", auth=SessionAuth(), response={201: CustomerOut})
@require(Permission.INFRA_CUSTOMERS_MANAGE, agent=AgentTier.NONE)
def create_customer(request: AuthedRequest, payload: CustomerIn) -> Status[Customer]:
    return Status(201, customers.create(request.auth.user, payload.model_dump()))


@router.patch("/customers/{customer_id}", auth=SessionAuth(), response=CustomerOut)
@require(Permission.INFRA_CUSTOMERS_MANAGE, agent=AgentTier.NONE)
def change_customer(
    request: AuthedRequest, customer_id: uuid.UUID, payload: CustomerPatch
) -> Customer:
    return customers.change(request.auth.user, customer_id, payload.model_dump())


# ── customer / chat (`/api/requester/infra/*`) ──


@requester_router.get("/projects", auth=SessionAuth(), response=list[ProjectOut])
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def list_my_projects(request: AuthedRequest) -> list[Project]:
    return Inventory.for_own(request.auth).projects()


@requester_router.get("/servers", auth=SessionAuth(), response=list[ServerOut])
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def list_my_servers(request: AuthedRequest, project_id: str | None = None) -> list[Server]:
    return Inventory.for_own(request.auth).servers(project_id)


@requester_router.get("/servers/{server_id}", auth=SessionAuth(), response=ServerDetailOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def get_my_server(request: AuthedRequest, server_id: str) -> Server:
    return Inventory.for_own(request.auth).server(server_id)


@requester_router.get("/volumes", auth=SessionAuth(), response=list[VolumeOut])
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def list_my_volumes(request: AuthedRequest, project_id: str | None = None) -> list[Volume]:
    return Inventory.for_own(request.auth).volumes(project_id)


@requester_router.get("/volumes/{volume_id}", auth=SessionAuth(), response=VolumeOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def get_my_volume(request: AuthedRequest, volume_id: str) -> Volume:
    return Inventory.for_own(request.auth).volume(volume_id)


@requester_router.get("/networks", auth=SessionAuth(), response=list[NetworkOut])
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def list_my_networks(request: AuthedRequest, project_id: str | None = None) -> list[Network]:
    return Inventory.for_own(request.auth).networks(project_id)


@requester_router.get("/networks/{network_id}", auth=SessionAuth(), response=NetworkDetailOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def get_my_network(request: AuthedRequest, network_id: str) -> Network:
    return Inventory.for_own(request.auth).network(network_id)


@requester_router.get("/alerts", auth=SessionAuth(), response=list[AlertOut])
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def list_my_alerts(request: AuthedRequest, project_id: str | None = None) -> list[Alert]:
    return Inventory.for_own(request.auth).alerts(project_id)


@requester_router.get("/alerts/silences", auth=SessionAuth(), response=list[SilenceOut])
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def list_my_silences(request: AuthedRequest, project_id: str | None = None) -> list[Silence]:
    return Inventory.for_own(request.auth).silences(project_id)


@requester_router.get("/catalog", auth=SessionAuth(), response=CatalogOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def get_my_catalog(request: AuthedRequest) -> Listing:
    return Catalog(Surface.CUSTOMER).listing(settings.THRESHOLDS.infra)


@requester_router.post("/metrics/query", auth=SessionAuth(), response=MetricAnswerOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def query_my_metrics(request: AuthedRequest, body: MetricQueryIn) -> MetricAnswer:
    return Observability.for_own(request.auth).metrics(body.query(), body.project_id)


@requester_router.post("/logs/search", auth=SessionAuth(), response=LogAnswerOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def search_my_logs(request: AuthedRequest, body: LogSearchIn) -> LogAnswer:
    return Observability.for_own(request.auth).logs(body.query(), body.project_id)


@requester_router.post("/traces/search", auth=SessionAuth(), response=TraceAnswerOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def search_my_traces(request: AuthedRequest, body: TraceSearchIn) -> TraceAnswer:
    return Observability.for_own(request.auth).traces(body.query(), body.project_id)


@requester_router.get("/traces/{trace_id}", auth=SessionAuth(), response=TraceAnswerOut)
@require(Permission.INFRA_READ_OWN, agent=AgentTier.READ)
def get_my_trace(request: AuthedRequest, trace_id: str) -> TraceAnswer:
    return Observability.for_own(request.auth).trace(trace_id)
