"""Cinder's v3 API, the parts core-api uses: volumes and their attachments."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from cloud_sim.api.errors import nova_error
from cloud_sim.api.identity import Admin, cloud_of
from cloud_sim.cloud import Cloud, NotFound, Volume

router = APIRouter(prefix="/volume/v3/{tenant}")


@router.get("/volumes/detail")
def list_volumes(
    request: Request,
    tenant: str,
    _: Admin,
    all_tenants: bool = False,
    project_id: str | None = None,
    name: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        scope = project_id if all_tenants else (project_id or tenant)
        volumes = [
            v
            for v in cloud.volumes.values()
            if (scope is None or v.project_id == scope)
            and (name is None or v.name == name)
            and (status is None or v.status.value == status)
        ]
        return {"volumes": [volume_view(cloud, v) for v in volumes]}


@router.get("/volumes/{volume_id}")
def get_volume(request: Request, tenant: str, volume_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        try:
            return {"volume": volume_view(cloud, cloud.volume(volume_id))}
        except NotFound as e:
            raise nova_error(404, str(e)) from None


def volume_view(cloud: Cloud, volume: Volume) -> dict[str, Any]:
    attachments = (
        [
            {
                "server_id": volume.server_id,
                "attachment_id": volume.id,
                "volume_id": volume.id,
                "device": volume.device,
                "host_name": cloud.servers[volume.server_id].host,
            }
        ]
        if volume.server_id
        else []
    )
    return {
        "id": volume.id,
        "name": volume.name,
        "status": volume.status.value,
        "size": volume.size_gb,
        "os-vol-tenant-attr:tenant_id": volume.project_id,
        "attachments": attachments,
        "volume_type": "ssd",
        "bootable": "false",
        "created_at": volume.created.isoformat(),
        "metadata": {"iops_quota": str(volume.iops_quota)},
    }
