"""Which workflow a ticket enters at handoff: rules in order, then its category's, then the
default. No database."""

from __future__ import annotations

import uuid

from apps.lifecycle.domain.selection import select_workflow
from apps.lifecycle.models import WorkflowRule

CATEGORY_WF = uuid.uuid4()
DEFAULT_WF = uuid.uuid4()


def rule(
    order: int,
    *,
    category: str | None = None,
    branch: str | None = None,
    priority: str | None = None,
    active: bool = True,
) -> WorkflowRule:
    return WorkflowRule(
        id=uuid.uuid4(),
        order=order,
        category_id=category,
        branch=branch,
        priority=priority,
        workflow_id=uuid.uuid4(),
        is_active=active,
    )


def select(
    rules, category="network", branch="auto_route", priority="P1", *, category_wf=CATEGORY_WF
):
    return select_workflow(
        rules,
        category,
        branch,
        priority,
        category_workflow=category_wf,
        default_workflow=DEFAULT_WF,
    )


def test_the_first_matching_rule_in_order_wins_over_a_later_one():
    later = rule(2, category="network")
    first = rule(1, priority="P1")

    chosen = select([later, first])

    assert (chosen.workflow_id, chosen.selected_by, chosen.rule) == (
        first.workflow_id,
        str(first.id),
        first,
    )


def test_a_null_key_matches_any_value():
    anything = rule(1)

    assert select([anything], category=None, branch=None, priority=None).rule == anything


def test_a_rule_needs_every_key_it_sets_to_match():
    p1_network = rule(1, category="network", priority="P1")

    assert select([p1_network], priority="P2").rule is None
    assert select([p1_network], category="software").rule is None
    assert select([p1_network]).rule == p1_network


def test_a_branch_rule_does_not_match_another_branch():
    reviewed = rule(1, branch="hitl")

    assert select([reviewed], branch="auto_route").rule is None
    assert select([reviewed], branch="hitl").rule == reviewed


def test_a_rule_does_not_match_a_ticket_missing_that_key():
    p1 = rule(1, priority="P1")

    assert select([p1], priority=None).rule is None


def test_an_inactive_rule_is_skipped():
    off = rule(1, category="network", active=False)
    on = rule(2, category="network")

    assert select([off, on]).rule == on


def test_a_preview_can_count_an_inactive_rule():
    off = rule(1, category="network", active=False)

    chosen = select_workflow(
        [off],
        "network",
        "auto_route",
        "P1",
        category_workflow=CATEGORY_WF,
        default_workflow=DEFAULT_WF,
        include_inactive=True,
    )

    assert chosen.rule == off


def test_no_matching_rule_falls_back_to_the_categorys_workflow():
    chosen = select([rule(1, priority="P4")])

    assert (chosen.workflow_id, chosen.selected_by, chosen.rule) == (CATEGORY_WF, "category", None)


def test_no_matching_rule_and_no_category_keeps_the_current_workflow():
    chosen = select([rule(1, category="network")], category=None)

    assert (chosen.workflow_id, chosen.selected_by, chosen.rule) == (None, "current", None)


def test_no_rules_and_no_category_workflow_gives_the_default():
    chosen = select([], category_wf=None)

    assert (chosen.workflow_id, chosen.selected_by) == (DEFAULT_WF, "default")
