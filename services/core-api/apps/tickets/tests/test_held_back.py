"""Whether a routing decision was held back, read off its branch and snapshot (ADR-0051)."""

from __future__ import annotations

from typing import Any

import pytest

from apps.accounts.models import User, UserRole
from apps.lifecycle.tests.conftest import make_ticket
from apps.rollout.domain.vocabulary import BRANCH_FLAG
from apps.tickets.domain.router import Branch
from apps.tickets.models import RoutingDecision

pytestmark = pytest.mark.django_db

UNFLAGGED = [b.value for b in Branch if b.value not in BRANCH_FLAG]


@pytest.fixture
def reporter(db) -> User:
    return User.objects.create_user(
        username="lan.nt", password="x", role=UserRole.EMPLOYEE.value, email="lan@example.test"
    )


def recorded(reporter: User, branch: str, snapshot: dict[str, Any]) -> RoutingDecision:
    return RoutingDecision.objects.create(
        ticket=make_ticket(reporter),
        branch=branch,
        reason_code="all_checks_passed",
        reason_detail="",
        thresholds_used={},
        rollout_snapshot=snapshot,
    )


def snapshots(flag: str) -> list[dict[str, Any]]:
    """Every shape a stored snapshot takes for one flag."""
    return [{flag: "on"}, {flag: "off"}, {"thresholds": "v"}, {}]


def test_the_mapping_names_every_flagged_branch_of_the_router():
    assert set(BRANCH_FLAG) <= {b.value for b in Branch}
    assert set(BRANCH_FLAG) == {"auto_route", "auto_reply", "clarify"}


@pytest.mark.parametrize("branch", UNFLAGGED)
def test_a_branch_with_no_flag_is_never_held_back(reporter, branch):
    rows = [recorded(reporter, branch, s) for s in snapshots("auto_route")]

    assert not any(row.was_held_back() for row in rows)
    assert not RoutingDecision.objects.held_back().exists()
    assert RoutingDecision.objects.carried_out().count() == len(rows)


@pytest.mark.parametrize("branch", sorted(BRANCH_FLAG))
def test_a_snapshot_missing_the_flag_is_held_back(reporter, branch):
    other = next(f for f in BRANCH_FLAG.values() if f is not BRANCH_FLAG[branch])

    missing = recorded(reporter, branch, {other.value: "on"})
    empty = recorded(reporter, branch, {})

    assert missing.was_held_back() and empty.was_held_back()
    assert set(RoutingDecision.objects.held_back()) == {missing, empty}


@pytest.mark.parametrize("branch", sorted(BRANCH_FLAG))
def test_only_the_flag_on_carries_a_decision_out(reporter, branch):
    flag = BRANCH_FLAG[branch].value

    on = recorded(reporter, branch, {flag: "on"})
    off = recorded(reporter, branch, {flag: "off"})

    assert (on.was_held_back(), off.was_held_back()) == (False, True)
    assert list(RoutingDecision.objects.carried_out()) == [on]


def test_held_back_and_was_held_back_agree(reporter):
    """The queryset and the model method give the same answer for every branch and shape."""
    rows = [
        recorded(reporter, branch.value, snapshot)
        for branch in Branch
        for flag in BRANCH_FLAG.values()
        for snapshot in snapshots(flag.value)
    ]

    held = set(RoutingDecision.objects.held_back().values_list("id", flat=True))
    carried = set(RoutingDecision.objects.carried_out().values_list("id", flat=True))

    assert held == {row.id for row in rows if row.was_held_back()}
    assert carried == {row.id for row in rows if not row.was_held_back()}
    assert held and carried
