"""Runbooks (F12, ADR-0038): executing an approved proposal, the executor's outcome on the
ticket, and the catalog."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.itsm_mock.models import (
    CATALOG_FIELDS,
    ExecutionState,
    ExecutorKind,
    Runbook,
    RunbookExecution,
    TargetRule,
)
from apps.itsm_mock.utils.executors import (
    EXECUTORS,
    KeycloakExecutor,
    Outcome,
    RunbookError,
    RunbookRefusal,
)
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.review.models import ReviewDecision, ReviewItem
from apps.tickets.models import CommentVisibility
from apps.tickets.utils.comments import comments
from apps.tickets.utils.router import ReviewQueue

R = RunbookRefusal

OUTCOME_AUDIT = {
    ExecutionState.SUCCEEDED: "runbook_executed",
    ExecutionState.FAILED: "runbook_failed",
    ExecutionState.UNKNOWN: "runbook_unknown",
}

OUTCOME_VI = {
    ExecutionState.SUCCEEDED: "đã chạy thành công",
    ExecutionState.FAILED: "chạy không thành công, kỹ thuật viên sẽ xử lý tiếp",
    ExecutionState.UNKNOWN: "chưa rõ kết quả, kỹ thuật viên đang kiểm tra",
}


@dataclass
class RunbookPanel:
    """What a review item's runbook panel shows: the proposal, its catalog entry, whether a
    person approved it, and its executions."""

    runbook_id: str | None
    draft_payload: dict[str, Any]
    runbook: Runbook | None
    approved: bool
    executions: list[RunbookExecution]


class Runbooks:
    """Runs approved runbooks and keeps the catalog."""

    def panel(self, item_id: uuid.UUID) -> RunbookPanel:
        item = ReviewItem.objects.select_related("ai_run").filter(pk=item_id).first()
        if item is None:
            raise RunbookError(404, R.REVIEW_ITEM_NOT_FOUND, "review item not found")
        draft = (item.ai_run.proposed_draft or {}) if item.ai_run else {}
        code = draft.get("runbook_id") if isinstance(draft.get("runbook_id"), str) else None
        try:
            self.approval_of(item)
            approved = True
        except RunbookError:
            approved = False
        return RunbookPanel(
            runbook_id=code,
            draft_payload=draft.get("draft_payload") or {},
            runbook=Runbook.objects.select_related("approved_by", "drafted_by")
            .filter(code=code)
            .first(),
            approved=approved,
            executions=list(
                RunbookExecution.objects.filter(review_item=item).select_related(
                    "runbook", "executed_by", "approved_by", "second_approver", "resolved_by"
                )
            ),
        )

    # ── approval (ADR-0006, BR-F12-01) ──

    def approval_of(self, item: ReviewItem) -> ReviewDecision:
        """The staff approval that lets `item`'s runbook run; refuses otherwise."""
        decision = (
            item.decisions.filter(action_taken="approve")
            .select_related("reviewer")
            .order_by("-decided_at")
            .first()
        )
        if decision is None:
            raise RunbookError(
                422,
                R.NOT_APPROVED,
                "no approving review_decisions row for this review item — "
                "runbooks NEVER execute without human approval (ADR-0006)",
            )
        if item.queue != ReviewQueue.RUNBOOK_APPROVAL.value:
            raise RunbookError(
                422, R.NOT_A_RUNBOOK_ITEM, "review item is not a runbook_approval item"
            )
        if not decision.reviewer.may_run_runbooks:
            raise RunbookError(
                422,
                R.APPROVER_NOT_STAFF,
                "the approving decision was not made by a technician or manager",
            )
        return decision

    def runbook_of(self, item: ReviewItem) -> Runbook:
        draft = (item.ai_run.proposed_draft or {}) if item.ai_run else {}
        code = draft.get("runbook_id")
        runbook = (
            Runbook.objects.filter(code=code, is_active=True).first()
            if isinstance(code, str)
            else None
        )
        if runbook is None:
            raise RunbookError(422, R.UNKNOWN_RUNBOOK, f"unknown runbook_id: {code!r}")
        if not runbook.is_runnable():
            raise RunbookError(
                409, R.RUNBOOK_NOT_APPROVED, f"runbook {runbook.code} has no manager approval"
            )
        return runbook

    def check_payload(self, runbook: Runbook, item: ReviewItem, payload: dict[str, Any]) -> None:
        """Required fields, the target rule (BR-F12-02) and the executor's own limits."""
        executor = EXECUTORS[ExecutorKind(runbook.executor)]
        needed = set(runbook.required_fields) | executor.needs(runbook.config)
        missing = sorted(f for f in needed if payload.get(f) in (None, ""))
        if missing:
            raise RunbookError(
                422,
                R.MISSING_FIELDS,
                f"runbook {runbook.code} missing required fields: {missing}",
            )
        reporter = item.ticket.reporter.username
        if runbook.target_rule == TargetRule.REPORTER.value and (
            payload.get("target_username") != reporter
        ):
            raise RunbookError(
                422,
                R.TARGET_NOT_REPORTER,
                f"runbook {runbook.code} may only target the ticket's reporter",
            )
        executor.check_payload(runbook.config, payload)

    # ── execution ──

    def execute(self, item_id: uuid.UUID, actor: User, payload: dict[str, Any]) -> RunbookExecution:
        """Records an approver's payload for a run and queues it (BR-F12-03)."""
        if not actor.may_run_runbooks:
            raise RunbookError(
                403, R.EXECUTOR_NOT_STAFF, "only a technician or manager may execute a runbook"
            )
        with transaction.atomic():
            item = (
                ReviewItem.objects.select_for_update(of=("self",))
                .select_related("ai_run", "ticket__reporter")
                .filter(pk=item_id)
                .first()
            )
            if item is None:
                raise RunbookError(404, R.REVIEW_ITEM_NOT_FOUND, "review item not found")
            decision = self.approval_of(item)
            runbook = self.runbook_of(item)
            self.check_payload(runbook, item, payload)
            if RunbookExecution.objects.blocking_a_new_attempt(item).exists():
                raise RunbookError(
                    409,
                    R.EXECUTION_EXISTS,
                    "this proposal already has an execution that has not failed",
                )
            attempt = RunbookExecution.objects.filter(review_item=item).count() + 1
            draft = (item.ai_run.proposed_draft or {}) if item.ai_run else {}
            execution = RunbookExecution.objects.create(
                ticket=item.ticket,
                review_item=item,
                runbook=runbook,
                runbook_code=runbook.code,
                payload=draft.get("draft_payload") or {},
                executed_payload=payload,
                executed_by=actor,
                approved_by=decision.reviewer,
                executor=runbook.executor,
                state=ExecutionState.QUEUED.value,
                attempt=attempt,
                idempotency_key=f"{item.id}:{attempt}",
            )
            self.audit("runbook_approved", execution, actor, {})
            self.enqueue(execution)
        return execution

    def enqueue(self, execution: RunbookExecution) -> None:
        from apps.itsm_mock import tasks

        execution_id = str(execution.id)
        transaction.on_commit(lambda: tasks.execute.delay(execution_id), robust=True)

    def run(self, execution_id: uuid.UUID) -> RunbookExecution | None:
        """The worker's run: starts a queued execution once, calls its executor and records the
        outcome; None when the row is past `queued` (BR-F12-06)."""
        execution = self.start(execution_id)
        if execution is None:
            return None
        assert execution.runbook is not None
        try:
            outcome = EXECUTORS[ExecutorKind(execution.runbook.executor)].run(execution)
        except Exception as e:  # noqa: BLE001 — an executor bug is an unknown outcome, never a retry
            outcome = Outcome(ExecutionState.UNKNOWN, error=f"executor error: {type(e).__name__}")
        return self.finish(execution_id, outcome)

    def start(self, execution_id: uuid.UUID) -> RunbookExecution | None:
        """Moves a queued execution to running, checking ADR-0006 again; None if it isn't
        queued."""
        with transaction.atomic():
            execution = self.lock(execution_id)
            if execution.state != ExecutionState.QUEUED.value:
                return None
            refusal = self.why_not_runnable(execution)
            now = timezone.now()
            execution.started_at = now
            if refusal:
                self.close(execution, Outcome(ExecutionState.FAILED, error=refusal), now)
                return None
            execution.state = ExecutionState.RUNNING.value
            execution.awaiting_until = now + timedelta(seconds=settings.ITSM_RUN_STUCK_SEC)
            execution.save(update_fields=["state", "started_at", "awaiting_until"])
        return execution

    def why_not_runnable(self, execution: RunbookExecution) -> str | None:
        """Why a queued execution may not run now, re-checked by the worker."""
        try:
            self.approval_of(execution.review_item)
        except RunbookError as e:
            return e.message
        runbook = execution.runbook
        if runbook is None or not runbook.is_runnable():
            return "the runbook is no longer approved or active"
        assert runbook.approved_at is not None
        if runbook.approved_at > execution.executed_at:
            return "the runbook changed after this execution was approved"
        return None

    def finish(self, execution_id: uuid.UUID, outcome: Outcome) -> RunbookExecution:
        with transaction.atomic():
            execution = self.lock(execution_id)
            if execution.state != ExecutionState.RUNNING.value:
                execution.result = {**execution.result, "late_outcome": self.outcome_of(outcome)}
                execution.save(update_fields=["result"])
                return execution
            if outcome.state == ExecutionState.RUNNING:
                execution.external_ref = outcome.external_ref
                execution.result = outcome.result
                execution.awaiting_until = outcome.awaiting_until
                execution.save(update_fields=["external_ref", "result", "awaiting_until"])
                return execution
            self.close(execution, outcome, timezone.now())
        return execution

    @staticmethod
    def outcome_of(outcome: Outcome) -> dict[str, Any]:
        return {
            "state": outcome.state.value,
            "external_ref": outcome.external_ref,
            "error": outcome.error,
        }

    def close(self, execution: RunbookExecution, outcome: Outcome, now: datetime) -> None:
        """Records a final outcome with its audit row, ticket comment and notice (FR-F12-006)."""
        execution.state = outcome.state.value
        execution.external_ref = outcome.external_ref or execution.external_ref
        execution.error = outcome.error
        execution.result = {**execution.result, **outcome.result}
        execution.finished_at = now
        execution.awaiting_until = None
        execution.save(
            update_fields=[
                "state",
                "external_ref",
                "error",
                "result",
                "started_at",
                "finished_at",
                "awaiting_until",
            ]
        )
        self.audit(
            OUTCOME_AUDIT[outcome.state],
            execution,
            None,
            {"external_ref": execution.external_ref, "error": execution.error},
        )
        self.tell(execution, OUTCOME_VI[outcome.state])

    def tell(self, execution: RunbookExecution, what: str) -> None:
        """The ticket comment and the assignee's notice for an outcome."""
        state = ExecutionState(execution.state)
        public = state == ExecutionState.SUCCEEDED
        comments.system(
            execution.ticket,
            f"Runbook {execution.runbook_code} {what}.",
            visibility=CommentVisibility.PUBLIC if public else CommentVisibility.INTERNAL,
        )
        notifier.emit(
            NotificationEvent.RUNBOOK_FINISHED,
            execution.ticket,
            Notice(
                message=f"{execution.runbook_code}: {state.value}",
                link=f"/tickets/{execution.ticket.public_id}",
                data={"execution": str(execution.id), "state": state.value},
            ),
        )

    # ── answers from outside and from people ──

    def complete_callback(
        self,
        execution_id: uuid.UUID,
        *,
        token: str,
        state: ExecutionState,
        external_ref: str,
        error: str,
    ) -> RunbookExecution:
        """n8n's one answer for a run it started (BR-F12-07)."""
        with transaction.atomic():
            execution = self.lock(execution_id)
            if not constant_time_compare(token, execution.callback_token()):
                raise RunbookError(403, R.BAD_CALLBACK_TOKEN, "bad callback token")
            if (
                execution.state != ExecutionState.RUNNING.value
                or execution.executor != ExecutorKind.N8N.value
            ):
                raise RunbookError(409, R.NOT_AWAITING, "the execution is not waiting")
            self.close(
                execution,
                Outcome(state, external_ref=external_ref, error=error),
                timezone.now(),
            )
        return execution

    def sweep(self) -> int:
        """Marks running executions past their wait `unknown` (BR-F12-06)."""
        count = 0
        for execution_id in RunbookExecution.objects.past_their_wait(timezone.now()).values_list(
            "id", flat=True
        ):
            with transaction.atomic():
                execution = self.lock(execution_id)
                if execution.state != ExecutionState.RUNNING.value:
                    continue
                self.close(
                    execution,
                    Outcome(
                        ExecutionState.UNKNOWN,
                        error="no answer from the executor in time; check the target system",
                    ),
                    timezone.now(),
                )
                count += 1
        return count

    def resolve(
        self, execution_id: uuid.UUID, actor: User, state: ExecutionState, note: str
    ) -> RunbookExecution:
        """A person's verdict on an unknown outcome after checking the target system
        (UC-F12-02)."""
        with transaction.atomic():
            execution = self.lock(execution_id)
            if execution.state != ExecutionState.UNKNOWN.value:
                raise RunbookError(409, R.NOT_UNKNOWN, "only an unknown outcome is resolved")
            execution.state = state.value
            execution.resolved_by = actor
            execution.resolved_at = timezone.now()
            execution.resolution_note = note
            execution.save(update_fields=["state", "resolved_by", "resolved_at", "resolution_note"])
            self.audit("runbook_resolved", execution, actor, {"note": note})
            self.tell(execution, f"được xác nhận {OUTCOME_VI[state]} sau khi kiểm tra")
        return execution

    def lock(self, execution_id: uuid.UUID) -> RunbookExecution:
        execution = (
            RunbookExecution.objects.select_for_update(of=("self",))
            .select_related("runbook", "ticket", "review_item")
            .filter(pk=execution_id)
            .first()
        )
        if execution is None:
            raise RunbookError(404, R.EXECUTION_NOT_FOUND, "execution not found")
        return execution

    def audit(
        self,
        action: str,
        execution: RunbookExecution,
        actor: User | None,
        extra: dict[str, Any],
    ) -> None:
        AuditLog.objects.record(
            action,
            actor_type="user" if actor else "system",
            actor_id=actor.id if actor else None,
            ticket_id=execution.ticket_id,
            payload={
                "execution": str(execution.id),
                "runbook": execution.runbook_code,
                "executor": execution.executor,
                "state": execution.state,
                "executed_payload": execution.executed_payload,
                **extra,
            },
        )

    # ── the catalog (BR-F12-08) ──

    def check_definition(self, fields: dict[str, Any]) -> None:
        """Refuses a runbook definition no executor could run safely."""
        executor = EXECUTORS[ExecutorKind(fields["executor"])]
        errors = executor.config_errors(fields["config"])
        required = fields["required_fields"]
        if not isinstance(required, list) or not all(isinstance(f, str) for f in required):
            errors.append("required_fields must list field names")
        elif (
            fields["target_rule"] == TargetRule.REPORTER.value and "target_username" not in required
        ):
            errors.append("a reporter-only runbook must require target_username")
        if errors:
            raise RunbookError(422, R.INVALID_CONFIG, "; ".join(errors))
        if isinstance(executor, KeycloakExecutor):
            refused = executor.ungrantable_groups(fields["config"])
            if refused:
                raise RunbookError(
                    422,
                    R.GROUP_NOT_ALLOWED,
                    f"groups outside {settings.ITSM_GRANTABLE_GROUP_PREFIXES}: {refused}",
                )

    def runbook(self, code: str) -> Runbook:
        runbook = Runbook.objects.filter(code=code).first()
        if runbook is None:
            raise RunbookError(404, R.UNKNOWN_RUNBOOK, f"unknown runbook {code!r}")
        return runbook

    @transaction.atomic
    def create(self, code: str, fields: dict[str, Any], actor: User) -> Runbook:
        """A new runbook, live at once (ADR-0043)."""
        self.check_definition(fields)
        now = timezone.now()
        try:
            with transaction.atomic():
                runbook = Runbook.objects.create(
                    code=code,
                    drafted_by=actor,
                    drafted_at=now,
                    approved_by=actor,
                    approved_at=now,
                    **fields,
                )
        except IntegrityError as e:
            raise RunbookError(409, R.RUNBOOK_EXISTS, f"runbook {code} exists") from e
        self.audit_catalog(runbook, actor, "created", fields)
        return runbook

    @transaction.atomic
    def change(self, code: str, changes: dict[str, Any], actor: User) -> Runbook:
        """Applies a change at once; a run queued before it fails rather than run the old
        definition (ADR-0043)."""
        runbook = self.locked(code)
        fields = {**self.definition(runbook), **(runbook.pending_change or {}), **changes}
        self.check_definition(fields)
        self.make_live(runbook, fields, actor)
        self.audit_catalog(runbook, actor, "changed", changes)
        return runbook

    @transaction.atomic
    def activate(self, code: str, actor: User) -> Runbook:
        """Makes a runbook that was never live, or a change drafted before ADR-0043, live."""
        runbook = self.locked(code)
        if runbook.pending_change is None and runbook.approved_at is not None:
            raise RunbookError(409, R.ALREADY_LIVE, "the runbook is already live")
        fields = {**self.definition(runbook), **(runbook.pending_change or {})}
        self.check_definition(fields)
        self.make_live(runbook, fields, actor)
        self.audit_catalog(runbook, actor, "activated", self.definition(runbook))
        return runbook

    def locked(self, code: str) -> Runbook:
        runbook = Runbook.objects.select_for_update().filter(code=code).first()
        if runbook is None:
            raise RunbookError(404, R.UNKNOWN_RUNBOOK, f"unknown runbook {code!r}")
        return runbook

    def make_live(self, runbook: Runbook, fields: dict[str, Any], actor: User) -> None:
        for name in CATALOG_FIELDS:
            setattr(runbook, name, fields[name])
        now = timezone.now()
        runbook.pending_change = None
        runbook.drafted_by = actor
        runbook.drafted_at = now
        runbook.approved_by = actor
        runbook.approved_at = now
        runbook.save()

    @staticmethod
    def definition(runbook: Runbook) -> dict[str, Any]:
        return {name: getattr(runbook, name) for name in CATALOG_FIELDS}

    def audit_catalog(
        self, runbook: Runbook, actor: User, stage: str, fields: dict[str, Any]
    ) -> None:
        AuditLog.objects.record(
            "runbook_catalog_changed",
            actor_type="user",
            actor_id=actor.id,
            payload={"runbook": runbook.code, "stage": stage, "fields": fields},
        )


# --- the runbook service ---

runbooks = Runbooks()
