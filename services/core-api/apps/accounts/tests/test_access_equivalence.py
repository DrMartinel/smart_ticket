"""The permission gates admit exactly whom the role and capability gates admitted (F14 §i)."""

import json
from itertools import chain, combinations
from pathlib import Path

import pytest

from apps.accounts.models import Capability, UserRole
from apps.accounts.permissions import gate_of
from apps.accounts.utils.catalog import (
    ADD_ON_ROLES,
    BASE_ROLES,
    PERMISSIONS,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
)
from config.urls import api

SNAPSHOT = json.loads((Path(__file__).parent / "gate_snapshot.json").read_text())
ADDED_SINCE_SNAPSHOT: dict[str, str] = {}


def routes() -> dict[str, Permission | None]:
    found: dict[str, Permission | None] = {}
    for prefix, router in api._routers:
        for path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                gate = gate_of(operation.view_func)
                for method in operation.methods:
                    found[f"{method} /api{prefix.rstrip('/')}{path}"] = (
                        gate.permission if gate else None
                    )
    return found


def capability_sets():
    caps = list(Capability)
    return [
        frozenset(c)
        for c in chain.from_iterable(combinations(caps, n) for n in range(len(caps) + 1))
    ]


def new_admits(permission: Permission, role: UserRole, caps: frozenset[Capability]) -> bool:
    held = set(SYSTEM_ROLE_PERMISSIONS[BASE_ROLES[role]])
    for cap in caps:
        held |= SYSTEM_ROLE_PERMISSIONS[ADD_ON_ROLES[cap]]
    return permission in held


def test_every_snapshot_route_still_exists_with_a_gate_or_none():
    current = routes()
    assert set(SNAPSHOT) <= set(current)
    for key, old in SNAPSHOT.items():
        assert (old["roles"] is None) == (current[key] is None), key


def test_new_routes_are_listed():
    assert set(routes()) - set(SNAPSHOT) == set(ADDED_SINCE_SNAPSHOT)


@pytest.mark.parametrize("role", list(UserRole))
def test_old_and_new_gates_admit_the_same_people(role):
    current = routes()
    diffs = []
    for key, old in SNAPSHOT.items():
        if old["roles"] is None:
            continue
        permission = current[key]
        assert permission is not None
        for caps in capability_sets():
            if role is UserRole.EMPLOYEE and caps:
                continue
            before = role.value in old["roles"] or bool(
                {c.value for c in caps} & set(old["capabilities"])
            )
            if before != new_admits(permission, role, caps):
                diffs.append((key, role.value, sorted(c.value for c in caps), before))
    assert diffs == []


def test_every_permission_urn_is_well_formed_and_unique():
    from apps.accounts.utils.catalog import is_permission_urn

    values = [p.value for p in Permission]
    assert len(values) == len(set(values))
    assert all(is_permission_urn(v) for v in values)
    assert set(PERMISSIONS) == set(Permission)


def test_system_role_urns_are_well_formed():
    from apps.accounts.utils.catalog import SystemRole, is_role_urn

    assert all(is_role_urn(r.value) and ":system:" in r.value for r in SystemRole)
    assert set(SYSTEM_ROLE_PERMISSIONS) == set(SystemRole)


def test_an_employee_role_holds_no_staff_only_permission():
    from apps.accounts.utils.catalog import SystemRole

    for role in (SystemRole.EMPLOYEE, SystemRole.DEPARTMENT_HEAD):
        assert not [p for p in SYSTEM_ROLE_PERMISSIONS[role] if PERMISSIONS[p].staff_only]
