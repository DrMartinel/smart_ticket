"""Test helpers for rollout (F9): hold a branch back."""

from __future__ import annotations

from apps.rollout.models import RolloutFlag
from apps.rollout.domain.vocabulary import FlagBranch, FlagState


def flags_off(*branches: FlagBranch) -> None:
    """Turns each branch's flag off, so its decisions are held back (ADR-0051)."""
    for branch in branches:
        RolloutFlag.objects.update_or_create(
            branch=branch.value, defaults={"state": FlagState.OFF.value}
        )
