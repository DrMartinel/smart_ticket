"""Rollout flags and gates, and threshold change requests (F9, ADR-0035)."""

from __future__ import annotations

import uuid

from ninja import Router

from apps.accounts.models import Capability, UserRole
from apps.accounts.permissions import (
    STAFF,
    AuthedRequest,
    SessionAuth,
    require_access,
    require_role,
)
from apps.rollout.models import (
    FlagRequest,
    GateChange,
    RolloutFlag,
    RolloutGate,
    ThresholdChangeRequest,
)
from apps.rollout.request_schema import (
    ApproveIn,
    ChangeRequestIn,
    CommentIn,
    FlagRequestIn,
    GateChangeIn,
    ReasonIn,
)
from apps.rollout.response_schema import (
    ChangeRequestDetailOut,
    ChangeRequestOut,
    CurrentThresholdsOut,
    FlagOut,
    FlagRequestOut,
    GateChangeOut,
    GateOut,
    RolloutOut,
    ThresholdsStatusOut,
)
from apps.rollout.utils.gates import rollout_metrics
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.thresholds import threshold_changes
from apps.rollout.utils.vocabulary import (
    FlagBranch,
    RequestState,
    RolloutError,
    RolloutRefusal,
)

router = Router(tags=["rollout"])

# The router branch whose shadow decisions each flag would carry out, and the window shown.
_AGREEMENT_BRANCH = {
    FlagBranch.AUTO_ROUTE: "auto_route",
    FlagBranch.AUTO_REPLY: "auto_reply",
    FlagBranch.REQUESTER_QUESTIONS: "clarify",
}
_AGREEMENT_DAYS = 14
thresholds_router = Router(tags=["thresholds"])


def _rollout() -> RolloutOut:
    snapshot = rollout.snapshot()
    status = rollout.thresholds_status()
    flags = []
    for branch in FlagBranch:
        flag = rollout.flag(branch.value)
        pending = (
            FlagRequest.objects.select_related("requested_by")
            .filter(branch=branch.value, state=RequestState.PENDING.value)
            .first()
        )
        entered = pending.entered_values if pending else rollout.entered_on(flag)
        flags.append(
            FlagOut.of(
                RolloutFlag.objects.select_related("changed_by").get(pk=flag.pk),
                rollout.is_live(branch, snapshot),
                rollout_metrics.snapshot(branch, entered),
                pending,
                rollout_metrics.shadow_agreement(_AGREEMENT_BRANCH[branch], _AGREEMENT_DAYS),
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
        gate_changes=[
            GateChangeOut.of(c)
            for c in GateChange.objects.select_related("requested_by").filter(
                state=RequestState.PENDING.value
            )
        ],
    )


@router.get("", auth=SessionAuth(), response=RolloutOut)
@require_role(*STAFF)
def get_rollout(request: AuthedRequest) -> RolloutOut:
    return _rollout()


@router.post("/{branch}/requests", auth=SessionAuth(), response=FlagRequestOut)
@require_role(UserRole.MANAGER)
def request_on(request: AuthedRequest, branch: str, payload: FlagRequestIn) -> FlagRequestOut:
    made = rollout.request_on(
        branch, request.auth, payload.reason, payload.gate_override_reason, payload.entered_values
    )
    return FlagRequestOut.of(made)


@router.post("/requests/{request_id}/approve", auth=SessionAuth(), response=FlagRequestOut)
@require_role(UserRole.MANAGER)
def approve(request: AuthedRequest, request_id: uuid.UUID, payload: ApproveIn) -> FlagRequestOut:
    return FlagRequestOut.of(
        rollout.approve(request_id, request.auth, payload.gate_override_reason)
    )


@router.post("/requests/{request_id}/reject", auth=SessionAuth(), response=FlagRequestOut)
@require_role(UserRole.MANAGER)
def reject(request: AuthedRequest, request_id: uuid.UUID, payload: ReasonIn) -> FlagRequestOut:
    return FlagRequestOut.of(rollout.reject(request_id, request.auth, payload.reason))


@router.post("/{branch}/off", auth=SessionAuth(), response=RolloutOut)
@require_role(UserRole.MANAGER, UserRole.SECURITY)
def turn_off(request: AuthedRequest, branch: str, payload: ReasonIn) -> RolloutOut:
    rollout.turn_off(branch, request.auth, payload.reason)
    return _rollout()


@router.patch("/gates/{gate_id}", auth=SessionAuth(), response=GateChangeOut)
@require_role(UserRole.MANAGER)
def change_gate(request: AuthedRequest, gate_id: uuid.UUID, payload: GateChangeIn) -> GateChangeOut:
    change = rollout.propose_gate_change(
        gate_id, request.auth, payload.threshold, payload.window_days, payload.reason
    )
    return GateChangeOut.of(change)


@router.post("/gate-changes/{change_id}/approve", auth=SessionAuth(), response=GateChangeOut)
@require_role(UserRole.MANAGER)
def approve_gate_change(request: AuthedRequest, change_id: uuid.UUID) -> GateChangeOut:
    return GateChangeOut.of(rollout.decide_gate_change(change_id, request.auth, approve=True))


@router.post("/gate-changes/{change_id}/reject", auth=SessionAuth(), response=GateChangeOut)
@require_role(UserRole.MANAGER)
def reject_gate_change(request: AuthedRequest, change_id: uuid.UUID) -> GateChangeOut:
    return GateChangeOut.of(rollout.decide_gate_change(change_id, request.auth, approve=False))


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
@require_access(
    roles=(UserRole.MANAGER, UserRole.TECHNICIAN), capabilities=(Capability.WORKFLOW_ADMIN,)
)
def create_change(request: AuthedRequest, payload: ChangeRequestIn) -> ChangeRequestDetailOut:
    made = threshold_changes.create(request.auth, payload.yaml_text, payload.evidence)
    return ChangeRequestDetailOut.detail(_change(made.id))


@thresholds_router.post(
    "/change-requests/{request_id}/submit", auth=SessionAuth(), response=ChangeRequestOut
)
@require_role(*STAFF)
def submit_change(request: AuthedRequest, request_id: uuid.UUID) -> ChangeRequestOut:
    threshold_changes.submit(request_id, request.auth)
    return ChangeRequestOut.of(_change(request_id))


@thresholds_router.post(
    "/change-requests/{request_id}/approve", auth=SessionAuth(), response=ChangeRequestOut
)
@require_role(*STAFF)
def approve_change(
    request: AuthedRequest, request_id: uuid.UUID, payload: CommentIn
) -> ChangeRequestOut:
    threshold_changes.approve(request_id, request.auth, payload.comment)
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
