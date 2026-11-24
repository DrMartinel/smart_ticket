"""The simulated cloud's starting inventory, read from `seed.json` and checked at boot."""

from __future__ import annotations

import json
from importlib import resources

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DomainSeed(_Strict):
    id: str
    name: str


class ProjectSeed(_Strict):
    id: str
    name: str
    domain: str
    environment: str


class UserSeed(_Strict):
    id: str
    name: str
    domain: str
    # The person's Keycloak subject: Keystone federates from the same Keycloak (OQ-F17-01).
    subject: str
    member_of: list[str]


class NetworkSeed(_Strict):
    id: str
    name: str
    project: str
    cidr: str


class RuleSeed(_Strict):
    id: str
    direction: str
    protocol: str | None
    port_min: int | None
    port_max: int | None
    remote_ip_prefix: str | None


class SecurityGroupSeed(_Strict):
    id: str
    name: str
    project: str
    rules: list[RuleSeed]


class ServerSeed(_Strict):
    id: str
    name: str
    project: str
    host: str
    flavor: str
    workload: str
    security_groups: list[str]
    ip: str
    # The server this one sends requests to, for traces.
    calls: str | None = None


class VolumeSeed(_Strict):
    id: str
    name: str
    project: str
    size_gb: int
    iops_quota: int
    attached_to: str | None


class FlavorSeed(_Strict):
    vcpus: int
    ram_mb: int
    disk_gb: int


class Seed(_Strict):
    region: str
    domains: list[DomainSeed]
    projects: list[ProjectSeed]
    users: list[UserSeed]
    networks: list[NetworkSeed]
    security_groups: list[SecurityGroupSeed]
    servers: list[ServerSeed]
    volumes: list[VolumeSeed]
    flavors: dict[str, FlavorSeed]

    @classmethod
    def packaged(cls) -> Seed:
        """The seed shipped with the package."""
        text = resources.files("cloud_sim").joinpath("seed.json").read_text(encoding="utf-8")
        return cls.model_validate(json.loads(text))
