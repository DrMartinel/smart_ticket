"""The infra read routes (F17 §h.1): staff holding `infra:read` reach every project, a customer
holding `infra:read:own` their own."""

from ninja import Router

from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.accounts.utils.catalog import Permission
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
from apps.infra.utils.inventory import Inventory
from apps.infra.utils.resources import Alert, Network, Project, Server, Silence, Volume

router = Router(tags=["infra"])

READ = Permission.INFRA_READ
READ_OWN = Permission.INFRA_READ_OWN


@router.get("/projects", auth=SessionAuth(), response=list[ProjectOut])
@require(READ, READ_OWN, agent=AgentTier.READ)
def list_projects(request: AuthedRequest) -> list[Project]:
    return Inventory.of(request.auth).projects()


@router.get("/servers", auth=SessionAuth(), response=list[ServerOut])
@require(READ, READ_OWN, agent=AgentTier.READ)
def list_servers(request: AuthedRequest, project_id: str | None = None) -> list[Server]:
    return Inventory.of(request.auth).servers(project_id)


@router.get("/servers/{server_id}", auth=SessionAuth(), response=ServerDetailOut)
@require(READ, READ_OWN, agent=AgentTier.READ)
def get_server(request: AuthedRequest, server_id: str) -> Server:
    return Inventory.of(request.auth).server(server_id)


@router.get("/volumes", auth=SessionAuth(), response=list[VolumeOut])
@require(READ, READ_OWN, agent=AgentTier.READ)
def list_volumes(request: AuthedRequest, project_id: str | None = None) -> list[Volume]:
    return Inventory.of(request.auth).volumes(project_id)


@router.get("/volumes/{volume_id}", auth=SessionAuth(), response=VolumeOut)
@require(READ, READ_OWN, agent=AgentTier.READ)
def get_volume(request: AuthedRequest, volume_id: str) -> Volume:
    return Inventory.of(request.auth).volume(volume_id)


@router.get("/networks", auth=SessionAuth(), response=list[NetworkOut])
@require(READ, READ_OWN, agent=AgentTier.READ)
def list_networks(request: AuthedRequest, project_id: str | None = None) -> list[Network]:
    return Inventory.of(request.auth).networks(project_id)


@router.get("/networks/{network_id}", auth=SessionAuth(), response=NetworkDetailOut)
@require(READ, READ_OWN, agent=AgentTier.READ)
def get_network(request: AuthedRequest, network_id: str) -> Network:
    return Inventory.of(request.auth).network(network_id)


@router.get("/alerts", auth=SessionAuth(), response=list[AlertOut])
@require(READ, READ_OWN, agent=AgentTier.READ)
def list_alerts(request: AuthedRequest, project_id: str | None = None) -> list[Alert]:
    return Inventory.of(request.auth).alerts(project_id)


@router.get("/alerts/silences", auth=SessionAuth(), response=list[SilenceOut])
@require(READ, READ_OWN, agent=AgentTier.READ)
def list_silences(request: AuthedRequest, project_id: str | None = None) -> list[Silence]:
    return Inventory.of(request.auth).silences(project_id)
