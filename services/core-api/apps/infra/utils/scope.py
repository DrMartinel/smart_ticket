"""The cloud projects a caller reaches (F17 BR-F17-02..04): every one for staff holding
`infra:read`, else the ones Keystone lists the caller's user as a member of, read on every
request."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.accounts.models import User
from apps.accounts.permissions import Caller
from apps.accounts.utils.catalog import Permission
from apps.infra.models import InfraBackend
from apps.infra.utils.clients import BackendUnavailable, OpenStack


@dataclass(frozen=True)
class InfraScope:
    """Every project, or the projects in `project_ids`."""

    everything: bool
    project_ids: frozenset[str] = frozenset()

    @classmethod
    def of(cls, caller: Caller, cloud: OpenStack) -> InfraScope:
        """Raises `BackendUnavailable` when Keystone can't say whom a customer belongs to."""
        if caller.holds(Permission.INFRA_READ):
            return cls(everything=True)
        return cls(everything=False, project_ids=member_projects(caller.user, cloud))

    def reaches(self, project_id: str | None) -> bool:
        return self.everything or project_id in self.project_ids

    def narrowed_to(self, project_id: str | None) -> frozenset[str] | None:
        """The projects a read asking for `project_id` covers; None for every project."""
        if project_id is None:
            return None if self.everything else self.project_ids
        return frozenset({project_id}) if self.reaches(project_id) else frozenset()

    @staticmethod
    def listing(projects: frozenset[str] | None) -> list[str]:
        """`projects` as an `infra_queries.projects` value, `*` for every project."""
        return ["*"] if projects is None else sorted(projects)


def member_projects(user: User, cloud: OpenStack) -> frozenset[str]:
    """The projects Keystone lists `user` as a member of, found by their Keycloak subject;
    none for a person with no Keycloak subject or no Keystone user."""
    if not user.external_id:
        return frozenset()
    found = cloud.get(
        "identity",
        "/users",
        {
            "idp_id": settings.OPENSTACK_FEDERATION_IDP,
            "protocol_id": settings.OPENSTACK_FEDERATION_PROTOCOL,
            "unique_id": user.external_id,
        },
    )
    try:
        users = found["users"]
        if not users:
            return frozenset()
        if len(users) > 1:
            raise BackendUnavailable(InfraBackend.CLOUD, "Keystone lists more than one user")
        assignments = cloud.get("identity", "/role_assignments", {"user.id": users[0]["id"]})
        return frozenset(
            a["scope"]["project"]["id"]
            for a in assignments["role_assignments"]
            if "project" in a["scope"]
        )
    except (KeyError, TypeError, IndexError) as e:
        raise BackendUnavailable(InfraBackend.CLOUD, "Keystone's answer is unreadable") from e
