# pyright: standard
"""
Account endpoints over HTTP. The response schema decides what the web
receives, so a field renamed or dropped there changes the JSON with no error
on the server. The keys the web reads are pinned here.
"""

import pytest


@pytest.mark.django_db
def test_me_returns_the_authenticated_user(employee_user, api_as):
    response = api_as(employee_user).get("/api/accounts/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": employee_user.id,
        "username": "emp",
        "email": "",
        "role": "employee",
    }
