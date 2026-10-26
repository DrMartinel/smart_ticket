"""SLA policies (drafted, then approved by another manager), calendars and holidays (UC-F1-06)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.sla.models import Calendar, Holiday, Policy, PolicyState
from apps.sla.utils.business_time import CalendarError, parse_hours

_POLICY_FIELDS = (
    "name",
    "order",
    "category",
    "priority",
    "response_minutes",
    "resolution_minutes",
    "is_24x7",
)


class SlaConfigRefusal(StrEnum):
    INVALID_TARGET = "invalid_target"
    ORDER_TAKEN = "order_taken"
    SELF_APPROVAL = "self_approval"
    DEFAULT_POLICY = "default_policy"
    NOT_A_DRAFT = "not_a_draft"
    BAD_INTERVAL = "bad_interval"
    UNKNOWN_TIMEZONE = "unknown_timezone"
    HOLIDAY_EXISTS = "holiday_exists"
    REASON_REQUIRED = "reason_required"
    NOT_FOUND = "not_found"


class SlaConfigError(CodedError):
    """An SLA configuration change core-api refuses (BR-X-08)."""


def _audit(event: str, actor: User, payload: dict[str, Any]) -> None:
    AuditLog.objects.record(event, actor_type="human", actor_id=actor.id, payload=payload)


class SlaConfig:
    """Changes to policies, calendars and holidays, each audited."""

    # ── policies ──

    def draft(self, actor: User, data: dict[str, Any]) -> Policy:
        """A new draft; with `replaces_id`, the active policy it takes over from on approval."""
        self.check_targets(data["response_minutes"], data["resolution_minutes"])
        with transaction.atomic():
            policy = Policy(created_by=actor, state=PolicyState.DRAFT.value)
            for name in _POLICY_FIELDS:
                setattr(policy, name, data[name])
            policy.calendar = (
                self.calendar(data["calendar_id"]) if data.get("calendar_id") else None
            )
            policy.replaces = self.policy(data["replaces_id"]) if data.get("replaces_id") else None
            policy.save()
            _audit("sla_policy_drafted", actor, self.snapshot(policy))
        return policy

    def edit(self, actor: User, policy_id: uuid.UUID, data: dict[str, Any]) -> Policy:
        with transaction.atomic():
            policy = self.policy(policy_id, lock=True)
            if policy.state != PolicyState.DRAFT.value:
                raise SlaConfigError(
                    409,
                    SlaConfigRefusal.NOT_A_DRAFT,
                    "only a draft can change; draft a replacement instead",
                )
            for name in _POLICY_FIELDS:
                if name in data:
                    setattr(policy, name, data[name])
            if "calendar_id" in data:
                policy.calendar = (
                    self.calendar(data["calendar_id"]) if data["calendar_id"] else None
                )
            self.check_targets(policy.response_minutes, policy.resolution_minutes)
            policy.save()
            _audit("sla_policy_drafted", actor, self.snapshot(policy))
        return policy

    def approve(self, actor: User, policy_id: uuid.UUID, reason: str) -> Policy:
        """Activates a draft; its author can't (BR-F1-12). The policy it replaces retires."""
        self.check_reason(reason)
        with transaction.atomic():
            policy = self.policy(policy_id, lock=True)
            if policy.state != PolicyState.DRAFT.value:
                raise SlaConfigError(409, SlaConfigRefusal.NOT_A_DRAFT, "the policy is not a draft")
            if policy.created_by_id == actor.id:
                raise SlaConfigError(
                    403, SlaConfigRefusal.SELF_APPROVAL, "another manager approves your draft"
                )
            replaced = policy.replaces
            clash = Policy.objects.filter(state=PolicyState.ACTIVE.value, order=policy.order)
            if replaced is not None:
                clash = clash.exclude(pk=replaced.pk)
            if clash.exists():
                raise SlaConfigError(
                    409,
                    SlaConfigRefusal.ORDER_TAKEN,
                    f"an active policy already has order {policy.order}",
                )
            if replaced is not None and replaced.state == PolicyState.ACTIVE.value:
                replaced.state = PolicyState.RETIRED.value
                replaced.save(update_fields=["state"])
            policy.state = PolicyState.ACTIVE.value
            policy.approved_by = actor
            policy.approved_at = timezone.now()
            policy.save(update_fields=["state", "approved_by", "approved_at"])
            _audit(
                "sla_policy_activated",
                actor,
                {
                    **self.snapshot(policy),
                    "reason": reason.strip(),
                    "replaces": str(replaced.id) if replaced else None,
                },
            )
        return policy

    def retire(self, actor: User, policy_id: uuid.UUID, reason: str) -> Policy:
        """Retires a policy; the last active default can't go (BR-F1-03)."""
        self.check_reason(reason)
        with transaction.atomic():
            policy = self.policy(policy_id, lock=True)
            if policy.is_default() and policy.state == PolicyState.ACTIVE.value:
                others = Policy.objects.filter(
                    state=PolicyState.ACTIVE.value, category__isnull=True, priority__isnull=True
                ).exclude(pk=policy.pk)
                if not others.exists():
                    raise SlaConfigError(
                        409, SlaConfigRefusal.DEFAULT_POLICY, "the default policy can't be retired"
                    )
            policy.state = PolicyState.RETIRED.value
            policy.save(update_fields=["state"])
            _audit("sla_policy_retired", actor, {**self.snapshot(policy), "reason": reason.strip()})
        return policy

    def check_targets(self, response: int, resolution: int) -> None:
        if response <= 0 or resolution <= 0 or response > resolution:
            raise SlaConfigError(
                422,
                SlaConfigRefusal.INVALID_TARGET,
                "targets are positive and the response target is not above the resolution target",
            )

    def check_reason(self, reason: str) -> None:
        if not reason.strip():
            raise SlaConfigError(422, SlaConfigRefusal.REASON_REQUIRED, "say why")

    def policy(self, policy_id: uuid.UUID, *, lock: bool = False) -> Policy:
        rows = Policy.objects.select_for_update() if lock else Policy.objects.all()
        found = rows.filter(pk=policy_id).first()
        if found is None:
            raise SlaConfigError(404, SlaConfigRefusal.NOT_FOUND, "no such SLA policy")
        return found

    def snapshot(self, policy: Policy) -> dict[str, Any]:
        return {
            "policy": str(policy.id),
            **{name: getattr(policy, name) for name in _POLICY_FIELDS},
            "calendar": policy.calendar.name if policy.calendar else None,
            "state": policy.state,
        }

    # ── calendars and holidays (effective at once, BR-F1-05) ──

    def save_calendar(
        self, actor: User, data: dict[str, Any], calendar_id: uuid.UUID | None = None
    ) -> Calendar:
        try:
            ZoneInfo(data["timezone"]) if "timezone" in data else None
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise SlaConfigError(
                422, SlaConfigRefusal.UNKNOWN_TIMEZONE, f"unknown time zone {data['timezone']!r}"
            ) from e
        if "working_hours" in data:
            try:
                parse_hours(data["working_hours"])
            except CalendarError as e:
                raise SlaConfigError(422, SlaConfigRefusal.BAD_INTERVAL, str(e)) from e
        with transaction.atomic():
            calendar = self.calendar(calendar_id, lock=True) if calendar_id else Calendar()
            before = self.calendar_snapshot(calendar) if calendar_id else None
            for name in ("name", "timezone", "working_hours", "is_default"):
                if data.get(name) is not None:
                    setattr(calendar, name, data[name])
            if data.get("is_default"):
                Calendar.objects.exclude(pk=calendar.pk).update(is_default=False)
            calendar.save()
            _audit(
                "sla_calendar_changed",
                actor,
                {
                    "calendar": calendar.name,
                    "before": before,
                    "after": self.calendar_snapshot(calendar),
                },
            )
        return calendar

    def add_holidays(
        self, actor: User, calendar_id: uuid.UUID, start: date, end: date, name: str
    ) -> list[Holiday]:
        """Whole days off, one or a range (Tết), refused if any day is already one."""
        calendar = self.calendar(calendar_id)
        if end < start:
            raise SlaConfigError(
                422, SlaConfigRefusal.BAD_INTERVAL, "the range ends before it starts"
            )
        days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
        with transaction.atomic():
            taken = list(calendar.holidays.filter(date__in=days).values_list("date", flat=True))
            if taken:
                raise SlaConfigError(
                    409,
                    SlaConfigRefusal.HOLIDAY_EXISTS,
                    f"{taken[0].isoformat()} is already a holiday",
                    {"dates": [d.isoformat() for d in taken]},
                )
            added = [Holiday.objects.create(calendar=calendar, date=d, name=name) for d in days]
            _audit(
                "sla_calendar_changed",
                actor,
                {
                    "calendar": calendar.name,
                    "holidays_added": [d.isoformat() for d in days],
                    "name": name,
                },
            )
        return added

    def remove_holiday(self, actor: User, calendar_id: uuid.UUID, holiday_id: uuid.UUID) -> None:
        holiday = Holiday.objects.filter(pk=holiday_id, calendar_id=calendar_id).first()
        if holiday is None:
            raise SlaConfigError(404, SlaConfigRefusal.NOT_FOUND, "no such holiday")
        with transaction.atomic():
            _audit(
                "sla_calendar_changed",
                actor,
                {"calendar": holiday.calendar.name, "holiday_removed": holiday.date.isoformat()},
            )
            holiday.delete()

    def calendar(self, calendar_id: Any, *, lock: bool = False) -> Calendar:
        rows = Calendar.objects.select_for_update() if lock else Calendar.objects.all()
        found = rows.filter(pk=calendar_id).first()
        if found is None:
            raise SlaConfigError(404, SlaConfigRefusal.NOT_FOUND, "no such calendar")
        return found

    def calendar_snapshot(self, calendar: Calendar) -> dict[str, Any]:
        return {
            "name": calendar.name,
            "timezone": calendar.timezone,
            "working_hours": calendar.working_hours,
            "is_default": calendar.is_default,
        }


# --- the SLA configuration service ---

sla_config = SlaConfig()
