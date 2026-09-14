"""
Runbook registry + execution. A tiny fixed set of "runbooks" simulating
real ITSM actions — this is a mock, so the "execution" is just recording a
plausible result, not calling a real system.
"""

from __future__ import annotations

from django.db import transaction

from apps.itsm_mock.models import RunbookExecution
from apps.review.models import ReviewItem

RUNBOOK_REGISTRY: dict[str, dict] = {
    "RB-RESET-PASSWORD": {
        "title": "Reset user password",
        "required_fields": ["target_username"],
    },
    "RB-GRANT-ACCESS": {
        "title": "Grant application access",
        "required_fields": ["target_username", "application", "access_level"],
    },
    "RB-RESTART-SERVICE": {
        "title": "Restart a service",
        "required_fields": ["service_name", "host"],
    },
}


class RunbookError(Exception):
    pass


@transaction.atomic
def execute_runbook(*, review_item: ReviewItem, executed_by) -> RunbookExecution:
    """ADR-0006, enforced here as a second, independent check beyond the
    router: this refuses to run unless an actual approving decision exists
    on this review item, regardless of how the caller got here."""

    approving_decision = (
        review_item.decisions.filter(action_taken="approve").order_by("-decided_at").first()
    )
    if approving_decision is None:
        raise RunbookError(
            "no approving review_decisions row for this review item — "
            "runbooks NEVER execute without human approval (ADR-0006)"
        )
    if review_item.queue != "runbook_approval":
        raise RunbookError("review item is not a runbook_approval item")

    ai_run = review_item.ai_run
    draft = (ai_run.proposed_draft or {}) if ai_run else {}
    runbook_id = draft.get("runbook_id")
    payload = draft.get("draft_payload", {})

    spec = RUNBOOK_REGISTRY.get(runbook_id)
    if spec is None:
        raise RunbookError(f"unknown runbook_id: {runbook_id!r}")

    missing = [f for f in spec["required_fields"] if f not in payload]
    if missing:
        raise RunbookError(f"runbook {runbook_id} missing required fields: {missing}")

    result = {"simulated": True, "runbook": spec["title"], "applied_payload": payload}

    return RunbookExecution.objects.create(
        ticket=review_item.ticket,
        review_item=review_item,
        runbook_id=runbook_id,
        payload=payload,
        executed_by=executed_by,
        result=result,
        status="succeeded",
    )
