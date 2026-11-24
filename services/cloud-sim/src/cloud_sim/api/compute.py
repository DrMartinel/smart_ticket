"""Nova's v2.1 API, the parts core-api uses: servers, server actions and volume attachments."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from cloud_sim.api.errors import nova_error
from cloud_sim.api.identity import Admin, cloud_of
from cloud_sim.cloud import Cloud, Conflict, Invalid, NotFound, Server, ServerStatus, Volume

router = APIRouter(prefix="/compute/v2.1")

_POWER = {ServerStatus.ACTIVE: 1, ServerStatus.ERROR: 1, ServerStatus.SHUTOFF: 4}
_TASK = {ServerStatus.REBOOT: "rebooting", ServerStatus.HARD_REBOOT: "rebooting_hard"}


@router.get("/servers/detail")
def list_servers(
    request: Request,
    _: Admin,
    all_tenants: bool = False,
    project_id: str | None = None,
    name: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        servers = [
            s
            for s in cloud.servers.values()
            if (project_id is None or s.project_id == project_id)
            and (name is None or s.name == name)
            and (status is None or cloud.status_of(s).value == status.upper())
        ]
        return {"servers": [server_view(cloud, s) for s in servers]}


@router.get("/servers/{server_id}")
def get_server(request: Request, server_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        return {"server": server_view(cloud, _server(cloud, server_id))}


@router.post("/servers/{server_id}/action", status_code=202)
def server_action(request: Request, server_id: str, body: dict[str, Any], _: Admin) -> Response:
    cloud = cloud_of(request)
    try:
        if "reboot" in body:
            kind = str((body["reboot"] or {}).get("type", "")).upper()
            if kind not in {"SOFT", "HARD"}:
                raise nova_error(400, "reboot type must be SOFT or HARD")
            cloud.reboot(server_id, hard=kind == "HARD")
        elif "os-start" in body:
            cloud.start(server_id)
        elif "os-stop" in body:
            cloud.stop(server_id)
        else:
            raise nova_error(400, "Unsupported server action")
    except NotFound as e:
        raise nova_error(404, str(e)) from None
    except Conflict as e:
        raise nova_error(409, str(e)) from None
    return Response(status_code=202)


@router.get("/servers/{server_id}/os-volume_attachments")
def list_attachments(request: Request, server_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        server = _server(cloud, server_id)
        return {"volumeAttachments": [attachment_view(v) for v in cloud.volumes_of(server)]}


@router.post("/servers/{server_id}/os-volume_attachments")
def attach_volume(
    request: Request, server_id: str, body: dict[str, Any], _: Admin
) -> dict[str, Any]:
    cloud = cloud_of(request)
    volume_id = str((body.get("volumeAttachment") or {}).get("volumeId", ""))
    try:
        volume = cloud.attach(volume_id, server_id)
    except NotFound as e:
        raise nova_error(404, str(e)) from None
    except Invalid as e:
        raise nova_error(400, str(e)) from None
    except Conflict as e:
        raise nova_error(409, str(e)) from None
    return {"volumeAttachment": attachment_view(volume)}


@router.delete("/servers/{server_id}/os-volume_attachments/{volume_id}", status_code=202)
def detach_volume(request: Request, server_id: str, volume_id: str, _: Admin) -> Response:
    cloud = cloud_of(request)
    try:
        cloud.detach(volume_id, server_id)
    except NotFound as e:
        raise nova_error(404, str(e)) from None
    except Conflict as e:
        raise nova_error(409, str(e)) from None
    return Response(status_code=202)


def server_view(cloud: Cloud, server: Server) -> dict[str, Any]:
    status = cloud.status_of(server)
    network = cloud.network_of(server)
    return {
        "id": server.id,
        "name": server.name,
        "status": status.value,
        "tenant_id": server.project_id,
        "user_id": None,
        "created": server.created.isoformat(),
        "updated": (server.updated or server.created).isoformat(),
        "OS-EXT-SRV-ATTR:host": server.host,
        "OS-EXT-STS:vm_state": {"SHUTOFF": "stopped", "ERROR": "error"}.get(status.value, "active"),
        "OS-EXT-STS:task_state": _TASK.get(server.status),
        "OS-EXT-STS:power_state": _POWER.get(status, 1),
        "flavor": {
            "original_name": server.flavor.name,
            "vcpus": server.flavor.vcpus,
            "ram": server.flavor.ram_mb,
            "disk": server.flavor.disk_gb,
        },
        "addresses": {
            network.name: [
                {
                    "addr": server.ip,
                    "version": 4,
                    "OS-EXT-IPS:type": "fixed",
                    "OS-EXT-IPS-MAC:mac_addr": server.mac,
                }
            ]
        },
        "os-extended-volumes:volumes_attached": [{"id": v.id} for v in cloud.volumes_of(server)],
        "security_groups": [{"name": name} for name in server.security_groups],
        "metadata": {"workload": server.workload},
    }


def attachment_view(volume: Volume) -> dict[str, Any]:
    return {
        "id": volume.id,
        "volumeId": volume.id,
        "serverId": volume.server_id,
        "device": volume.device,
    }


def _server(cloud: Cloud, server_id: str) -> Server:
    try:
        return cloud.server(server_id)
    except NotFound as e:
        raise nova_error(404, str(e)) from None
