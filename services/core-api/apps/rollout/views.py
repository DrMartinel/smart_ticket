"""Rollout flags and gates, and the loaded thresholds (F9, ADR-0035, ADR-0044)."""

from __future__ import annotations

import uuid

from django.conf import settings
from ninja import Router

from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.rollout.models import RolloutFlag, RolloutGate
from apps.rollout.request_schema import FlagOnIn, GateChangeIn, ReasonIn
from apps.rollout.response_schema import (
    CurrentThresholdsOut,
    FlagOut,
    GateChangeOut,
    GateOut,
    RolloutOut,
)
from apps.rollout.utils.gates import AGREEMENT_BRANCH, rollout_metrics
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.vocabulary import FlagBranch

router = Router(tags=["rollout"])

thresholds_router = Router(tags=["thresholds"])


def _rollout() -> RolloutOut:
    snapshot = rollout.snapshot()
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
        thresholds=snapshot["thresholds"],
        flags=flags,
        gates=[
            GateOut.model_validate(g, from_attributes=True)
            for g in RolloutGate.objects.filter(is_active=True).order_by("branch", "metric")
        ],
    )


@router.get("", auth=SessionAuth(), response=RolloutOut)
@require(Permission.ROLLOUT_READ, agent=AgentTier.NONE)
def get_rollout(request: AuthedRequest) -> RolloutOut:
    return _rollout()


@router.post("/{branch}/on", auth=SessionAuth(), response=RolloutOut)
@require(Permission.ROLLOUT_FLAG_ON, agent=AgentTier.NONE)
def turn_on(request: AuthedRequest, branch: str, payload: FlagOnIn) -> RolloutOut:
    rollout.turn_on(
        branch,
        request.auth.user,
        payload.reason,
        payload.gate_override_reason,
        payload.entered_values,
    )
    return _rollout()


@router.post("/{branch}/off", auth=SessionAuth(), response=RolloutOut)
@require(Permission.ROLLOUT_FLAG_OFF, agent=AgentTier.NONE)
def turn_off(request: AuthedRequest, branch: str, payload: ReasonIn) -> RolloutOut:
    rollout.turn_off(branch, request.auth.user, payload.reason)
    return _rollout()


@router.patch("/gates/{gate_id}", auth=SessionAuth(), response=GateChangeOut)
@require(Permission.ROLLOUT_GATES_MANAGE, agent=AgentTier.NONE)
def change_gate(request: AuthedRequest, gate_id: uuid.UUID, payload: GateChangeIn) -> GateChangeOut:
    change = rollout.change_gate(
        gate_id, request.auth.user, payload.threshold, payload.window_days, payload.reason
    )
    return GateChangeOut.of(change)


# ── thresholds ──


@thresholds_router.get("/current", auth=SessionAuth(), response=CurrentThresholdsOut)
@require(Permission.ROLLOUT_THRESHOLDS_READ, agent=AgentTier.NONE)
def current(request: AuthedRequest) -> CurrentThresholdsOut:
    return CurrentThresholdsOut.loaded()
