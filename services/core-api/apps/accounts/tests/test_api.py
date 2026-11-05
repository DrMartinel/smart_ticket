"""
Account endpoints over HTTP. The response schema decides what the web
receives, so a field renamed or dropped there changes the JSON with no error
on the server. The keys the web reads are pinned here.
"""

import pytest

from apps.accounts.utils.catalog import SYSTEM_ROLE_PERMISSIONS, SystemRole


@pytest.mark.django_db
def test_me_returns_the_authenticated_user(employee_user, api_as):
    response = api_as(employee_user).get("/api/accounts/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(employee_user.id),
        "username": "emp",
        "email": "",
        "role": "employee",
        "auth_source": "local",
        "language": "vi",
        "capabilities": [],
        "teams": [],
        "permissions": sorted(p.value for p in SYSTEM_ROLE_PERMISSIONS[SystemRole.EMPLOYEE]),
        "permissions_everywhere": sorted(
            p.value for p in SYSTEM_ROLE_PERMISSIONS[SystemRole.EMPLOYEE]
        ),
        "status": "active",
        "name": "",
        "department": None,
        "line_manager": None,
        "job_title": "",
        "location": "",
    }
