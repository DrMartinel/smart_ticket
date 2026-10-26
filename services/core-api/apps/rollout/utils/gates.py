"""The numbers a branch's gate reads (BR-F9-04), and shadow agreement, which F10 reports from the same
query (BR-F10-10)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from django.db.models import F, Q
from django.utils import timezone

from apps.rollout.models import RolloutGate
from apps.rollout.utils.vocabulary import ENTERED_METRICS, FlagBranch, GateMetric


@dataclass(frozen=True)
class Agreement:
    """Shadow decisions of a branch a reviewer decided, and how many they agreed with."""

    decided: int
    agreed: int
    rerouted: int

    @property
    def rate(self) -> float | None:
        return self.agreed / self.decided if self.decided else None

    @property
    def reroute_rate(self) -> float | None:
        return self.rerouted / self.decided if self.decided else None


@dataclass(frozen=True)
class GateValue:
    """One gate with its current value, as the Rollout page and an approval record it."""

    metric: str
    comparator: str
    threshold: float
    window_days: int | None
    phase: str
    value: float | None
    met: bool
    entered: bool
    evidence: str = ""

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


class RolloutMetrics:
    """Reads the operational tables for gate values."""

    def shadow_agreement(self, branch: str, days: int) -> Agreement:
        """Shadow decisions of `branch` in the window whose ticket a reviewer decided: agreed =
        approved, and for `auto_route` with the category not corrected (BR-F10-10)."""
        from apps.review.models import ReviewDecision

        since = timezone.now() - timedelta(days=days)
        decisions = ReviewDecision.objects.filter(
            decided_at__gte=since,
            review_item__ai_run__routing_decisions__branch=branch,
            review_item__ai_run__routing_decisions__shadow_mode=True,
        ).distinct()
        approved = Q(action_taken="approve")
        if branch == "auto_route":
            approved &= Q(corrected_category__isnull=True) | Q(
                corrected_category=F("review_item__ticket__category")
            )
        return Agreement(
            decided=decisions.count(),
            agreed=decisions.filter(approved).count(),
            rerouted=decisions.filter(action_taken="reroute").count(),
        )

    def approved_low_pages(self) -> int:
        from apps.kb.models import KbArticle

        return KbArticle.objects.filter(
            is_active=True, auto_reply_allowed=True, risk_tier="low"
        ).count()

    def value(self, gate: RolloutGate, entered: dict[str, Any]) -> tuple[float | None, str]:
        """A gate's value now, and its evidence when the requester entered it."""
        metric = GateMetric(gate.metric)
        if metric in ENTERED_METRICS:
            given = entered.get(metric.value) or {}
            raw = given.get("value")
            return (float(raw) if raw is not None else None), str(given.get("evidence", ""))
        if metric is GateMetric.APPROVED_LOW_PAGES:
            return float(self.approved_low_pages()), ""
        days = gate.window_days or 14
        if metric is GateMetric.REROUTE_RATE:
            return self.shadow_agreement("auto_route", days).reroute_rate, ""
        return self.shadow_agreement("clarify", days).rate, ""

    def snapshot(self, branch: FlagBranch, entered: dict[str, Any]) -> list[GateValue]:
        """Every active gate of `branch` with its value now."""
        values = []
        for gate in RolloutGate.objects.filter(branch=branch.value, is_active=True).order_by(
            "metric"
        ):
            value, evidence = self.value(gate, entered)
            values.append(
                GateValue(
                    metric=gate.metric,
                    comparator=gate.comparator,
                    threshold=gate.threshold,
                    window_days=gate.window_days,
                    phase=gate.phase,
                    value=value,
                    met=gate.met_by(value),
                    entered=GateMetric(gate.metric) in ENTERED_METRICS,
                    evidence=evidence,
                )
            )
        return values


# --- the rollout metrics ---

rollout_metrics = RolloutMetrics()
