"""The infra read routes (F17 §h.1), split into two routers so every endpoint carries one
permission: `/api/infra/*` for staff (`infra:read`, every project) and `/api/requester/infra/*`
for customers (`infra:read:own`, only their Keystone projects)."""

from ninja import Router

from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.accounts.domain.catalog import Permission
from apps.infra.response_schema import (
    AlertOut,
    NetworkDetailOut,
    NetworkOut,
    ProjectOut,
    ServerDetailOut,
    ServerOut,
    SilenceOut,
    VolumeOut,
)
from apps.infra.services.inventory import Inventory
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
