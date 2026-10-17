"""The staff board: a workflow's tickets by status, and who may see it."""

import pytest

from apps.lifecycle.tests.conftest import make_ticket, put_in

pytestmark = pytest.mark.django_db


def test_the_board_holds_only_the_workflows_tickets(api_as, employee_user, technician_user, strict):
    elsewhere = make_ticket(employee_user)
    here = put_in(make_ticket(employee_user), strict.working)

    client = api_as(technician_user)
    board = client.get(f"/api/tickets/board?workflow={strict.workflow.id}").json()

    assert [r["public_id"] for r in board["items"]] == [here.public_id]
    assert board["items"][0]["status"]["key"] == strict.working.key
    assert board["counts"] == {strict.working.key: 1}
    assert elsewhere.public_id not in [r["public_id"] for r in board["items"]]


def test_a_full_column_still_reports_its_whole_count(
    api_as, employee_user, technician_user, strict
):
    for _ in range(3):
        put_in(make_ticket(employee_user), strict.working)
    put_in(make_ticket(employee_user), strict.hold)

    board = (
        api_as(technician_user)
        .get(f"/api/tickets/board?workflow={strict.workflow.id}&per_column=2")
        .json()
    )

    keys = [r["status"]["key"] for r in board["items"]]
    assert keys.count(strict.working.key) == 2 and keys.count(strict.hold.key) == 1
    assert board["counts"] == {strict.working.key: 3, strict.hold.key: 1}


def test_a_requester_cannot_see_the_board(api_as, employee_user, strict):
    response = api_as(employee_user).get(f"/api/tickets/board?workflow={strict.workflow.id}")

    assert response.status_code == 403
