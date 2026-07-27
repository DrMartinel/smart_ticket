#!/usr/bin/env python3
"""
Fit the trust-score logistic regression on shadow-mode data — spec §7.1.

Reads (TrustSignals, ground_truth) pairs from the real database:
- `TrustSignals` comes from `ai_runs.trust_signals` (what the AI actually saw).
- Ground truth comes from the paired `review_decisions` row: a decision
  is treated as "correct" when a human approved it outright (kb_verdict /
  category_verdict == "correct" and action_taken == "approve"), and
  "incorrect" for any override (edit_and_send, reject, reroute, escalate)
  — i.e. exactly the human-labeling signal spec §12.4 describes as a free
  label source.

Usage:
    uv run --package evals python evals/calibration/fit_trust_score.py [--min-n 500] [--out PATH]

Writes a new versioned model file (default:
services/core-api/config/trust_model_<date>.json) — it does NOT overwrite
`trust_model_v0.json` or flip which model is active. Wiring a new model
version into production is a deliberate, reviewed config change (bump
`TRUST_MODEL_PATH` / rename the file core-api actually loads), matching
spec §12.3's discipline for anything that changes routing behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import django
import numpy as np

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
os.environ.setdefault("DATABASE_URL", "postgresql://app_user:app_password@localhost:5434/smart_triage")
os.environ.setdefault("SECRET_KEY", "calibration-script-key")
django.setup()

from contracts.trust import TrustSignals  # noqa: E402

from apps.review.models import ReviewDecision  # noqa: E402
from apps.tickets.services.trust_scorer import FEATURES, extract_features  # noqa: E402

SHADOW_MODE_MIN_N = 500  # spec §7.1 / §14 P1 exit condition


def load_shadow_pairs() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Returns (X, y, case_ids). y=1 means the human approved outright."""

    X, y, ids = [], [], []
    decisions = (
        ReviewDecision.objects.select_related("review_item", "review_item__ai_run")
        .exclude(review_item__ai_run__isnull=True)
        .exclude(review_item__ai_run__trust_signals__isnull=True)
    )
    for decision in decisions.iterator():
        ai_run = decision.review_item.ai_run
        try:
            signals = TrustSignals(**ai_run.trust_signals)
        except Exception:  # noqa: BLE001 — skip malformed/legacy rows rather than crash the fit
            continue
        features = extract_features(signals)
        X.append([features[f] for f in FEATURES])
        y.append(1 if decision.action_taken == "approve" else 0)
        ids.append(str(decision.id))

    return np.array(X, dtype=float), np.array(y, dtype=int), ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-n", type=int, default=SHADOW_MODE_MIN_N)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "services/core-api/config"
        / f"trust_model_{date.today().isoformat()}.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="fit and write even if n < --min-n (the resulting model MUST NOT be wired into production)",
    )
    args = parser.parse_args()

    X, y, _ids = load_shadow_pairs()
    n = len(y)
    print(f"loaded {n} (signals, human_decision) pairs from review_decisions")

    if n < args.min_n and not args.force:
        print(
            f"REFUSING to fit: n={n} < required minimum {args.min_n} (spec §7.1/§14 P1 exit "
            "condition — shadow mode needs 500+ pairs before calibration is trustworthy).\n"
            "Run with --force to fit anyway for development purposes; the result must not "
            "be treated as a real calibration and must not be wired into production."
        )
        sys.exit(1)

    if len(set(y.tolist())) < 2:
        print("REFUSING to fit: all labels are the same class — need both approvals and overrides.")
        sys.exit(1)

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if min(np.bincount(y)) >= 2 else None
    )

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)

    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test) if len(X_test) else float("nan")
    print(f"train accuracy={train_acc:.3f}  test accuracy={test_acc:.3f} (n_test={len(X_test)})")

    out = {
        "model_version": f"logreg-v1-{date.today().isoformat()}",
        "note": (
            f"Fit by evals/calibration/fit_trust_score.py on {n} shadow-mode "
            f"(signals, human_decision) pairs. train_acc={train_acc:.3f} test_acc={test_acc:.3f}. "
            "NOT automatically wired into production — see this script's module docstring."
        ),
        "intercept": float(model.intercept_[0]),
        "weights": {feat: float(w) for feat, w in zip(FEATURES, model.coef_[0])},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
