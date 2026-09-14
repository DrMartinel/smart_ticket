#!/usr/bin/env python3
"""
Choose T_auto / T_route from a precision-recall curve — spec §7.1.

    T_auto  = smallest trust threshold with auto-reply precision >= 0.95
    T_route = smallest trust threshold with auto-route precision >= 0.85

Chosen by PRECISION, not accuracy, and intentionally asymmetric: a wrong
auto-route costs one reroute click (spec calls this "rẻ" — cheap, and it
even produces a free training label); a wrong auto-reply is a closed
ticket with wrong information the user already acted on (spec: "sai số
của auto-reply đắt"). That's why T_route is allowed to be lower than
T_auto — precision requirements below reflect that asymmetry, not the
other way around.

Usage:
    uv run --package evals python evals/calibration/choose_thresholds.py \\
        --model services/core-api/config/trust_model_v0.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import django
import numpy as np

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://app_user:app_password@localhost:5434/smart_triage"
)
os.environ.setdefault("SECRET_KEY", "calibration-script-key")
django.setup()

from contracts.trust import TrustSignals  # noqa: E402

from apps.review.models import ReviewDecision  # noqa: E402
from apps.tickets.services.trust_scorer import extract_features  # noqa: E402

T_AUTO_PRECISION_FLOOR = 0.95
T_ROUTE_PRECISION_FLOOR = 0.85


def _score_with_model(signals: TrustSignals, model: dict) -> float:
    from apps.tickets.services.trust_scorer import FEATURES

    x = extract_features(signals)
    z = model["intercept"] + sum(model["weights"][f] * x[f] for f in FEATURES)
    return 1.0 / (1.0 + np.exp(-z))


def _collect(intent: str, verdict_field: str, model: dict) -> tuple[list[float], list[int]]:
    """Re-scores every case with `model` rather than trusting the
    `trust_score` value stored on each `ai_run` — those rows may span
    several model versions over time (whatever was active when each ran),
    which would make the resulting PR curve a mix of models rather than a
    curve for the specific model these thresholds are being chosen for."""

    scores, labels = [], []
    decisions = (
        ReviewDecision.objects.select_related("review_item__ai_run")
        .exclude(review_item__ai_run__isnull=True)
        .exclude(review_item__ai_run__trust_signals__isnull=True)
    )
    for decision in decisions.iterator():
        ai_run = decision.review_item.ai_run
        draft = ai_run.proposed_draft or {}
        if (
            draft.get("root", {}).get("proposed_intent") != intent
            and draft.get("proposed_intent") != intent
        ):
            continue
        verdict = getattr(decision, verdict_field, None)
        if verdict is None:
            continue
        try:
            signals = TrustSignals(**ai_run.trust_signals)
        except Exception:  # noqa: BLE001
            continue
        scores.append(_score_with_model(signals, model))
        labels.append(1 if verdict == "correct" else 0)
    return scores, labels


def _smallest_threshold_for_precision(
    scores: list[float], labels: list[int], floor: float
) -> float | None:
    if not scores or len(set(labels)) < 2:
        return None
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(labels, scores)
    # precision_recall_curve returns len(thresholds) = len(precision) - 1
    candidates = [(t, p) for t, p in zip(thresholds, precision[:-1]) if p >= floor]
    if not candidates:
        return None
    return min(t for t, _ in candidates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "services/core-api/config/trust_model_v0.json",
    )
    args = parser.parse_args()

    with open(args.model) as f:
        model = json.load(f)
    print(f"scoring with model_version={model['model_version']!r} from {args.model}")

    auto_scores, auto_labels = _collect("auto_reply", "kb_verdict", model)
    route_scores, route_labels = _collect("route_to_team", "category_verdict", model)

    print(f"auto_reply-eligible decisions: {len(auto_labels)} (positives={sum(auto_labels)})")
    print(f"route_to_team-eligible decisions: {len(route_labels)} (positives={sum(route_labels)})")

    t_auto = _smallest_threshold_for_precision(auto_scores, auto_labels, T_AUTO_PRECISION_FLOOR)
    t_route = _smallest_threshold_for_precision(route_scores, route_labels, T_ROUTE_PRECISION_FLOOR)

    print()
    if t_auto is not None:
        print(
            f"t_auto  = {t_auto:.4f}   (smallest threshold with auto-reply precision >= {T_AUTO_PRECISION_FLOOR})"
        )
    else:
        print(
            f"t_auto  = UNDETERMINED — not enough labeled auto_reply decisions yet, "
            f"or no threshold achieves precision >= {T_AUTO_PRECISION_FLOOR}. Keep the current "
            f"thresholds.yaml value until more shadow data accumulates."
        )
    if t_route is not None:
        print(
            f"t_route = {t_route:.4f}   (smallest threshold with auto-route precision >= {T_ROUTE_PRECISION_FLOOR})"
        )
    else:
        print(
            f"t_route = UNDETERMINED — not enough labeled route_to_team decisions yet, "
            f"or no threshold achieves precision >= {T_ROUTE_PRECISION_FLOOR}. Keep the current "
            f"thresholds.yaml value until more shadow data accumulates."
        )

    print(
        "\nThese values are a RECOMMENDATION, not an automatic write to thresholds.yaml — "
        "spec §12.3's discipline (update requires review) applies to threshold changes too, "
        "not only to eval baselines."
    )


if __name__ == "__main__":
    main()
