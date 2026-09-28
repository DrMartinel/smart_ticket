# pyright: standard
"""
Runbook execution — ADR-0006. The router sends every RunbookProposal to a
human; `RunbookExecution.objects.execute` is the second, independent check,
so a bug upstream (an item in the wrong queue, a rejection mistaken for an
approval, a draft the LLM filled in wrongly) still cannot reach a live
system.

Each refusal below would otherwise fail in the worst way available: the
runbook simply runs.
"""

import pytest

from apps.tickets.utils.patterns import PIILevel
from apps.review.models import ReviewAction, ReviewDecision, ReviewItem
from apps.tickets.utils.router import ReviewQueue

from apps.itsm_mock.models import RunbookError, RunbookExecution
from apps.tickets.models import AiRun, Ticket

RESET_PASSWORD = {
    "runbook_id": "RB-RESET-PASSWORD",
    "draft_payload": {"target_username": "an.nguyen"},
}


def runbook_item(reporter, draft=RESET_PASSWORD, queue=ReviewQueue.RUNBOOK_APPROVAL):
    ticket = Ticket.objects.create(
        public_id="TKT-RB-001",
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )
    ai_run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="test",
        model="test",
        graph_version="test",
        trust_signals={},
        proposed_draft=draft,
    )
    return ReviewItem.objects.create(ticket=ticket, ai_run=ai_run, queue=queue.value)


def record_decision(item, reviewer, action: ReviewAction) -> None:
    ReviewDecision.objects.create(
        review_item=item,
        reviewer=reviewer,
        action_taken=action.value,
        override_reason=None if action is ReviewAction.APPROVE else "not safe to run",
        time_spent_sec=30,
    )


def assert_refused(item, executor, match: str) -> None:
    with pytest.raises(RunbookError, match=match):
        RunbookExecution.objects.execute(review_item=item, executed_by=executor)
    assert not RunbookExecution.objects.exists()


@pytest.mark.django_db
class TestRefusals:
    def test_no_decision_at_all(self, employee_user, technician_user):
        item = runbook_item(employee_user)

        assert_refused(item, technician_user, "NEVER execute without human approval")

    def test_a_rejection_is_not_an_approval(self, employee_user, technician_user):
        item = runbook_item(employee_user)
        record_decision(item, technician_user, ReviewAction.REJECT)

        assert_refused(item, technician_user, "NEVER execute without human approval")

    def test_an_approval_outside_the_runbook_queue(self, employee_user, technician_user):
        """An approved auto-reply draft is not an approved runbook."""
        item = runbook_item(employee_user, queue=ReviewQueue.LOW_CONFIDENCE)
        record_decision(item, technician_user, ReviewAction.APPROVE)

        assert_refused(item, technician_user, "not a runbook_approval item")

    def test_a_runbook_the_registry_does_not_know(self, employee_user, technician_user):
        item = runbook_item(employee_user, draft={"runbook_id": "RB-DROP-DATABASE"})
        record_decision(item, technician_user, ReviewAction.APPROVE)

        assert_refused(item, technician_user, "unknown runbook_id")

    def test_a_draft_missing_required_fields(self, employee_user, technician_user):
        item = runbook_item(
            employee_user, draft={"runbook_id": "RB-RESET-PASSWORD", "draft_payload": {}}
        )
        record_decision(item, technician_user, ReviewAction.APPROVE)

        assert_refused(item, technician_user, "missing required fields")


@pytest.mark.django_db
def test_an_approved_runbook_is_recorded_as_a_simulated_run(employee_user, technician_user):
    item = runbook_item(employee_user)
    record_decision(item, technician_user, ReviewAction.APPROVE)

    execution = RunbookExecution.objects.execute(review_item=item, executed_by=technician_user)

    assert execution.runbook_id == "RB-RESET-PASSWORD"
    assert execution.payload == {"target_username": "an.nguyen"}
    assert execution.executed_by == technician_user
    assert execution.result["simulated"] is True
