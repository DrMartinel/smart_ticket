"""Permission and role URN helpers; system data lives in `apps.accounts.data` (ADR-0045)."""

from __future__ import annotations

import re

from apps.accounts.data import (
    ADD_ON_ROLES,
    BASE_ROLES,
    STRUCTURAL_ROLES,
    SYSTEM_ROLE_NAMES,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    ScopeKind,
    SystemRole,
)

__all__ = [
    "ADD_ON_ROLES",
    "BASE_ROLES",
    "NID",
    "PERMISSION_PREFIX",
    "PERMISSION_URN",
    "ROLE_NAME",
    "ROLE_PREFIX",
    "ROLE_URN",
    "STRUCTURAL_ROLES",
    "SYSTEM_ROLE_NAMES",
    "SYSTEM_ROLE_PERMISSIONS",
    "Permission",
    "ScopeKind",
    "SystemRole",
    "area_of",
    "custom_role_urn",
    "is_permission_urn",
    "is_role_urn",
    "permissions_scopable_at",
]

NID = "smart-ticket"
PERMISSION_PREFIX = f"urn:{NID}:perm:"
ROLE_PREFIX = f"urn:{NID}:role:"
PERMISSION_URN = re.compile(
    r"^urn:smart-ticket:perm:[a-z][a-z0-9-]{0,31}(:[a-z][a-z0-9-]{0,31}){1,2}$"
)
ROLE_URN = re.compile(r"^urn:smart-ticket:role:(system|custom):[a-z][a-z0-9-]{1,47}$")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,47}$")


def area_of(permission: Permission) -> str:
    """The permission's area, its first segment after `perm`."""
    return permission.value.removeprefix(PERMISSION_PREFIX).split(":")[0]


def custom_role_urn(name: str) -> str:
    """The URN of a custom role called `name`, e.g. "Read-only auditor" → `…:custom:read-only-auditor`."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return f"{ROLE_PREFIX}custom:{slug}"


def is_role_urn(value: str) -> bool:
    return bool(ROLE_URN.match(value))


def is_permission_urn(value: str) -> bool:
    return bool(PERMISSION_URN.match(value))


def permissions_scopable_at(permissions: frozenset[Permission], scope: ScopeKind) -> bool:
    """Whether every one of `permissions` may be granted at `scope`."""
    return all(scope in p.scopes for p in permissions)
