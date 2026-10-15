"""Executes one action run: claims it, fills its parameters' placeholders, calls its handler."""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.lifecycle.models import ActionRun, Transfer, Workflow
from apps.lifecycle.utils.actions import (
    HANDLERS,
    ActionContext,
    ActionError,
    RetryableActionError,
)
from apps.lifecycle.utils.fields import field_values
from apps.lifecycle.utils.templates import render, render_json
from apps.lifecycle.utils.vocabulary import ActionCode, FailureCode, RunState
from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"
    RETRY = "retry"
    AWAITING = "awaiting"
    # Another worker claimed the run first.
    OWNED = "owned"


class ActionRunner:
    """Runs action runs, one at a time, recording each outcome on its row."""

    def execute(self, run_id: uuid.UUID) -> Outcome:
        claimed = ActionRun.objects.filter(pk=run_id, state=RunState.QUEUED.value).update(
            state=RunState.RUNNING.value, attempt=F("attempt") + 1, started_at=timezone.now()
        )
        if not claimed:
            return Outcome.OWNED
        run = ActionRun.objects.select_related("transfer").get(pk=run_id)
        ticket = Ticket.objects.select_related(
            "reporter", "assigned_to", "workflow_status__base"
        ).get(pk=run.ticket_id)
        workflow = Workflow.objects.of_ticket(ticket)
        handler = HANDLERS[ActionCode(run.action)]

        unknown: list[str] = []
        variables = self.variables(ticket, run.transfer, workflow)
        try:
            run.resolved_params = {
                name: render_json(value, variables, unknown)
                if name in handler.json_params
                else render(value, variables, unknown)
                for name, value in run.params.items()
            }
        except ValueError as e:
            return self.fail(run, FailureCode.INVALID_PARAM, f"not a JSON template: {e}")
        try:
            with transaction.atomic():
                params = handler.parse(run.resolved_params)
                result = handler.execute(params, ActionContext(run, ticket, run.transfer, workflow))
        except RetryableActionError as e:
            if run.attempt < settings.THRESHOLDS.lifecycle.action_max_attempts:
                run.error = str(e)
                return self.finish(
                    run,
                    Outcome.RETRY,
                    state=RunState.QUEUED.value,
                    error=run.error,
                    resolved_params=run.resolved_params,
                )
            return self.fail(run, FailureCode.ACTION_FAILED, str(e))
        except ActionError as e:
            return self.fail(run, e.code, str(e))
        except Exception as e:  # noqa: BLE001 — a crashing handler fails its run, never its worker
            logger.exception("lifecycle action %s crashed on run %s", run.action, run.id)
            return self.fail(run, FailureCode.ACTION_CRASHED, f"{type(e).__name__}: {e}")

        run.output = {**result.output, **({"warnings": unknown} if unknown else {})}
        if result.abort is not None:
            return self.fail(run, FailureCode.ACTION_ABORTED, result.abort, outcome=Outcome.ABORTED)
        if result.awaiting_until is not None:
            return self.finish(
                run,
                Outcome.AWAITING,
                awaiting_until=result.awaiting_until,
                output=run.output,
                resolved_params=run.resolved_params,
            )
        return self.finish(
            run,
            Outcome.SUCCEEDED,
            state=RunState.SUCCEEDED.value,
            finished_at=timezone.now(),
            error="",
            output=run.output,
            resolved_params=run.resolved_params,
        )

    def fail(
        self, run: ActionRun, code: FailureCode, message: str, *, outcome: Outcome = Outcome.FAILED
    ) -> Outcome:
        """Records `run` as failed with `code`, unless it stopped running meanwhile."""
        return self.finish(
            run,
            outcome,
            state=RunState.FAILED.value,
            error_code=code.value,
            error=message,
            finished_at=timezone.now(),
            awaiting_until=None,
            output=run.output,
            resolved_params=run.resolved_params,
        )

    def finish(self, run: ActionRun, outcome: Outcome, **fields: Any) -> Outcome:
        """Writes `fields` to a run still running and returns `outcome`; returns `OWNED` when the
        run was cancelled or finished elsewhere meanwhile."""
        written = ActionRun.objects.filter(pk=run.pk, state=RunState.RUNNING.value).update(**fields)
        if not written:
            return Outcome.OWNED
        for name, value in fields.items():
            setattr(run, name, value)
        return outcome

    def variables(
        self, ticket: Ticket, transfer: Transfer | None, workflow: Workflow
    ) -> dict[str, str]:
        """The placeholder values an action may use: masked ticket text, never quarantined PII."""
        status = ticket.workflow_status
        now = timezone.now()
        variables = {
            "ticket.id": ticket.public_id,
            "ticket.subject": ticket.subject_masked,
            "ticket.body": ticket.body_masked,
            "ticket.status": ticket.status,
            "ticket.statusName": status.name if status else ticket.status,
            "ticket.baseStatus": status.base.name if status else "",
            "ticket.workflow": workflow.name,
            "ticket.category": ticket.category or "",
            "ticket.assignedTeam": ticket.assigned_team or "",
            "ticket.assignee": ticket.assigned_to.username if ticket.assigned_to else "",
            "ticket.reporter": ticket.reporter.username,
            "ticket.reporterEmail": ticket.reporter.email,
            "ticket.piiLevel": ticket.pii_level,
            "ticket.source": ticket.source,
            "ticket.slaDueAt": ticket.sla_due_at.isoformat() if ticket.sla_due_at else "",
            "ticket.createdAt": ticket.created_at.isoformat(),
            "now": now.isoformat(),
            "today": timezone.localdate().isoformat(),
        }
        if transfer is not None:
            before, after = transfer.before_status, transfer.after_status
            variables |= {
                "transfer.id": str(transfer.id),
                "transfer.trigger": transfer.trigger,
                "transfer.direction": transfer.direction or "",
                "transfer.by": transfer.actor.username if transfer.actor else "system",
                "transfer.beforeStatus": before.name if before else "",
                "transfer.beforeStatusKey": before.key if before else "",
                "transfer.afterStatus": after.name if after else "",
                "transfer.afterStatusKey": after.key if after else "",
            }
        values = field_values.by_name(ticket)
        for field in workflow.fields.all():
            value = values.get(field.name)
            variables[f"field.{field.name}"] = "" if value is None else str(value)
        return variables


# --- the action runner ---

runner = ActionRunner()
