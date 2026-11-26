"""The permission and system-role catalogue JSON validates strictly against the code enums."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apps.accounts.utils.catalog import (
    CATALOG_PATH,
    PERMISSIONS,
    SYSTEM_ROLE_NAMES,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    ScopeKind,
    SystemRole,
    load_catalog,
)


def _baseline() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_catalog_loads_every_permission_and_system_role():
    loaded = load_catalog()
    assert loaded.permissions == PERMISSIONS
    assert loaded.system_role_permissions == SYSTEM_ROLE_PERMISSIONS
    assert loaded.system_role_names == SYSTEM_ROLE_NAMES
    assert set(loaded.permissions) == set(Permission)
    assert set(loaded.system_role_permissions) == set(SystemRole)
    assert set(loaded.system_role_names) == set(SystemRole)
    assert loaded.permissions[Permission.INFRA_READ].staff_only is True
    assert loaded.permissions[Permission.INFRA_READ_OWN].staff_only is False
    assert loaded.permissions[Permission.TICKETS_READ].scopes == (
        ScopeKind.GLOBAL,
        ScopeKind.TEAM,
        ScopeKind.DEPARTMENT,
    )


def test_missing_permission_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    del data["permissions"][Permission.INFRA_READ.value]
    with pytest.raises(ValidationError, match="missing permissions"):
        load_catalog(_write(tmp_path, data))


def test_unknown_permission_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["permissions"]["urn:smart-ticket:perm:infra:nonexistent"] = {"label": "Ghost"}
    with pytest.raises(ValidationError):
        load_catalog(_write(tmp_path, data))


def test_unknown_field_on_permission_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["permissions"][Permission.INFRA_READ.value]["staffOnly"] = False
    with pytest.raises(ValidationError):
        load_catalog(_write(tmp_path, data))


def test_scopes_without_global_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["permissions"][Permission.TICKETS_READ.value]["scopes"] = ["team"]
    with pytest.raises(ValidationError, match="global"):
        load_catalog(_write(tmp_path, data))


def test_duplicate_scopes_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["permissions"][Permission.TICKETS_READ.value]["scopes"] = ["global", "team", "team"]
    with pytest.raises(ValidationError, match="duplicates"):
        load_catalog(_write(tmp_path, data))


def test_missing_system_role_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    del data["system_roles"][SystemRole.TEAM_LEAD.value]
    with pytest.raises(ValidationError, match="missing system roles"):
        load_catalog(_write(tmp_path, data))


def test_unknown_system_role_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["system_roles"]["urn:smart-ticket:role:system:ghost"] = {
        "name": "Ghost",
        "permissions": [],
    }
    with pytest.raises(ValidationError):
        load_catalog(_write(tmp_path, data))


def test_duplicate_permission_in_system_role_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    perms = data["system_roles"][SystemRole.TEAM_LEAD.value]["permissions"]
    perms.append(perms[0])
    with pytest.raises(ValidationError, match="duplicates"):
        load_catalog(_write(tmp_path, data))


def test_unknown_permission_in_system_role_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["system_roles"][SystemRole.TEAM_LEAD.value]["permissions"].append(
        "urn:smart-ticket:perm:teams:ghost"
    )
    with pytest.raises(ValidationError):
        load_catalog(_write(tmp_path, data))


def test_employee_holding_staff_only_permission_fails_validation(tmp_path: Path):
    data = copy.deepcopy(_baseline())
    data["system_roles"][SystemRole.EMPLOYEE.value]["permissions"].append(
        Permission.INFRA_READ.value
    )
    with pytest.raises(ValidationError, match="staff-only"):
        load_catalog(_write(tmp_path, data))


def test_duplicate_json_key_fails_validation(tmp_path: Path):
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    target = f'"{Permission.INFRA_READ.value}": {{'
    duplicate = (
        f'"{Permission.INFRA_READ.value}": {{"label": "Duplicate"}},\n    '
        f'"{Permission.INFRA_READ.value}": {{'
    )
    assert target in raw
    path = tmp_path / "catalog.json"
    path.write_text(raw.replace(target, duplicate, 1), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key"):
        load_catalog(path)
