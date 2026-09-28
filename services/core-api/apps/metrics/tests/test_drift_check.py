# pyright: standard
"""
Weekly drift check — spec §7.2. The "trust score collapsed" alert fires when
this week's scores cluster so tightly that the scorer can no longer tell
tickets apart. The spread it compares against is calibration data, so it
has to come from `thresholds.yaml` like the other alert thresholds; a
literal in code is invisible to anyone tuning the file and absent from the
recorded alert.
"""

import pytest

from apps.tickets.utils.patterns import PIILevel

from apps.metrics.tasks import weekly_drift_check
from apps.tickets.models import AiRun, Ticket

CLUSTERED = [0.80, 0.81, 0.80, 0.81]  # std ≈ 0.006
SPREAD = [0.30, 0.60, 0.90]  # std = 0.30


def record_runs(reporter, scores: list[float]) -> None:
    ticket = Ticket.objects.create(
        public_id="TKT-DRIFT-001",
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )
    for attempt, score in enumerate(scores, start=1):
        AiRun.objects.create(
            ticket=ticket,
            idempotency_key=f"{ticket.id}:{attempt}",
            prompt_version="test",
            model="test",
            graph_version="test",
            trust_signals={},
            trust_score=score,
        )


def set_std_min(settings, value: float) -> None:
    alerts = settings.THRESHOLDS.alerts.model_copy(update={"trust_score_std_min": value})
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"alerts": alerts})


def collapse_alerts(result) -> list[dict]:
    return [a for a in result["alerts"] if a["alert"] == "trust_score_collapsed"]


@pytest.mark.django_db
def test_clustered_scores_raise_the_collapse_alert_with_its_threshold(employee_user, settings):
    set_std_min(settings, 0.05)
    record_runs(employee_user, CLUSTERED)

    [alert] = collapse_alerts(weekly_drift_check())

    assert alert["std"] < 0.05
    assert alert["threshold"] == 0.05


@pytest.mark.django_db
def test_collapse_threshold_is_read_from_config(employee_user, settings):
    """Same clustered scores, a threshold below their spread: no alert. With
    the threshold hard-coded, this would still alert."""
    set_std_min(settings, 0.001)
    record_runs(employee_user, CLUSTERED)

    assert collapse_alerts(weekly_drift_check()) == []


@pytest.mark.django_db
def test_spread_scores_do_not_raise_the_collapse_alert(employee_user):
    record_runs(employee_user, SPREAD)

    assert collapse_alerts(weekly_drift_check()) == []
