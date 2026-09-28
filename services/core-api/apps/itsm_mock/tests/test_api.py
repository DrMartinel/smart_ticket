# pyright: standard
"""
Mock ITSM endpoints over HTTP. The response schema decides what the web
receives, so the keys are pinned here, and a refused runbook must reach the
caller as a 422, not a 500.
"""

import pytest

from apps.review.models import ReviewAction

from apps.itsm_mock.models import RUNBOOK_REGISTRY
from apps.itsm_mock.tests.test_execute_runbook import record_decision, runbook_item


@pytest.mark.django_db
def test_runbooks_are_listed_by_id(technician_user, api_as):
    response = api_as(technician_user).get("/api/itsm/runbooks")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(RUNBOOK_REGISTRY)
    assert all(set(spec) == {"title", "required_fields"} for spec in body.values())


@pytest.mark.django_db
def test_an_approved_runbook_execution_is_returned(employee_user, technician_user, api_as):
    item = runbook_item(employee_user)
    record_decision(item, technician_user, ReviewAction.APPROVE)

    response = api_as(technician_user).post(f"/api/itsm/review-items/{item.id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "runbook_id", "status", "result"}
    assert body["runbook_id"] == "RB-RESET-PASSWORD"
    assert body["result"]["simulated"] is True


@pytest.mark.django_db
def test_an_unapproved_runbook_is_a_422(employee_user, technician_user, api_as):
    item = runbook_item(employee_user)

    response = api_as(technician_user).post(f"/api/itsm/review-items/{item.id}/execute")

    assert response.status_code == 422
