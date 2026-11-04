"""Rollout flags and gates, and threshold change requests (F9, ADR-0035)."""

from __future__ import annotations

import uuid

from django.conf import settings
from ninja import Router

from apps.accounts.models import UserRole
from apps.accounts.permissions import (
    STAFF,
    AuthedRequest,
    SessionAuth,
    require_role,
)
from apps.rollout.models import (
    RolloutFlag,
    RolloutGate,
    ThresholdChangeRequest,
)
from apps.rollout.request_schema import (
    ChangeRequestIn,
    CommentIn,
    FlagOnIn,
    GateChangeIn,
    ReasonIn,
)
from apps.rollout.response_schema import (
    ChangeRequestDetailOut,
    ChangeRequestOut,
    CurrentThresholdsOut,
    FlagOut,
    GateChangeOut,
    GateOut,
    RolloutOut,
    ThresholdsStatusOut,
)
from apps.rollout.utils.gates import AGREEMENT_BRANCH, rollout_metrics
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.thresholds import threshold_changes
from apps.rollout.utils.vocabulary import (
    FlagBranch,
    RolloutError,
    RolloutRefusal,
)

router = Router(tags=["rollout"])

# The router branch whose shadow decisions each flag would carry out, and the window shown.
thresholds_router = Router(tags=["thresholds"])


def _rollout() -> RolloutOut:
    snapshot = rollout.snapshot()
    status = rollout.thresholds_status()
    flags = []
    for branch in FlagBranch:
        flag = rollout.flag(branch.value)
        flags.append(
            FlagOut.of(
                RolloutFlag.objects.select_related("changed_by").get(pk=flag.pk),
                rollout.is_live(branch, snapshot),
                rollout_metrics.snapshot(branch, rollout.entered_on(flag)),
                rollout_metrics.shadow_agreement(
                    AGREEMENT_BRANCH[branch], settings.THRESHOLDS.reports.rollout_days
                ),
            )
        )
    return RolloutOut(
        env_shadow=snapshot["env_shadow"],
        thresholds=ThresholdsStatusOut(
            version=status.version,
            sha256=status.sha256,
            approved=status.approved,
            checked=status.checked,
            change_request=status.change_request,
        ),
        flags=flags,
        gates=[
            GateOut.model_validate(g, from_attributes=True)
            for g in RolloutGate.objects.filter(is_active=True).order_by("branch", "metric")
        ],
    )


@router.get("", auth=SessionAuth(), response=RolloutOut)
@require_role(*STAFF)
def get_rollout(request: AuthedRequest) -> RolloutOut:
    return _rollout()


@router.post("/{branch}/on", auth=SessionAuth(), response=RolloutOut)
@require_role(UserRole.MANAGER)
def turn_on(request: AuthedRequest, branch: str, payload: FlagOnIn) -> RolloutOut:
    rollout.turn_on(
        branch, request.auth, payload.reason, payload.gate_override_reason, payload.entered_values
    )
    return _rollout()


@router.post("/{branch}/off", auth=SessionAuth(), response=RolloutOut)
@require_role(UserRole.MANAGER, UserRole.SECURITY)
def turn_off(request: AuthedRequest, branch: str, payload: ReasonIn) -> RolloutOut:
    rollout.turn_off(branch, request.auth, payload.reason)
    return _rollout()


@router.patch("/gates/{gate_id}", auth=SessionAuth(), response=GateChangeOut)
@require_role(UserRole.MANAGER)
def change_gate(request: AuthedRequest, gate_id: uuid.UUID, payload: GateChangeIn) -> GateChangeOut:
    change = rollout.change_gate(
        gate_id, request.auth, payload.threshold, payload.window_days, payload.reason
    )
    return GateChangeOut.of(change)


# ── thresholds ──


def _change(request_id: uuid.UUID) -> ThresholdChangeRequest:
    found = ThresholdChangeRequest.objects.select_related("author").filter(pk=request_id).first()
    if found is None:
        raise RolloutError(404, RolloutRefusal.NOT_FOUND, "no such change request")
    return found


@thresholds_router.get("/current", auth=SessionAuth(), response=CurrentThresholdsOut)
@require_role(*STAFF)
def current(request: AuthedRequest) -> CurrentThresholdsOut:
    status = rollout.thresholds_status()
    loaded = (
        ThresholdChangeRequest.objects.filter(version=status.change_request).first()
        if status.change_request
        else None
    )
    return CurrentThresholdsOut(
        version=status.version,
        sha256=status.sha256,
        approved=status.approved,
        checked=status.checked,
        change_request=status.change_request,
        loaded_at=loaded.loaded_at if loaded else None,
        next_version=threshold_changes.next_id(),
        yaml=threshold_changes.current_text(),
    )


@thresholds_router.get("/history", auth=SessionAuth(), response=list[ChangeRequestOut])
@require_role(*STAFF)
def history(request: AuthedRequest) -> list[ChangeRequestOut]:
    return [
        ChangeRequestOut.of(r)
        for r in ThresholdChangeRequest.objects.select_related("author").order_by("-created_at")
    ]


@thresholds_router.get(
    "/change-requests/{request_id}", auth=SessionAuth(), response=ChangeRequestDetailOut
)
@require_role(*STAFF)
def change_request(request: AuthedRequest, request_id: uuid.UUID) -> ChangeRequestDetailOut:
    return ChangeRequestDetailOut.detail(_change(request_id))


@thresholds_router.post("/change-requests", auth=SessionAuth(), response=ChangeRequestDetailOut)
@require_role(UserRole.MANAGER)
def create_change(request: AuthedRequest, payload: ChangeRequestIn) -> ChangeRequestDetailOut:
    made = threshold_changes.create(request.auth, payload.yaml_text, payload.evidence)
    return ChangeRequestDetailOut.detail(_change(made.id))


@thresholds_router.post(
    "/change-requests/{request_id}/submit", auth=SessionAuth(), response=ChangeRequestOut
)
@require_role(UserRole.MANAGER)
def submit_change(request: AuthedRequest, request_id: uuid.UUID) -> ChangeRequestOut:
    threshold_changes.submit(request_id, request.auth)
    return ChangeRequestOut.of(_change(request_id))


@thresholds_router.post(
    "/change-requests/{request_id}/reject", auth=SessionAuth(), response=ChangeRequestOut
)
@require_role(*STAFF)
def reject_change(
    request: AuthedRequest, request_id: uuid.UUID, payload: CommentIn
) -> ChangeRequestOut:
    threshold_changes.reject(request_id, request.auth, payload.comment)
    return ChangeRequestOut.of(_change(request_id))
