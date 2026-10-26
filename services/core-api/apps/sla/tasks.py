"""
Celery entry points for SLA clocks. The work lives in `utils/clocks.py`.
"""

from __future__ import annotations

from celery import shared_task

from apps.sla.utils.clocks import sla_clocks


@shared_task
def sweep() -> dict[str, int]:
    """Beat task: rebuilds failed clocks and fires warnings, breaches and escalations."""
    return sla_clocks.sweep()


@shared_task
def holiday_check() -> int:
    """Beat task: reports calendars with no holidays for next year."""
    return sla_clocks.holiday_check()
