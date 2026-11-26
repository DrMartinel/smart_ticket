"""The simulator's own routes: inject and clear faults, reset the cloud, check health."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from cloud_sim.api.errors import ApiError
from cloud_sim.api.identity import cloud_of
from cloud_sim.cloud import Invalid, NotFound
from cloud_sim.faults import Fault, FaultKind

router = APIRouter(prefix="/sim")


class FaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: FaultKind
    target_id: str | None = None
    params: dict[str, Any] = {}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/faults")
def list_faults(request: Request) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        return {"faults": [fault_view(f) for f in cloud.faults.values()]}


@router.post("/faults", status_code=201)
def add_fault(request: Request, body: FaultIn) -> dict[str, Any]:
    try:
        fault = cloud_of(request).add_fault(body.kind, body.target_id, body.params)
    except NotFound as e:
        raise ApiError(404, {"message": str(e)}) from None
    except Invalid as e:
        raise ApiError(400, {"message": str(e)}) from None
    return {"fault": fault_view(fault)}


@router.delete("/faults/{fault_id}", status_code=204)
def remove_fault(request: Request, fault_id: str) -> Response:
    try:
        cloud_of(request).remove_fault(fault_id)
    except NotFound as e:
        raise ApiError(404, {"message": str(e)}) from None
    return Response(status_code=204)


@router.post("/reset", status_code=204)
def reset(request: Request) -> Response:
    cloud_of(request).reset()
    return Response(status_code=204)


def fault_view(fault: Fault) -> dict[str, Any]:
    return {
        "id": fault.id,
        "kind": fault.kind.value,
        "target": fault.target.value,
        "target_id": fault.target_id,
        "started_at": fault.started_at.isoformat(),
        "params": fault.params,
    }
