"""Test helpers for rollout (F9): put every automated branch live."""

from __future__ import annotations

from typing import Any

from apps.rollout.models import RolloutFlag
from apps.rollout.utils.vocabulary import FlagBranch, FlagState


def all_live(settings: Any) -> None:
    """SHADOW_MODE off and every flag on."""
    settings.SHADOW_MODE = False
    for branch in FlagBranch:
        RolloutFlag.objects.update_or_create(
            branch=branch.value, defaults={"state": FlagState.ON.value}
        )
