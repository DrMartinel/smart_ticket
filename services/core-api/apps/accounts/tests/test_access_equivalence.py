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
WITHDRAWN_SINCE_SNAPSHOT = {
    "PUT /api/accounts/people/{username}/rights",
}

ADDED_SINCE_SNAPSHOT: dict[str, Permission] = {
    "PUT /api/accounts/people/{username}/base-role": Permission.ACCESS_GRANT,
    "GET /api/access/holders": Permission.ACCESS_READ,
    "GET /api/access/me": Permission.SELF_PROFILE,
    "GET /api/access/people/{username}/access": Permission.ACCESS_READ,
    "GET /api/access/people/{username}/assignments": Permission.ACCESS_READ,
    "GET /api/access/people/{username}/explain": Permission.ACCESS_READ,
    "GET /api/access/permissions": Permission.ACCESS_READ,
    "GET /api/access/reviews": Permission.ACCESS_REVIEW_MANAGE,
    "GET /api/access/reviews/inbox": Permission.ACCESS_REVIEW_RESPOND,
    "GET /api/access/reviews/{campaign_id}": Permission.ACCESS_REVIEW_MANAGE,
    "GET /api/access/roles": Permission.ACCESS_READ,
    "GET /api/access/roles/{urn}": Permission.ACCESS_READ,
    "GET /api/accounts/people/{username}": Permission.ACCESS_PEOPLE_READ,
    "GET /api/org/departments": Permission.ORG_DEPARTMENTS_READ,
    "GET /api/org/departments/{code}": Permission.ORG_DEPARTMENTS_READ,
    "GET /api/org/departments/{code}/people": Permission.ORG_DEPARTMENTS_READ,
    "POST /api/org/departments/{code}/people": Permission.ORG_DEPARTMENTS_MANAGE,
    "GET /api/org/delegable-roles": Permission.ACCESS_GRANT_DELEGABLE,
    "GET /api/org/departments/{code}/grants": Permission.ORG_DEPARTMENTS_READ,
    "POST /api/org/departments/{code}/grants": Permission.ACCESS_GRANT_DELEGABLE,
    "POST /api/org/departments/{code}/grants/{assignment_id}/end": (
        Permission.ACCESS_GRANT_DELEGABLE
    ),
    "GET /api/requester/department-tickets": Permission.REQUESTER_DEPARTMENT_READ,
    "POST /api/agent/turns": Permission.AGENT_USE,
    "GET /api/agent/turns/{turn_id}": Permission.AGENT_USE,
    "GET /api/agent/conversations/{conversation_id}": Permission.AGENT_USE,
    "POST /api/agent/conversations/{conversation_id}/end": Permission.AGENT_USE,
    "GET /api/agent/actions": Permission.AGENT_USE,
    "POST /api/agent/actions/{action_id}/dismiss": Permission.AGENT_USE,
    "PATCH /api/access/roles/{urn}": Permission.ACCESS_ROLES_MANAGE,
    "PATCH /api/accounts/people/{username}": Permission.ACCESS_PEOPLE_MANAGE,
    "PATCH /api/org/departments/{code}": Permission.ORG_DEPARTMENTS_MANAGE,
    "POST /api/access/assignments/{assignment_id}/confirm": Permission.ACCESS_GRANT,
    "POST /api/access/assignments/{assignment_id}/end": Permission.ACCESS_GRANT,
    "POST /api/access/assignments/{assignment_id}/extend": Permission.ACCESS_GRANT,
    "POST /api/access/people/{username}/assignments": Permission.ACCESS_GRANT,
    "POST /api/access/reviews": Permission.ACCESS_REVIEW_MANAGE,
    "POST /api/access/reviews/items/{item_id}/decide": Permission.ACCESS_REVIEW_RESPOND,
    "POST /api/access/reviews/{campaign_id}/close": Permission.ACCESS_REVIEW_MANAGE,
    "POST /api/access/roles": Permission.ACCESS_ROLES_MANAGE,
    "POST /api/access/roles/{urn}/retire": Permission.ACCESS_ROLES_MANAGE,
    "POST /api/accounts/people": Permission.ACCESS_PEOPLE_MANAGE,
    "POST /api/accounts/people/{username}/deactivate": Permission.ACCESS_PEOPLE_MANAGE,
    "POST /api/accounts/people/{username}/reactivate": Permission.ACCESS_PEOPLE_MANAGE,
    "POST /api/accounts/people/{username}/suspend": Permission.ACCESS_PEOPLE_MANAGE,
    "POST /api/org/departments": Permission.ORG_DEPARTMENTS_MANAGE,
    "POST /api/org/departments/{code}/archive": Permission.ORG_DEPARTMENTS_MANAGE,
    "POST /api/org/departments/{code}/move": Permission.ORG_DEPARTMENTS_MANAGE,
    "POST /api/org/import/departments": Permission.ORG_IMPORT,
    "POST /api/org/import/people": Permission.ORG_IMPORT,
}


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
    kept = {k: v for k, v in SNAPSHOT.items() if k not in WITHDRAWN_SINCE_SNAPSHOT}
    assert set(kept) <= set(current)
    assert not WITHDRAWN_SINCE_SNAPSHOT & set(current)
    for key, old in kept.items():
        assert (old["roles"] is None) == (current[key] is None), key


def test_new_routes_are_listed_with_their_permission():
    current = routes()
    assert {k: current[k] for k in set(current) - set(SNAPSHOT)} == ADDED_SINCE_SNAPSHOT


@pytest.mark.parametrize("role", list(UserRole))
def test_old_and_new_gates_admit_the_same_people(role):
    current = routes()
    diffs = []
    for key, old in SNAPSHOT.items():
        if old["roles"] is None or key in WITHDRAWN_SINCE_SNAPSHOT:
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

    assert not [
        p for p in SYSTEM_ROLE_PERMISSIONS[SystemRole.EMPLOYEE] if PERMISSIONS[p].staff_only
    ]
