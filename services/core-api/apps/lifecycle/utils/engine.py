"""
Moves tickets between workflow statuses (ADR-0028): the pipeline's moves,
which nothing in a workflow can refuse, and people's and actions' moves,
which the workflow's transitions and rules govern and whose actions run on
Celery.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.lifecycle.models import (
    ActionRun,
    ApprovalRequest,
    SystemStatus,
    Transfer,
    TransitionRule,
    Workflow,
    WorkflowStatus,
)
from apps.lifecycle.utils.actions import callback_token
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.fields import field_values, violation_detail
from apps.lifecycle.utils.resolver import (
    MoveOption,
    Resolution,
    allowed_moves,
    plan_runs,
    resolve,
)
from apps.lifecycle.utils.rules import ConfiguredRule, RuleCode, RuleViolation, violations
from apps.lifecycle.utils.runner import Outcome, runner
from apps.lifecycle.utils.vocabulary import (
    DONE_RUN_STATES,
    TRANSFER_PHASES,
    ApprovalState,
    FailureCode,
    Phase,
    PipelineStatus,
    RunState,
    TransferState,
    Trigger,
)
from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)

# Ticket fields a move changes, copied back onto a caller's stale instance.
_MOVED_FIELDS = ("workflow_status", "status", "version", "resolved_at", "waiting_transform")


@dataclass(frozen=True)
class Adoption:
    """How many tickets a workflow change moved, and how many it skipped mid-move."""

    moved: int
    skipped: int


class Lifecycle:
    """Every status change of every ticket, and the action runs those changes start."""

    # ── where a ticket can go ──

    def options(self, ticket: Ticket) -> list[MoveOption]:
        """The statuses a person may move `ticket` to now."""
        workflow = Workflow.objects.of_ticket(ticket)
        return allowed_moves(
            current=WorkflowStatus.objects.of_ticket(ticket),
            workflow=workflow,
            statuses=list(workflow.statuses.select_related("base")),
            transitions=list(workflow.transitions.prefetch_related("rules")),
        )

    # ── the pipeline's moves ──

    def start(self, ticket: Ticket) -> None:
        """Puts a newly submitted ticket at `new` in the default workflow."""
        self.system_move(ticket, PipelineStatus.NEW, trigger=Trigger.CREATE)

    def system_move(
        self, ticket: Ticket, status: PipelineStatus, *, trigger: Trigger = Trigger.SYSTEM
    ) -> None:
        """Moves `ticket` to a pipeline status, cancelling any move in flight, and updates the
        caller's instance."""
        with transaction.atomic():
            locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
            current = WorkflowStatus.objects.of_ticket(locked)
            workflow = current.workflow if current else Workflow.objects.default()
            target = self.pipeline_status(workflow, status)
            self.cancel_open(locked, f"the triage pipeline moved the ticket to {status.value!r}")
            if locked.workflow_status_id != target.id or locked.status != target.key:
                before = None if trigger is Trigger.CREATE else current
                self.record_system_transfer(locked, before, target, trigger=trigger, actor=None)
        for name in _MOVED_FIELDS:
            setattr(ticket, name, getattr(locked, name))

    def pipeline_status(self, workflow: Workflow, status: PipelineStatus) -> WorkflowStatus:
        """The workflow's status for `status`, recreated if it has gone missing."""
        found = workflow.statuses.select_related("base").filter(key=status.value).first()
        if found is not None:
            return found
        logger.warning("workflow %s lost pipeline status %s; recreating it", workflow.id, status)
        template = (
            WorkflowStatus.objects.filter(workflow__is_default=True, key=status.value)
            .select_related("base")
            .first()
        )
        base = template.base if template else SystemStatus.objects.order_by("order").first()
        if base is None:
            raise RuntimeError("no system status exists; run the lifecycle migrations")
        return WorkflowStatus.objects.create(
            workflow=workflow,
            base=base,
            key=status.value,
            name=template.name if template else status.value,
            color=template.color if template else base.color,
            order=template.order if template else 0,
        )

    def cancel_open(self, ticket: Ticket, reason: str) -> None:
        """Cancels `ticket`'s transfer in flight and skips its remaining runs."""
        now = timezone.now()
        open_ids = list(ticket.transfers.open().values_list("id", flat=True))
        if not open_ids:
            return
        Transfer.objects.filter(id__in=open_ids).update(
            state=TransferState.CANCELLED.value,
            failure_code=FailureCode.SUPERSEDED_BY_PIPELINE.value,
            failure_reason=reason,
            finished_at=now,
        )
        ActionRun.objects.filter(
            transfer_id__in=open_ids, state__in=[RunState.QUEUED.value, RunState.RUNNING.value]
        ).update(state=RunState.SKIPPED.value, finished_at=now, awaiting_until=None)
        ApprovalRequest.objects.filter(
            run__transfer_id__in=open_ids, state=ApprovalState.PENDING.value
        ).update(state=ApprovalState.REJECTED.value, decided_at=now, comment=reason)
        ticket.waiting_transform = False
        ticket.save(update_fields=["waiting_transform"])

    def record_system_transfer(
        self,
        ticket: Ticket,
        current: WorkflowStatus | None,
        target: WorkflowStatus,
        *,
        trigger: Trigger,
        actor: User | None,
        extra: Mapping[str, Any] | None = None,
    ) -> Transfer:
        """Moves a locked ticket at once, with no rules and no actions."""
        now = timezone.now()
        transfer = Transfer.objects.create(
            ticket=ticket,
            actor=actor,
            trigger=trigger.value,
            before_status=current,
            after_status=target,
            state=TransferState.COMPLETED.value,
            committed_at=now,
            finished_at=now,
        )
        ticket.enter_status(target)
        self.audit_status_change(ticket, transfer, current, target, extra=extra)
        return transfer

    # ── people's and actions' moves ──

    def move(
        self,
        ticket_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        actor: User,
        force: bool,
        expected_version: int | None,
    ) -> Ticket:
        """A person's move: committed now, or queued behind its `before` actions."""
        self.request_move(
            ticket_id,
            target_id,
            actor=actor,
            trigger=Trigger.FORCE if force else Trigger.MANUAL,
            expected_version=expected_version,
        )
        return Ticket.objects.select_related("workflow_status").get(pk=ticket_id)

    def request_move(
        self,
        ticket_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        actor: User | None,
        trigger: Trigger,
        depth: int = 0,
        parent: Transfer | None = None,
        expected_version: int | None = None,
    ) -> Transfer | None:
        """Checks and records a move, plans its runs, and commits it unless `before` runs must
        succeed first; None when the ticket is already at the target."""
        try:
            with transaction.atomic():
                ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
                if ticket.waiting_transform or ticket.transfers.open().exists():
                    raise LifecycleError(
                        409,
                        FailureCode.TICKET_TRANSFORMING,
                        "the ticket's last move is still running",
                    )
                if expected_version is not None and ticket.version != expected_version:
                    raise LifecycleError(
                        409,
                        FailureCode.VERSION_CONFLICT,
                        f"the ticket is at version {ticket.version}, not {expected_version}",
                    )
                current = WorkflowStatus.objects.of_ticket(ticket)
                workflow = current.workflow if current else Workflow.objects.of_ticket(ticket)
                target = (
                    WorkflowStatus.objects.select_related("base")
                    .prefetch_related("actions")
                    .filter(pk=target_id)
                    .first()
                )
                if target is None:
                    raise LifecycleError(404, FailureCode.STATUS_NOT_IN_WORKFLOW, "no such status")
                resolution = resolve(
                    current=current,
                    target=target,
                    workflow=workflow,
                    transitions=list(
                        workflow.transitions.prefetch_related("rules__field", "actions")
                    ),
                    trigger=trigger,
                )
                if resolution is None:
                    return None
                if resolution.transition is not None and trigger is not Trigger.FORCE:
                    self.check_transition_rules(ticket, resolution, target)
                return self.record_move(
                    ticket, current, target, resolution, actor, trigger, depth, parent
                )
        except IntegrityError as e:
            raise LifecycleError(
                409, FailureCode.TICKET_TRANSFORMING, "the ticket's last move is still running"
            ) from e

    def check_transition_rules(
        self, ticket: Ticket, resolution: Resolution, target: WorkflowStatus
    ) -> None:
        """Raises `RULE_VIOLATION` listing every active rule of the transition the ticket breaks."""
        assert resolution.transition is not None
        rules = [
            ConfiguredRule(str(r.id), RuleCode(r.rule), r.params, str(r.field_id), r.field.name)
            for r in resolution.transition.rules.all()
            if r.is_active
        ]
        found = violations(rules, field_values.of(ticket), field_values.rule_context(ticket))
        if found:
            raise LifecycleError(
                422,
                FailureCode.RULE_VIOLATION,
                f"cannot move to {target.name!r}: " + "; ".join(v.message for v in found),
                details=[violation_detail(v) for v in found],
            )

    def record_move(
        self,
        ticket: Ticket,
        current: WorkflowStatus | None,
        target: WorkflowStatus,
        resolution: Resolution,
        actor: User | None,
        trigger: Trigger,
        depth: int,
        parent: Transfer | None,
    ) -> Transfer:
        """Creates the transfer and its planned runs for a checked move of a locked ticket."""
        transfer = Transfer.objects.create(
            ticket=ticket,
            actor=actor,
            trigger=trigger.value,
            before_status=current,
            after_status=target,
            transition=resolution.transition,
            direction=resolution.direction.value if resolution.direction else None,
            depth=depth,
            parent=parent,
        )
        planned = plan_runs(
            list(resolution.transition.actions.all()) if resolution.transition else [],
            list(target.actions.all()),
        )
        ActionRun.objects.bulk_create(
            ActionRun(
                ticket=ticket,
                transfer=transfer,
                source_action=p.action,
                action=p.action.action,
                params=p.action.params,
                phase=p.phase.value,
                seq=seq,
                depth=depth,
                idempotency_key=f"transfer:{transfer.id}:{seq}",
            )
            for seq, p in enumerate(planned)
        )
        phases = [p.phase for p in planned]
        if Phase.BEFORE not in phases:
            self.commit_locked(ticket, transfer)
        if not phases:
            transfer.state = TransferState.COMPLETED.value
            transfer.finished_at = timezone.now()
            transfer.save(update_fields=["state", "finished_at"])
            return transfer
        ticket.waiting_transform = True
        ticket.save(update_fields=["waiting_transform"])
        self.schedule(transfer.id, phases[0])
        return transfer

    def commit_locked(self, ticket: Ticket, transfer: Transfer) -> None:
        """Puts a locked ticket in its transfer's target status."""
        assert transfer.after_status is not None
        ticket.enter_status(transfer.after_status)
        transfer.state = TransferState.COMMITTED.value
        transfer.committed_at = timezone.now()
        transfer.save(update_fields=["state", "committed_at"])
        self.audit_status_change(ticket, transfer, transfer.before_status, transfer.after_status)

    def audit_status_change(
        self,
        ticket: Ticket,
        transfer: Transfer,
        before: WorkflowStatus | None,
        after: WorkflowStatus,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        AuditLog.objects.record(
            "ticket_status_changed",
            actor_type="human" if transfer.actor_id else "system",
            actor_id=transfer.actor_id,
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "transfer": str(transfer.id),
                "trigger": transfer.trigger,
                "direction": transfer.direction,
                "transition": str(transfer.transition_id) if transfer.transition_id else None,
                "old": {"status": before.key, "status_name": before.name} if before else None,
                "new": {"status": after.key, "status_name": after.name},
                **(extra or {}),
            },
        )

    # ── running a transfer's actions ──

    def run_phase(self, transfer_id: uuid.UUID, phase: Phase) -> None:
        """Runs `phase`'s unfinished runs in order, then moves the transfer on."""
        transfer = Transfer.objects.get(pk=transfer_id)
        expected = TransferState.PENDING if phase is Phase.BEFORE else TransferState.COMMITTED
        if transfer.state != expected.value:
            return
        for run in transfer.runs.filter(phase=phase.value).order_by("seq"):
            if run.state in DONE_RUN_STATES:
                continue
            if run.state == RunState.RUNNING.value:
                return
            if run.state == RunState.FAILED.value:
                if phase is Phase.BEFORE:
                    self.fail(
                        transfer.id, FailureCode(run.error_code or "action_failed"), run.error
                    )
                    return
                continue
            match runner.execute(run.id):
                case Outcome.RETRY:
                    run.refresh_from_db(fields=["attempt"])
                    self.schedule(transfer.id, phase, countdown=self.backoff(run.attempt))
                    return
                case Outcome.AWAITING | Outcome.OWNED:
                    return
                case Outcome.FAILED | Outcome.ABORTED if phase is Phase.BEFORE:
                    run.refresh_from_db(fields=["error_code", "error"])
                    self.fail(
                        transfer.id, FailureCode(run.error_code or "action_failed"), run.error
                    )
                    return
        self.advance(transfer.id, phase)

    def advance(self, transfer_id: uuid.UUID, finished: Phase) -> None:
        """After `finished`, commits a pending transfer and runs the next phase with work, or finalizes."""
        if finished is Phase.BEFORE and not self.commit(transfer_id):
            return
        later = TRANSFER_PHASES[TRANSFER_PHASES.index(finished) + 1 :]
        remaining = set(
            ActionRun.objects.filter(transfer_id=transfer_id, phase__in=[p.value for p in later])
            .exclude(state__in=[s.value for s in DONE_RUN_STATES])
            .values_list("phase", flat=True)
        )
        for phase in later:
            if phase.value in remaining:
                self.run_phase(transfer_id, phase)
                return
        self.finalize(transfer_id)

    def commit(self, transfer_id: uuid.UUID) -> bool:
        """Commits a pending transfer once its `before` runs succeeded; cancels it when the ticket
        moved meanwhile."""
        with transaction.atomic():
            ticket, transfer = self.lock(transfer_id)
            if transfer.state != TransferState.PENDING.value:
                return transfer.state == TransferState.COMMITTED.value
            if ticket.workflow_status_id != transfer.before_status_id:
                self.close(
                    transfer,
                    ticket,
                    TransferState.CANCELLED,
                    FailureCode.STALE_TRANSFER,
                    "the ticket moved while this move waited",
                )
                return False
            broken = self.broken_rules(ticket, transfer)
            if broken:
                self.close(
                    transfer,
                    ticket,
                    TransferState.FAILED,
                    FailureCode.RULE_VIOLATION,
                    "the ticket no longer passes the transition's rules: "
                    + "; ".join(v.message for v in broken),
                )
                return False
            self.commit_locked(ticket, transfer)
            return True

    def lock(self, transfer_id: uuid.UUID) -> tuple[Ticket, Transfer]:
        """Locks a transfer's ticket, then the transfer: the order every lifecycle lock follows."""
        ticket_id = Transfer.objects.values_list("ticket_id", flat=True).get(pk=transfer_id)
        ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
        transfer = (
            Transfer.objects.select_for_update(of=("self",))
            .select_related("before_status", "after_status__base")
            .get(pk=transfer_id)
        )
        return ticket, transfer

    def broken_rules(self, ticket: Ticket, transfer: Transfer) -> list[RuleViolation]:
        """The active rules of the transfer's transition the ticket breaks now; none for a forced move."""
        if transfer.transition_id is None or transfer.trigger == Trigger.FORCE.value:
            return []
        rules = [
            ConfiguredRule(str(r.id), RuleCode(r.rule), r.params, str(r.field_id), r.field.name)
            for r in TransitionRule.objects.filter(
                transition_id=transfer.transition_id, is_active=True
            ).select_related("field")
        ]
        return violations(rules, field_values.of(ticket), field_values.rule_context(ticket))

    def finalize(self, transfer_id: uuid.UUID) -> None:
        """Closes a committed transfer whose runs are done, then makes the moves its actions deferred."""
        with transaction.atomic():
            ticket, transfer = self.lock(transfer_id)
            if transfer.state != TransferState.COMMITTED.value:
                return
            failed = transfer.runs.filter(state=RunState.FAILED.value).order_by("seq").first()
            if failed is not None:
                self.close(
                    transfer,
                    ticket,
                    TransferState.FAILED,
                    FailureCode(failed.error_code or FailureCode.ACTION_FAILED.value),
                    failed.error,
                )
                return
            self.close(transfer, ticket, TransferState.COMPLETED, None, "")
            deferred = [
                run.output
                for run in transfer.runs.filter(state=RunState.SUCCEEDED.value).order_by("seq")
                if run.output
                and ("deferred_move" in run.output or "deferred_workflow" in run.output)
            ]
        for output in deferred:
            self.make_deferred(transfer, output)

    def make_deferred(self, transfer: Transfer, output: Mapping[str, Any]) -> None:
        """Makes a move an action asked for while its own transfer was in flight."""
        try:
            if "deferred_move" in output:
                self.request_move(
                    transfer.ticket_id,
                    uuid.UUID(output["deferred_move"]),
                    actor=None,
                    trigger=Trigger.ACTION,
                    depth=transfer.depth + 1,
                    parent=transfer,
                )
            else:
                self.change_workflow(
                    transfer.ticket_id, uuid.UUID(output["deferred_workflow"]), actor=None
                )
        except LifecycleError as e:
            AuditLog.objects.record(
                "lifecycle_deferred_move_failed",
                actor_type="system",
                ticket_id=transfer.ticket_id,
                payload={"transfer": str(transfer.id), "code": e.code.value, "message": e.message},
            )

    def fail(self, transfer_id: uuid.UUID, code: FailureCode, reason: str) -> None:
        """Fails an open transfer: a pending one never moves the ticket."""
        with transaction.atomic():
            ticket, transfer = self.lock(transfer_id)
            if not transfer.is_open:
                return
            self.close(transfer, ticket, TransferState.FAILED, code, reason)

    def close(
        self,
        transfer: Transfer,
        ticket: Ticket,
        state: TransferState,
        code: FailureCode | None,
        reason: str,
    ) -> None:
        """Ends a locked transfer in `state`, skips its queued runs and unlocks the ticket."""
        now = timezone.now()
        transfer.state = state.value
        transfer.failure_code = code.value if code else None
        transfer.failure_reason = reason
        transfer.finished_at = now
        transfer.save(update_fields=["state", "failure_code", "failure_reason", "finished_at"])
        transfer.runs.filter(state=RunState.QUEUED.value).update(
            state=RunState.SKIPPED.value, finished_at=now
        )
        ticket.waiting_transform = False
        ticket.save(update_fields=["waiting_transform"])
        AuditLog.objects.record(
            f"lifecycle_transfer_{state.value}",
            actor_type="system",
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "transfer": str(transfer.id),
                "failure_code": transfer.failure_code,
                "reason": reason,
            },
        )

    def resume(self, run: ActionRun) -> None:
        """Continues the phase of a transfer run that finished outside a worker."""
        if run.transfer_id is not None:
            self.schedule(run.transfer_id, Phase(run.phase))

    def retry(self, ticket_id: uuid.UUID, actor: User) -> Transfer:
        """Re-runs every unfinished run of the ticket's last failed or stalled transfer."""
        try:
            with transaction.atomic():
                ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
                latest = ticket.transfers.order_by("-created_at").first()
                retryable = (
                    TransferState.FAILED.value,
                    TransferState.PENDING.value,
                    TransferState.COMMITTED.value,
                )
                if latest is None or latest.state not in retryable:
                    raise LifecycleError(404, FailureCode.NOTHING_TO_RETRY, "nothing to retry")
                expected_at = (
                    latest.after_status_id if latest.committed_at else latest.before_status_id
                )
                if ticket.workflow_status_id != expected_at:
                    raise LifecycleError(
                        409, FailureCode.STALE_TRANSFER, "the ticket has moved since this transfer"
                    )
                latest = Transfer.objects.select_for_update(of=("self",)).get(pk=latest.pk)
                if latest.is_open:
                    return self.resume_stalled(latest)
                latest.runs.exclude(state=RunState.SUCCEEDED.value).update(
                    state=RunState.QUEUED.value,
                    attempt=0,
                    error="",
                    error_code=None,
                    awaiting_until=None,
                    finished_at=None,
                )
                committed = latest.committed_at is not None
                latest.state = (
                    TransferState.COMMITTED if committed else TransferState.PENDING
                ).value
                latest.failure_code = None
                latest.failure_reason = ""
                latest.finished_at = None
                latest.save(
                    update_fields=["state", "failure_code", "failure_reason", "finished_at"]
                )
                ticket.waiting_transform = True
                ticket.save(update_fields=["waiting_transform"])
                AuditLog.objects.record(
                    "lifecycle_transfer_retried",
                    actor_type="human",
                    actor_id=actor.id,
                    ticket_id=ticket.id,
                    payload={"ticket_public_id": ticket.public_id, "transfer": str(latest.id)},
                )
                self.schedule(latest.id, Phase.ENTER if committed else Phase.BEFORE)
                return latest
        except IntegrityError as e:
            raise LifecycleError(
                409, FailureCode.TICKET_TRANSFORMING, "another move of the ticket is running"
            ) from e

    def resume_stalled(self, transfer: Transfer) -> Transfer:
        """Re-queues an open transfer whose work was lost; refuses one with a run in progress."""
        if transfer.runs.filter(state=RunState.RUNNING.value).exists():
            raise LifecycleError(
                409,
                FailureCode.TRANSFER_IN_PROGRESS,
                "an action of this move is still running or waiting for an answer",
            )
        pending = transfer.state == TransferState.PENDING.value
        self.schedule(transfer.id, Phase.BEFORE if pending else Phase.ENTER)
        return transfer

    # ── changing workflow ──

    def change_workflow(
        self, ticket_id: uuid.UUID, target_id: uuid.UUID, *, actor: User | None
    ) -> Ticket:
        """Moves a ticket into another workflow's status, carrying its field values over."""
        with transaction.atomic():
            ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
            if ticket.waiting_transform or ticket.transfers.open().exists():
                raise LifecycleError(
                    409, FailureCode.TICKET_TRANSFORMING, "the ticket's last move is still running"
                )
            current = WorkflowStatus.objects.of_ticket(ticket)
            if current is not None and current.is_triage:
                raise LifecycleError(
                    409, FailureCode.TICKET_IN_TRIAGE, f"the ticket is at {current.key!r}"
                )
            target = (
                WorkflowStatus.objects.select_related("base", "workflow")
                .filter(pk=target_id)
                .first()
            )
            if target is None:
                raise LifecycleError(404, FailureCode.NOT_FOUND, "no such status")
            if current is not None and target.workflow_id == current.workflow_id:
                raise LifecycleError(
                    422,
                    FailureCode.SAME_WORKFLOW,
                    "the ticket is already in this workflow: move it instead",
                )
            if target.is_pipeline:
                raise LifecycleError(
                    422,
                    FailureCode.PIPELINE_STATUS_TARGET,
                    f"only the triage pipeline moves a ticket into {target.key!r}",
                )
            dropped = field_values.carry_over(ticket, target.workflow)
            self.record_system_transfer(
                ticket,
                current,
                target,
                trigger=Trigger.SYSTEM,
                actor=actor,
                extra={"workflow": target.workflow.name, "dropped_fields": dropped},
            )
        return ticket

    def adopt_tickets(
        self,
        source: Workflow,
        target: Workflow,
        mapping: Mapping[uuid.UUID, uuid.UUID],
        *,
        actor: User,
    ) -> Adoption:
        """Moves every ticket in `source` into `target`, status by status: a pipeline status to
        the same pipeline status, any other by `mapping` or else by key."""
        if source.id == target.id:
            raise LifecycleError(422, FailureCode.SAME_WORKFLOW, "source and target are the same")
        destinations = self.destinations(source, target, mapping)
        moved = skipped = 0
        ticket_ids = list(
            Ticket.objects.filter(workflow_status__workflow=source).values_list("id", flat=True)
        )
        for ticket_id in ticket_ids:
            with transaction.atomic():
                ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
                current = WorkflowStatus.objects.of_ticket(ticket)
                if current is None or current.workflow_id != source.id:
                    continue
                if ticket.waiting_transform or ticket.transfers.open().exists():
                    skipped += 1
                    continue
                dropped = field_values.carry_over(ticket, target)
                self.record_system_transfer(
                    ticket,
                    current,
                    destinations[current.id],
                    trigger=Trigger.SYSTEM,
                    actor=actor,
                    extra={"workflow": target.name, "dropped_fields": dropped},
                )
                moved += 1
        return Adoption(moved=moved, skipped=skipped)

    def destinations(
        self, source: Workflow, target: Workflow, mapping: Mapping[uuid.UUID, uuid.UUID]
    ) -> dict[uuid.UUID, WorkflowStatus]:
        """Where each of `source`'s statuses goes in `target`; raises `UNMAPPED_STATUSES`."""
        targets = {s.id: s for s in target.statuses.select_related("base")}
        by_key = {s.key: s for s in targets.values()}
        destinations: dict[uuid.UUID, WorkflowStatus] = {}
        unmapped = []
        for status in source.statuses.all():
            mapped = None if status.is_pipeline else mapping.get(status.id)
            chosen = targets.get(mapped) if mapped else by_key.get(status.key)
            if chosen is None or (chosen.is_pipeline and chosen.key != status.key):
                unmapped.append({"id": str(status.id), "key": status.key, "name": status.name})
            else:
                destinations[status.id] = chosen
        if unmapped:
            raise LifecycleError(
                422,
                FailureCode.UNMAPPED_STATUSES,
                "map these statuses to statuses of the target workflow",
                details=unmapped,
            )
        return destinations

    def evacuate(self, status: WorkflowStatus, to: WorkflowStatus, *, actor: User) -> int:
        """Moves every ticket at `status` to `to`, cancelling moves in flight; returns how many."""
        count = 0
        for ticket_id in list(status.tickets.values_list("id", flat=True)):
            with transaction.atomic():
                ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
                if ticket.workflow_status_id != status.id:
                    continue
                self.cancel_open(ticket, f"status {status.name!r} was deleted")
                self.record_system_transfer(ticket, status, to, trigger=Trigger.SYSTEM, actor=actor)
                count += 1
        return count

    # ── answers from outside ──

    def complete_callback(
        self,
        run_id: uuid.UUID,
        *,
        token: str,
        success: bool,
        message: str,
        output: Mapping[str, Any] | None,
    ) -> ActionRun:
        """Finishes a run waiting on an external system's callback, then continues its phase."""
        with transaction.atomic():
            run = self.lock_run(run_id)
            if not constant_time_compare(token, callback_token(run)):
                raise LifecycleError(403, FailureCode.BAD_CALLBACK_TOKEN, "bad callback token")
            if run.state != RunState.RUNNING.value or run.awaiting_until is None:
                raise LifecycleError(409, FailureCode.NOT_AWAITING, "the run is not waiting")
            run.output = {**(run.output or {}), "callback": dict(output or {}), "message": message}
            if success:
                run.state = RunState.SUCCEEDED.value
                run.finished_at = timezone.now()
                run.awaiting_until = None
                run.save(update_fields=["state", "finished_at", "awaiting_until", "output"])
            else:
                runner.fail(
                    run, FailureCode.CALLBACK_FAILED, message or "the callback reported failure"
                )
            self.resume(run)
        return run

    def decide_approval(
        self, approval_id: uuid.UUID, *, user: User, approve: bool, comment: str
    ) -> ApprovalRequest:
        """Records an approver's answer and continues the move it holds, or stops it."""
        with transaction.atomic():
            run_id = (
                ApprovalRequest.objects.filter(pk=approval_id)
                .values_list("run_id", flat=True)
                .first()
            )
            if run_id is None:
                raise LifecycleError(404, FailureCode.NOT_FOUND, "no such approval")
            run = self.lock_run(run_id)
            approval = ApprovalRequest.objects.select_for_update().get(pk=approval_id)
            if not approval.can_be_decided_by(user.id):
                raise LifecycleError(403, FailureCode.NOT_AN_APPROVER, "you are not an approver")
            if run.transfer is not None and run.transfer.actor_id == user.id:
                raise LifecycleError(
                    403, FailureCode.SELF_APPROVAL, "you cannot approve your own move"
                )
            if approval.state != ApprovalState.PENDING.value:
                raise LifecycleError(409, FailureCode.NOT_AWAITING, f"already {approval.state}")
            if approval.expires_at <= timezone.now():
                raise LifecycleError(409, FailureCode.APPROVAL_EXPIRED, "this approval has expired")
            approval.state = (ApprovalState.APPROVED if approve else ApprovalState.REJECTED).value
            approval.decided_by = user
            approval.decided_at = timezone.now()
            approval.comment = comment
            approval.save(update_fields=["state", "decided_by", "decided_at", "comment"])
            if approve:
                run.state = RunState.SUCCEEDED.value
                run.finished_at = timezone.now()
                run.awaiting_until = None
                run.save(update_fields=["state", "finished_at", "awaiting_until"])
            else:
                runner.fail(
                    run,
                    FailureCode.APPROVAL_REJECTED,
                    f"Rejected by {user.username}" + (f": {comment}" if comment else ""),
                )
            AuditLog.objects.record(
                f"approval_{approval.state}",
                actor_type="human",
                actor_id=user.id,
                ticket_id=run.ticket_id,
                payload={"approval": str(approval.id), "comment": comment},
            )
            self.resume(run)
        return approval

    def lock_run(self, run_id: uuid.UUID) -> ActionRun:
        """Locks a run's ticket, then the run; raises `NOT_FOUND` for an unknown run."""
        ticket_id = ActionRun.objects.filter(pk=run_id).values_list("ticket_id", flat=True).first()
        if ticket_id is None:
            raise LifecycleError(404, FailureCode.NOT_FOUND, "no such action run")
        list(Ticket.objects.select_for_update().filter(pk=ticket_id).values_list("pk", flat=True))
        return (
            ActionRun.objects.select_for_update(of=("self",))
            .select_related("transfer")
            .get(pk=run_id)
        )

    # ── the watchdog ──

    def sweep(self) -> dict[str, int]:
        """Fails runs past their wait, re-queues lost work and unlocks tickets left locked."""
        now = timezone.now()
        counts = {"approvals_expired": 0, "runs_timed_out": 0, "resumed": 0, "unlocked": 0}

        expired = ApprovalRequest.objects.filter(
            state=ApprovalState.PENDING.value, expires_at__lt=now
        ).values_list("id", "run_id")
        for approval_id, run_id in list(expired):
            with transaction.atomic():
                run = self.lock_run(run_id)
                approval = ApprovalRequest.objects.select_for_update().get(pk=approval_id)
                if approval.state != ApprovalState.PENDING.value:
                    continue
                approval.state = ApprovalState.REJECTED.value
                approval.decided_at = now
                approval.comment = "expired"
                approval.save(update_fields=["state", "decided_at", "comment"])
                if run.state == RunState.RUNNING.value:
                    runner.fail(run, FailureCode.APPROVAL_EXPIRED, "no approver answered in time")
                    self.resume(run)
                counts["approvals_expired"] += 1

        stuck_before = now - timedelta(seconds=settings.LIFECYCLE_RUN_STUCK_SEC)
        overdue = Q(awaiting_until__lt=now) | Q(
            awaiting_until__isnull=True, started_at__lt=stuck_before
        )
        stalled = ActionRun.objects.filter(overdue, state=RunState.RUNNING.value)
        for run_id in list(stalled.values_list("id", flat=True)):
            with transaction.atomic():
                run = self.lock_run(run_id)
                if not ActionRun.objects.filter(
                    overdue, pk=run.pk, state=RunState.RUNNING.value
                ).exists():
                    continue
                waited = run.awaiting_until is not None
                runner.fail(
                    run,
                    FailureCode.CALLBACK_TIMEOUT if waited else FailureCode.RUN_TIMEOUT,
                    "no answer in time" if waited else "the run stalled",
                )
                self.resume(run)
                counts["runs_timed_out"] += 1

        for transfer in Transfer.objects.open().filter(created_at__lt=stuck_before):
            runs = transfer.runs.all()
            if runs.filter(state=RunState.RUNNING.value).exists():
                continue
            phase = Phase.BEFORE if transfer.state == TransferState.PENDING.value else Phase.ENTER
            self.schedule(transfer.id, phase)
            counts["resumed"] += 1

        counts["unlocked"] = (
            Ticket.objects.filter(waiting_transform=True)
            .exclude(
                transfers__state__in=[
                    s.value for s in (TransferState.PENDING, TransferState.COMMITTED)
                ]
            )
            .update(waiting_transform=False)
        )
        return counts

    # ── scheduling ──

    def schedule(
        self, transfer_id: uuid.UUID, phase: Phase, countdown: float | None = None
    ) -> None:
        """Queues `phase` of a transfer to run once the current transaction commits."""
        from apps.lifecycle import tasks

        args = (str(transfer_id), phase.value)

        def send() -> None:
            if countdown is None:
                tasks.run_phase.apply_async(args=args)
            else:
                tasks.run_phase.apply_async(args=args, countdown=countdown)

        transaction.on_commit(send)

    def backoff(self, attempt: int) -> float:
        """Seconds before a run's next attempt."""
        return min(
            settings.LIFECYCLE_RETRY_BACKOFF_BASE_SEC * 2**attempt,
            settings.LIFECYCLE_RETRY_BACKOFF_MAX_SEC,
        )

    def run_events(self, run_ids: list[str]) -> None:
        """Runs field-event runs in order; a transient failure re-queues that run alone."""
        from apps.lifecycle import tasks

        for run in ActionRun.objects.filter(id__in=run_ids).order_by("seq"):
            if runner.execute(run.id) is Outcome.RETRY:
                run.refresh_from_db(fields=["attempt"])
                tasks.run_event_actions.apply_async(
                    args=([str(run.id)],), countdown=self.backoff(run.attempt)
                )


# --- the lifecycle service ---

lifecycle = Lifecycle()
