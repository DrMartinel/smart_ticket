"""Three flags off, the README's gates, and CR-2026-000: the thresholds.yaml on disk at migration
time, approved as the baseline so the first boot after F9 isn't forced to shadow (F9 §g)."""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import migrations

FLAGS = ("auto_route", "auto_reply", "requester_questions")
# branch, phase, metric, comparator, threshold, window_days (BR-F9-04)
GATES = [
    ("auto_route", "P3", "reroute_rate", "lt", 0.15, 14),
    ("auto_reply", "P4", "holdout_precision", "gte", 0.95, None),
    ("auto_reply", "P4", "approved_low_pages", "gte", 3, None),
    ("requester_questions", "P3", "clarify_agreement", "gte", 0.80, 14),
]


def seed(apps, schema_editor):
    Flag = apps.get_model("rollout", "RolloutFlag")
    Gate = apps.get_model("rollout", "RolloutGate")
    Change = apps.get_model("rollout", "ThresholdChangeRequest")
    for branch in FLAGS:
        Flag.objects.get_or_create(branch=branch)
    for branch, phase, metric, comparator, threshold, window in GATES:
        Gate.objects.get_or_create(
            branch=branch,
            metric=metric,
            defaults={
                "phase": phase,
                "comparator": comparator,
                "threshold": threshold,
                "window_days": window,
            },
        )
    with open(settings.THRESHOLDS_PATH, encoding="utf-8") as f:
        text = f.read()
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    Change.objects.get_or_create(
        version="CR-2026-000",
        defaults={
            "yaml_text": text,
            "sha256": sha,
            "base_sha256": sha,
            "evidence": "Baseline: the file on main when F9 was migrated.",
            "approvals": [
                {"user": "migration", "role": "manager", "at": None, "comment": "baseline"},
                {"user": "migration", "role": "manager", "at": None, "comment": "baseline"},
            ],
            "state": "approved",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("rollout", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
