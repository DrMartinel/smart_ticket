# pyright: standard
"""
Few-shot pool — spec §3.5. An example enters the pool only with the
reporter's confirmation, and leaves it when its TTL passes or its source
ticket is reopened. The TTL and the per-category cap come from
`thresholds.yaml`.

An example that should have left the pool keeps steering the model's answers
with nothing visibly wrong, so each exit is pinned here.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from contracts.enums import PIILevel

from apps.fewshot.models import FewshotExample
from apps.fewshot.selectors import active_examples_for_category
from apps.fewshot.services import FewshotError, add_example
from apps.fewshot.tasks import expire_fewshot_examples
from apps.tickets.models import Ticket
from apps.tickets.tasks import reopen_ticket


def ticket(reporter, public_id: str = "TKT-FS-001") -> Ticket:
    return Ticket.objects.create(
        public_id=public_id,
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
        status="resolved",
    )


def example(source: Ticket, approver, *, expires_in_days: int = 30) -> FewshotExample:
    now = timezone.now()
    return FewshotExample.objects.create(
        source_ticket=source,
        category="network",
        input_text="masked input",
        output_json={"proposed_category": "network"},
        approver=approver,
        approved_at=now,
        user_confirmed=True,
        expires_at=now + timedelta(days=expires_in_days),
    )


def with_fewshot_thresholds(settings, **values) -> None:
    fewshot = settings.THRESHOLDS.fewshot.model_copy(update=values)
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"fewshot": fewshot})


@pytest.mark.django_db
def test_an_unconfirmed_example_is_refused(employee_user, manager_user):
    with pytest.raises(FewshotError, match="user_confirmed"):
        add_example(
            ticket=ticket(employee_user),
            category="network",
            input_text="masked input",
            output_json={},
            approver=manager_user,
            user_confirmed=False,
        )

    assert not FewshotExample.objects.exists()


@pytest.mark.django_db
def test_a_new_example_expires_after_the_configured_ttl(employee_user, manager_user, settings):
    with_fewshot_thresholds(settings, ttl_days=7)

    added = add_example(
        ticket=ticket(employee_user),
        category="network",
        input_text="masked input",
        output_json={},
        approver=manager_user,
        user_confirmed=True,
    )

    assert added.expires_at - added.approved_at == timedelta(days=7)


@pytest.mark.django_db
def test_expired_examples_are_out_of_the_pool_before_the_expiry_task_runs(
    employee_user, manager_user
):
    source = ticket(employee_user)
    live = example(source, manager_user)
    example(source, manager_user, expires_in_days=-1)

    assert list(active_examples_for_category("network")) == [live]


@pytest.mark.django_db
def test_the_expiry_task_retracts_expired_examples(employee_user, manager_user):
    source = ticket(employee_user)
    live = example(source, manager_user)
    expired = example(source, manager_user, expires_in_days=-1)

    assert expire_fewshot_examples() == 1

    expired.refresh_from_db()
    live.refresh_from_db()
    assert expired.retract_reason == "ttl_expired"
    assert live.retracted_at is None


@pytest.mark.django_db
def test_reopening_a_ticket_retracts_only_its_examples(employee_user, manager_user):
    reopened, other = ticket(employee_user), ticket(employee_user, "TKT-FS-002")
    retracted = example(reopened, manager_user)
    kept = example(other, manager_user)

    reopen_ticket(reopened.id)

    retracted.refresh_from_db()
    assert retracted.retracted_at is not None
    assert list(active_examples_for_category("network")) == [kept]


@pytest.mark.django_db
def test_the_pool_is_capped_per_category_by_thresholds(employee_user, manager_user, settings):
    with_fewshot_thresholds(settings, max_per_category=2)
    source = ticket(employee_user)
    for _ in range(3):
        example(source, manager_user)

    assert len(active_examples_for_category("network")) == 2
