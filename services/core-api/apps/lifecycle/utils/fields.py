"""Reads and writes tickets' custom field values, applying field rules and firing field events."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.lifecycle.models import (
    ActionRun,
    CustomField,
    FieldEvent,
    TicketFieldValue,
    Workflow,
)
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.rules import (
    EVENTS,
    FREE_TEXT_TYPES,
    ConfiguredRule,
    EventCode,
    FieldType,
    RuleCode,
    RuleContext,
    RuleViolation,
    accepts,
    coerce,
    is_empty,
    violations,
)
from apps.lifecycle.utils.vocabulary import FailureCode, Phase
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.utils.crypto import QuarantineEntry, build_quarantine_entries
from apps.tickets.utils.masking import mask_reply
from apps.tickets.utils.patterns import PIILevel


@dataclass(frozen=True)
class FieldCheck:
    """Whether field values pass their fields' rules, and the rules they break."""

    valid: bool
    violations: list[dict[str, str]]


class FieldValues:
    """Every read and write of a ticket's custom field values."""

    def of(self, ticket: Ticket) -> dict[str, Any]:
        """The ticket's values, by field id."""
        return {
            str(v.field_id): v.value for v in TicketFieldValue.objects.filter(ticket_id=ticket.id)
        }

    def by_name(self, ticket: Ticket) -> dict[str, Any]:
        """The ticket's values, by field name."""
        return {
            v.field.name: v.value
            for v in TicketFieldValue.objects.filter(ticket_id=ticket.id).select_related("field")
        }

    def rule_context(self, ticket: Ticket) -> RuleContext:
        return RuleContext(
            today=timezone.localdate(),
            sla_due=ticket.sla_due_at.date() if ticket.sla_due_at else None,
            pattern_timeout=settings.LIFECYCLE_RULE_PATTERN_TIMEOUT_SEC,
        )

    def write(self, ticket_id: uuid.UUID, values: Mapping[Any, Any], *, actor: User) -> Ticket:
        """A person's write, by field id: free text is masked before it is stored."""
        ticket = Ticket.objects.get(id=ticket_id)
        fields = self.fields_of(Workflow.objects.of_ticket(ticket))
        changes = {self.field_by_id(fields, key): value for key, value in values.items()}

        taken = list(ticket.pii_map)
        quarantine: dict[str, QuarantineEntry] = {}
        level = PIILevel(ticket.pii_level)
        for field, value in list(changes.items()):
            if FieldType(field.field_type) not in FREE_TEXT_TYPES or is_empty(value):
                continue
            if not isinstance(value, str):
                continue
            masked = async_to_sync(mask_reply)(
                value, settings.THRESHOLDS.masking.ner_max_share, taken
            )
            entries = build_quarantine_entries(masked.placeholder_map)
            quarantine.update(entries)
            taken += list(entries)
            level = level.worse(masked.pii_level)
            changes[field] = masked.text_masked

        self.apply(ticket.id, changes, actor=actor, depth=0, quarantine=quarantine, pii_level=level)
        return Ticket.objects.get(id=ticket.id)

    def write_by_name(self, ticket: Ticket, values: Mapping[str, Any], *, depth: int) -> None:
        """An action's write, by field name, with templated strings read as the field's type."""
        fields = {f.name: f for f in self.fields_of(Workflow.objects.of_ticket(ticket)).values()}
        changes: dict[CustomField, Any] = {}
        for name, value in values.items():
            field = fields.get(name)
            if field is None:
                raise LifecycleError(
                    422, FailureCode.INVALID_FIELD_VALUE, f"no custom field {name!r}"
                )
            changes[field] = coerce(FieldType(field.field_type), value)
        self.apply(ticket.id, changes, actor=None, depth=depth, quarantine={}, pii_level=None)

    def apply(
        self,
        ticket_id: uuid.UUID,
        changes: Mapping[CustomField, Any],
        *,
        actor: User | None,
        depth: int,
        quarantine: dict[str, QuarantineEntry],
        pii_level: PIILevel | None,
    ) -> None:
        """Checks and stores `changes`, then queues the actions of the events they fire."""
        named = [
            v for f, v in changes.items() if f.field_type == FieldType.USER and not is_empty(v)
        ]
        users = set(
            User.objects.filter(username__in=named, is_active=True).values_list(
                "username", flat=True
            )
        )
        bad = [
            f.name
            for f, v in changes.items()
            if not accepts(FieldType(f.field_type), v, list(f.options))
            or (f.field_type == FieldType.USER and not is_empty(v) and v not in users)
        ]
        if bad:
            raise LifecycleError(
                422,
                FailureCode.INVALID_FIELD_VALUE,
                f"not a valid value for {', '.join(bad)}",
                details={"fields": bad},
            )

        with transaction.atomic():
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            current = self.of(ticket)
            proposed = {**current, **{str(f.id): v for f, v in changes.items()}}
            rules = [
                ConfiguredRule(str(r.id), RuleCode(r.rule), r.params, str(f.id), f.name)
                for f in changes
                for r in f.rules.all()
                if r.is_active
            ]
            found = violations(rules, proposed, self.rule_context(ticket))
            if found:
                raise LifecycleError(
                    422,
                    FailureCode.RULE_VIOLATION,
                    "; ".join(v.message for v in found),
                    details=[violation_detail(v) for v in found],
                )

            if quarantine:
                PiiQuarantine.objects.store(ticket, quarantine)
                ticket.pii_map = {
                    **ticket.pii_map,
                    **{ph: str(e.ref) for ph, e in quarantine.items()},
                }
            if pii_level is not None:
                ticket.pii_level = PIILevel(ticket.pii_level).worse(pii_level).value
            ticket.save(update_fields=["pii_map", "pii_level"])

            for field, value in changes.items():
                TicketFieldValue.objects.update_or_create(
                    ticket=ticket, field=field, defaults={"value": value}
                )

            runs = self.plan_event_runs(ticket, changes, current, depth)
            AuditLog.objects.record(
                "ticket_fields_updated",
                actor_type="human" if actor else "system",
                actor_id=actor.id if actor else None,
                ticket_id=ticket.id,
                payload={
                    "ticket_public_id": ticket.public_id,
                    "fields": sorted(f.name for f in changes),
                    "event_runs": len(runs),
                },
            )
            if runs:
                from apps.lifecycle import tasks

                ids = [str(r.id) for r in runs]
                transaction.on_commit(lambda: tasks.run_event_actions.delay(ids))

    def plan_event_runs(
        self,
        ticket: Ticket,
        changes: Mapping[CustomField, Any],
        before: Mapping[str, Any],
        depth: int,
    ) -> list[ActionRun]:
        """Creates the runs of every active event the changes fire, in field then action order."""
        runs: list[ActionRun] = []
        for field, value in changes.items():
            old = before.get(str(field.id))
            for event in field.events.all():
                if not event.is_active or not EVENTS[EventCode(event.event)].fires(
                    old, value, event.params
                ):
                    continue
                runs += self.event_runs(ticket, event, depth, start=len(runs))
        return runs

    def event_runs(
        self, ticket: Ticket, event: FieldEvent, depth: int, *, start: int
    ) -> list[ActionRun]:
        firing = uuid.uuid4()
        actions = [a for a in event.actions.all() if a.is_active]
        return [
            ActionRun.objects.create(
                ticket=ticket,
                field_event=event,
                source_action=action,
                action=action.action,
                params=action.params,
                phase=Phase.EVENT.value,
                seq=start + i,
                depth=depth,
                idempotency_key=f"event:{event.id}:{firing}:{i}",
            )
            for i, action in enumerate(actions)
        ]

    def validate(self, workflow: Workflow, values: Mapping[Any, Any]) -> FieldCheck:
        """The field-rule violations `values` (by field id) would cause, without writing."""
        fields = self.fields_of(workflow)
        checked = {self.field_by_id(fields, key): value for key, value in values.items()}
        rules = [
            ConfiguredRule(str(r.id), RuleCode(r.rule), r.params, str(f.id), f.name)
            for f in checked
            for r in f.rules.all()
            if r.is_active
        ]
        found = violations(
            rules,
            {str(f.id): v for f, v in checked.items()},
            RuleContext(
                today=timezone.localdate(),
                sla_due=None,
                pattern_timeout=settings.LIFECYCLE_RULE_PATTERN_TIMEOUT_SEC,
            ),
        )
        return FieldCheck(valid=not found, violations=[violation_detail(v) for v in found])

    def carry_over(self, ticket: Ticket, workflow: Workflow) -> list[str]:
        """Moves the ticket's values onto `workflow`'s fields of the same name and type; returns
        the names of the values dropped."""
        targets = {(f.name, f.field_type): f for f in workflow.fields.all()}
        dropped = []
        for value in TicketFieldValue.objects.filter(ticket=ticket).select_related("field"):
            target = targets.get((value.field.name, value.field.field_type))
            if target is None:
                dropped.append(value.field.name)
                value.delete()
            elif target.id != value.field_id:
                value.field = target
                value.save(update_fields=["field"])
        return dropped

    def fields_of(self, workflow: Workflow) -> dict[str, CustomField]:
        """The workflow's fields with their rules and events, by id."""
        return {str(f.id): f for f in workflow.fields.prefetch_related("rules", "events__actions")}

    def field_by_id(self, fields: Mapping[str, CustomField], key: Any) -> CustomField:
        field = fields.get(str(key))
        if field is None:
            raise LifecycleError(
                422, FailureCode.INVALID_FIELD_VALUE, f"no custom field {key} in this workflow"
            )
        return field


def violation_detail(violation: RuleViolation) -> dict[str, str]:
    """A rule violation as the API reports it."""
    return {
        "field_id": violation.field_id,
        "field_name": violation.field_name,
        "rule_id": violation.rule_id,
        "rule": violation.rule,
        "message": violation.message,
    }


# --- the field values service ---

field_values = FieldValues()
