"""The cloud projects a caller reaches (F17 BR-F17-02..04): every one on the staff router
(`infra:read`), or the ones Keystone lists the caller's user as a member of on the requester
router (`infra:read:own`), read on every request."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.accounts.models import User
from apps.infra.models import InfraBackend
from apps.infra.clients.backends import BackendUnavailable, OpenStack


@dataclass(frozen=True)
class InfraScope:
    """Every project, or the projects in `project_ids`."""

    everything: bool
    project_ids: frozenset[str] = frozenset()

    @classmethod
    def all(cls) -> InfraScope:
        """Every cloud project, for staff routes gated by `infra:read`."""
        return cls(everything=True)

    @classmethod
    def own(cls, user: User, cloud: OpenStack) -> InfraScope:
        """Only the projects Keystone lists `user` in, for requester routes gated by
        `infra:read:own`. Raises `BackendUnavailable` when Keystone can't answer."""
        return cls(everything=False, project_ids=member_projects(user, cloud))

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


@dataclass(frozen=True)
class KeystoneUser:
    id: str
    domain_id: str


def keystone_user(user: User, cloud: OpenStack) -> KeystoneUser | None:
    """`user`'s Keystone user, found by their Keycloak subject; None for a person with no Keycloak
    subject or no Keystone user. Raises `BackendUnavailable` when Keystone can't answer, answers
    unreadably, or lists more than one user."""
    if not user.external_id:
        return None
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
            return None
        if len(users) > 1:
            raise BackendUnavailable(InfraBackend.CLOUD, "Keystone lists more than one user")
        return KeystoneUser(users[0]["id"], users[0]["domain_id"])
    except (KeyError, TypeError, IndexError) as e:
        raise BackendUnavailable(InfraBackend.CLOUD, "Keystone's answer is unreadable") from e


def member_projects(user: User, cloud: OpenStack) -> frozenset[str]:
    """The projects Keystone lists `user` as a member of; none for a person with no Keycloak
    subject or no Keystone user."""
    found = keystone_user(user, cloud)
    if found is None:
        return frozenset()
    assignments = cloud.get("identity", "/role_assignments", {"user.id": found.id})
    try:
        return frozenset(
            a["scope"]["project"]["id"]
            for a in assignments["role_assignments"]
            if "project" in a["scope"]
        )
    except (KeyError, TypeError, IndexError) as e:
        raise BackendUnavailable(InfraBackend.CLOUD, "Keystone's answer is unreadable") from e
