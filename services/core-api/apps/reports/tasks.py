"""Celery entry points for F10 reporting."""

from celery import shared_task

from apps.reports.utils.weekly import weekly_report
from apps.reports.utils.facts import report_facts


@shared_task(name="apps.reports.tasks.build_facts")
def build_facts() -> int:
    return report_facts.build()


@shared_task(name="apps.reports.tasks.weekly_email")
def weekly_email() -> bool:
    return weekly_report.send()
