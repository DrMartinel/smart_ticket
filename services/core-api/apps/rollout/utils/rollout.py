"""Which automated branches act live (BR-F9-01): the env switch, the branch's flag and approved
thresholds, all three. One manager turns a flag on or off (ADR-0035, ADR-0043)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.rollout.models import (
    FlagRequest,
    GateChange,
    RolloutFlag,
    RolloutGate,
    ThresholdChangeRequest,
)
from apps.rollout.utils.gates import GateValue, rollout_metrics
from apps.rollout.utils.vocabulary import (
    APPROVED_CHANGE_STATES,
    ENTERED_METRICS,
    ChangeState,
    FlagBranch,
    FlagState,
    RequestState,
    RolloutError,
    RolloutRefusal,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThresholdsStatus:
    """The loaded thresholds file and whether it may act live."""

    sha256: str
    version: str
    approved: bool
    checked: bool
    change_request: str | None


def file_sha256() -> str:
    """SHA-256 of the thresholds.yaml core-api loaded."""
    with open(settings.THRESHOLDS_PATH, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Rollout:
    """Live or shadow per decision, and every change to a flag or gate."""

    def __init__(self) -> None:
        # The thresholds check, once per process per file (BR-F9-07).
        self._status: ThresholdsStatus | None = None

    # ── live or shadow (BR-F9-01) ──

    def thresholds_status(self) -> ThresholdsStatus:
        """Matches the loaded file's hash to an approved change request, once per process: marks
        it loaded, or raises `thresholds_unapproved`."""
        sha = file_sha256()
        require = settings.THRESHOLDS_REQUIRE_APPROVAL
        if self._status is not None and (self._status.sha256, self._status.checked) == (
            sha,
            require,
        ):
            return self._status
        version = settings.THRESHOLDS.version
        if not require:
            self._status = ThresholdsStatus(sha, version, True, False, None)
            return self._status
        request = (
            ThresholdChangeRequest.objects.filter(
                sha256=sha, state__in=[s.value for s in APPROVED_CHANGE_STATES]
            )
            .order_by("-approved_at")
            .first()
        )
        if request is None:
            self.unapproved(sha, version)
            self._status = ThresholdsStatus(sha, version, False, True, None)
            return self._status
        if request.state != ChangeState.LOADED.value:
            with transaction.atomic():
                updated = ThresholdChangeRequest.objects.filter(
                    pk=request.pk, state=ChangeState.APPROVED.value
                ).update(state=ChangeState.LOADED.value, loaded_at=timezone.now())
                if updated:
                    AuditLog.objects.record(
                        "thresholds_loaded",
                        actor_type="system",
                        payload={"version": request.version, "sha256": sha},
                    )
        self._status = ThresholdsStatus(sha, version, True, True, request.version)
        return self._status

    def unapproved(self, sha: str, version: str) -> None:
        """Every branch shadow: security alerted and managers told, once per file."""
        from apps.security.utils.alerts import security_alerts
        from apps.security.utils.vocabulary import AlertKind

        logger.error("thresholds.yaml %s (%s) matches no approved change request", version, sha)
        with transaction.atomic():
            security_alerts.raise_(
                AlertKind.THRESHOLDS_UNAPPROVED,
                payload={"sha256": sha, "version": version},
                detail=f"thresholds.yaml {version} ({sha[:12]}) is not approved",
            )
            AuditLog.objects.record(
                "thresholds_unapproved",
                actor_type="system",
                payload={"sha256": sha, "version": version},
            )
            notifier.emit(
                NotificationEvent.THRESHOLDS_UNAPPROVED,
                notice=Notice(
                    reason=version,
                    detail=f"sha256 {sha[:12]}…",
                    data={"sha256": sha, "version": version},
                ),
                event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"thresholds_unapproved:{sha}"),
            )

    def snapshot(self) -> dict[str, Any]:
        """What a decision runs under: each flag, the env switch, the thresholds (BR-F9-09)."""
        states = dict(RolloutFlag.objects.values_list("branch", "state"))
        status = self.thresholds_status()
        return {
            **{b.value: states.get(b.value, FlagState.OFF.value) for b in FlagBranch},
            "env_shadow": settings.SHADOW_MODE,
            "thresholds": status.change_request or status.version,
            "thresholds_approved": status.approved,
        }

    def is_live(self, branch: FlagBranch, snapshot: dict[str, Any] | None = None) -> bool:
        """Env not shadow, the branch's flag on, thresholds approved; any one missing is shadow."""
        snapshot = snapshot if snapshot is not None else self.snapshot()
        return (
            not snapshot["env_shadow"]
            and snapshot.get(branch.value) == FlagState.ON.value
            and bool(snapshot["thresholds_approved"])
        )

    # ── turning a branch on (UC-F9-01) ──

    def flag(self, branch: str) -> RolloutFlag:
        """The flag of a branch that has one; runbooks have none (BR-F9-10)."""
        if branch not in {b.value for b in FlagBranch}:
            raise RolloutError(404, RolloutRefusal.NO_SUCH_BRANCH, f"no flag for {branch!r}")
        flag, _ = RolloutFlag.objects.get_or_create(branch=branch)
        return flag

    def check_manager(self, actor: User) -> None:
        if actor.role != UserRole.MANAGER.value:
            raise RolloutError(403, RolloutRefusal.NOT_A_MANAGER, "only a manager may do this")

    def turn_on(
        self,
        branch: str,
        actor: User,
        reason: str,
        gate_override_reason: str = "",
        entered: dict[str, Any] | None = None,
    ) -> FlagRequest:
        """A manager turns a branch live at once, with a reason, the gate values now and an
        override reason for any gate not met (ADR-0043)."""
        self.check_manager(actor)
        reason = reason.strip()
        if not reason:
            raise RolloutError(422, RolloutRefusal.REASON_REQUIRED, "say why")
        entered = entered or {}
        with transaction.atomic():
            flag = RolloutFlag.objects.select_for_update().get(pk=self.flag(branch).pk)
            if flag.state == FlagState.ON.value:
                raise RolloutError(409, RolloutRefusal.ALREADY_ON, f"{branch} is already on")
            if not self.thresholds_status().approved:
                raise RolloutError(
                    409,
                    RolloutRefusal.THRESHOLDS_UNAPPROVED,
                    "the loaded thresholds aren't approved",
                )
            gates = rollout_metrics.snapshot(FlagBranch(branch), entered)
            self.check_entered(gates)
            unmet = [g.metric for g in gates if not g.met]
            override = gate_override_reason.strip()
            if unmet and not override:
                raise RolloutError(
                    422,
                    RolloutRefusal.OVERRIDE_REASON_REQUIRED,
                    f"gates not met: {', '.join(unmet)}; give an override reason",
                    details={"unmet": unmet},
                )
            now = timezone.now()
            snapshot = [g.as_json() for g in gates]
            request = FlagRequest.objects.create(
                branch=branch,
                requested_by=actor,
                reason=reason,
                gate_override_reason=override,
                entered_values=entered,
                gate_snapshot_at_request=snapshot,
                approvals=[
                    {
                        "user": actor.username,
                        "at": now.isoformat(),
                        "gate_snapshot": snapshot,
                        "override_reason": override,
                    }
                ],
                state=RequestState.APPROVED.value,
                decided_at=now,
                expires_at=now,
            )
            self.set_flag(flag, FlagState.ON, actor, reason)
            AuditLog.objects.record(
                "rollout_flag_on",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "branch": branch,
                    "request": str(request.id),
                    "gates": snapshot,
                    "unmet": unmet,
                    "override_reason": override,
                },
            )
            self.announce(branch, FlagState.ON, actor, reason)
        return request

    def check_entered(self, gates: list[GateValue]) -> None:
        """A gate whose value is entered needs a value and evidence (owner, 2026-10-26)."""
        for gate in gates:
            if gate.entered and (gate.value is None or not gate.evidence.strip()):
                raise RolloutError(
                    422,
                    RolloutRefusal.ENTERED_VALUE_REQUIRED,
                    f"enter {gate.metric} with the evidence it comes from",
                )

    # ── turning a branch off (UC-F9-02) ──

    def turn_off(self, branch: str, actor: User, reason: str) -> RolloutFlag:
        """Any manager or security, alone, at once (BR-F9-02)."""
        if actor.role not in (UserRole.MANAGER.value, UserRole.SECURITY.value):
            raise RolloutError(403, RolloutRefusal.NOT_A_MANAGER, "managers and security only")
        reason = reason.strip()
        if not reason:
            raise RolloutError(422, RolloutRefusal.REASON_REQUIRED, "say why")
        with transaction.atomic():
            flag = RolloutFlag.objects.select_for_update().get(pk=self.flag(branch).pk)
            if flag.state == FlagState.OFF.value:
                raise RolloutError(409, RolloutRefusal.ALREADY_OFF, f"{branch} is already off")
            self.set_flag(flag, FlagState.OFF, actor, reason)
            AuditLog.objects.record(
                "rollout_flag_off",
                actor_type="human",
                actor_id=actor.id,
                payload={"branch": branch, "reason": reason},
            )
            self.announce(branch, FlagState.OFF, actor, reason)
        return flag

    def set_flag(
        self, flag: RolloutFlag, state: FlagState, actor: User | None, reason: str
    ) -> None:
        flag.state = state.value
        flag.changed_by = actor
        flag.changed_at = timezone.now()
        flag.reason = reason
        flag.save(update_fields=["state", "changed_by", "changed_at", "reason"])

    def announce(self, branch: str, state: FlagState, actor: User, reason: str) -> None:
        notifier.emit(
            NotificationEvent.ROLLOUT_FLAG_CHANGED,
            notice=Notice(
                actor=actor.username,
                reason=f"{branch} {state.value}",
                message=reason,
                data={"branch": branch, "state": state.value},
            ),
        )

    # ── gates (BR-F9-04, AC-F9-08) ──

    def change_gate(
        self,
        gate_id: uuid.UUID,
        actor: User,
        threshold: float,
        window_days: int | None,
        reason: str,
    ) -> GateChange:
        """A manager changes a gate at once (ADR-0043); the change row records it."""
        self.check_manager(actor)
        if not reason.strip():
            raise RolloutError(422, RolloutRefusal.REASON_REQUIRED, "say why")
        with transaction.atomic():
            gate = RolloutGate.objects.select_for_update().filter(pk=gate_id).first()
            if gate is None:
                raise RolloutError(404, RolloutRefusal.NOT_FOUND, "no such gate")
            before = {"threshold": gate.threshold, "window_days": gate.window_days}
            now = timezone.now()
            change = GateChange.objects.create(
                gate=gate,
                threshold=threshold,
                window_days=window_days,
                reason=reason.strip(),
                requested_by=actor,
                state=RequestState.APPROVED.value,
                decided_by=actor,
                decided_at=now,
            )
            gate.threshold = threshold
            gate.window_days = window_days
            gate.save(update_fields=["threshold", "window_days"])
            AuditLog.objects.record(
                "rollout_gate_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "gate": str(gate.id),
                    "change": str(change.id),
                    "from": before,
                    "to": {"threshold": threshold, "window_days": window_days},
                },
            )
        return change

    # ── the sweep ──

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Re-checks the thresholds, and once a day tells managers about a live branch whose gate
        is no longer met."""
        now = now or timezone.now()
        self._status = None
        self.thresholds_status()
        unmet = 0
        for flag in RolloutFlag.objects.filter(state=FlagState.ON.value):
            missed = [
                g.metric
                for g in rollout_metrics.snapshot(FlagBranch(flag.branch), self.entered_on(flag))
                if not g.met and g.metric not in ENTERED_METRICS
            ]
            if missed:
                notifier.emit(
                    NotificationEvent.ROLLOUT_GATE_UNMET,
                    notice=Notice(
                        reason=flag.branch,
                        detail=", ".join(missed),
                        data={"branch": flag.branch, "unmet": missed},
                    ),
                    event_id=uuid.uuid5(
                        uuid.NAMESPACE_URL, f"gate_unmet:{flag.branch}:{now.date().isoformat()}"
                    ),
                )
                unmet += 1
        return {"gate_unmet": unmet}

    def entered_on(self, flag: RolloutFlag) -> dict[str, Any]:
        """The entered values of the request that turned the flag on."""
        request = (
            FlagRequest.objects.filter(branch=flag.branch, state=RequestState.APPROVED.value)
            .order_by("-decided_at")
            .first()
        )
        return request.entered_values if request else {}


# --- the rollout service ---

rollout = Rollout()
