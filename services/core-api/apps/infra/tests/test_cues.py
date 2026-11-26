"""A ticket's cues: queued at handoff, linked among the reporter's own projects from the masked
text, and collected as cue reads that change nothing about the ticket (F17 §o, BR-F17-13..19,
BR-F17-24, UC-F17-08, UC-F17-09, UC-F17-12)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from cloud_sim.faults import FaultKind
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.infra import tasks
from apps.infra.domain.cues import OVERVIEW, TEMPLATES, CueTemplate
from apps.infra.domain.untrusted import WITHHELD
from apps.infra.domain.vocabulary import CueRunOutcome, CueStatus, ResourceKind, ResourceSource
from apps.infra.models import CueRun, InfraQuery, InfraVia
from apps.infra.services.cues import cues
from apps.infra.tests.conftest import (
    FakeElasticsearch,
    FakePrometheus,
    log_doc,
    series,
)
from apps.infra.tests.test_customers import insufficient_context_answers
from apps.lifecycle.domain.vocabulary import PipelineStatus
from apps.lifecycle.models import Transfer
from apps.lifecycle.services.engine import lifecycle
from apps.notifications import tasks as notification_tasks
from apps.rollout.domain.vocabulary import FlagBranch
from apps.rollout.testing import flags_off
from apps.sla.tests.conftest import status
from apps.tickets.domain.masking import NERError
from apps.tickets.domain.patterns import PIILevel
from apps.tickets.models import Ticket
from apps.tickets.tasks import process_ticket
from config.celery import app

pytestmark = pytest.mark.django_db

_numbers = iter(range(1, 10_000))


def opened(reporter: User, subject: str, body: str = "", **fields: Any) -> Ticket:
    """A ticket at `new` whose masked text is `subject` and `body`."""
    ticket = Ticket.objects.create(
        public_id=f"TKT-CUES-{next(_numbers):06d}",
        reporter=reporter,
        subject_masked=subject,
        body_masked=body,
        pii_level=fields.pop("pii_level", PIILevel.ROUTINE.value),
        **fields,
    )
    lifecycle.start(ticket)
    return ticket


def opened_ago(reporter: User, subject: str, hours: int) -> Ticket:
    """A ticket at `new` opened `hours` ago."""
    ticket = opened(reporter, subject)
    ticket.created_at = timezone.now() - timedelta(hours=hours)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=ticket.created_at)
    return ticket


def hand_off(ticket: Ticket) -> Ticket:
    """Hands the ticket off to `pending_review` and runs what its commit queues."""
    with TestCase.captureOnCommitCallbacks(execute=True):
        lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)
    return ticket


def run_of(ticket: Ticket) -> CueRun:
    return CueRun.objects.get(ticket=ticket, transfer__isnull=False)


def window_of(run: CueRun) -> timedelta:
    assert run.window_start is not None and run.window_end is not None
    return run.window_end - run.window_start


def linked(run: CueRun) -> list[tuple[str, str, str | None]]:
    return list(run.resources.order_by("seq").values_list("name", "source", "token"))


# ── the database ──


def test_only_a_cue_read_may_have_no_actor(lan, technician_user):
    ticket = opened(lan, "db-01 chậm")
    row = dict(backend="cloud", kind="resource", compiled="GET", outcome="ok")

    for bad in (
        dict(via=InfraVia.HUMAN.value, actor=None, ticket=ticket),
        dict(via=InfraVia.CUE.value, actor=technician_user, ticket=ticket),
        dict(via=InfraVia.CUE.value, actor=None, ticket=None),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            InfraQuery.objects.create(**row, **bad)

    InfraQuery.objects.create(**row, via=InfraVia.CUE.value, actor=None, ticket=ticket)
    InfraQuery.objects.create(**row, via=InfraVia.HUMAN.value, actor=technician_user, ticket=ticket)


# ── queueing at handoff (BR-F17-13) ──


def test_cue_task_is_queued_once_per_handoff(lan, backends, queued, technician_user):
    ticket = hand_off(opened(lan, "db-01 chậm"))
    with TestCase.captureOnCommitCallbacks(execute=True):
        lifecycle.move(
            ticket.id,
            status("in_progress").id,
            actor=technician_user,
            force=False,
            expected_version=None,
        )
    tasks.ticket_cues.apply(args=queued[0]).get()

    assert len(queued) == 1
    assert CueRun.objects.filter(ticket=ticket).count() == 1


def test_a_ticket_sent_back_to_triage_gets_a_run_at_its_next_handoff(lan, backends, queued):
    ticket = hand_off(opened(lan, "db-01 chậm"))
    lifecycle.system_move(ticket, PipelineStatus.NEW)
    hand_off(ticket)

    assert len(queued) == 2
    assert CueRun.objects.filter(ticket=ticket).count() == 2


def test_flag_off_queues_no_cue_task(lan, backends, queued):
    flags_off(FlagBranch.TICKET_CUES)

    ticket = hand_off(opened(lan, "db-01 chậm"))

    assert queued == []
    assert not CueRun.objects.filter(ticket=ticket).exists()


def test_a_flag_turned_off_before_the_task_runs_collects_nothing(lan, backends, monkeypatch):
    held: list[tuple[str, str]] = []
    monkeypatch.setattr(tasks.ticket_cues, "delay", lambda *args: held.append(args))
    monkeypatch.setattr(notification_tasks.dispatch, "delay", lambda *a: None)
    ticket = hand_off(opened(lan, "db-01 chậm"))
    flags_off(FlagBranch.TICKET_CUES)

    tasks.ticket_cues.apply(args=held[0]).get()

    assert not CueRun.objects.filter(ticket=ticket).exists()
    assert not InfraQuery.objects.exists()


def test_cue_tasks_run_on_the_infra_queue_under_a_time_limit(settings):
    for task in (tasks.ticket_cues, tasks.linked_cues):
        assert app.amqp.router.route({}, task.name)["queue"].name == "infra"
        assert task.soft_time_limit == settings.INFRA_CUE_SOFT_TIME_LIMIT_SEC


def test_a_failure_queueing_cues_never_fails_the_move(lan, queued, monkeypatch):
    def broken(*args: Any) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1/0")
        return True

    monkeypatch.setattr(Transfer.objects, "is_handoff", broken)

    ticket = hand_off(opened(lan, "db-01 chậm"))

    ticket.refresh_from_db()
    assert ticket.status == PipelineStatus.PENDING_REVIEW.value
    assert queued == []


# ── what a run links (BR-F17-14, BR-F17-24) ──


def test_a_named_server_is_linked_with_its_attached_volume(lan, backends, queued):
    ticket = hand_off(opened(lan, "db-01 trả lời rất chậm từ khoảng 9h"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.DONE
    assert linked(run) == [
        ("db-01", ResourceSource.NAMED, "db-01"),
        ("vol-db-01", ResourceSource.ATTACHED, None),
    ]
    templates = list(run.cues.order_by("seq").values_list("template", flat=True))
    assert templates == [
        *TEMPLATES[ResourceKind.SERVER],
        *TEMPLATES[ResourceKind.VOLUME],
    ]
    assert set(run.cues.values_list("status", flat=True)) == {CueStatus.OK}


def test_the_cap_keeps_named_then_attached(lan, backends, queued):
    ticket = hand_off(opened(lan, "app-01 lỗi", "db-01 cũng chậm"))

    assert linked(run_of(ticket)) == [
        ("app-01", ResourceSource.NAMED, "app-01"),
        ("db-01", ResourceSource.NAMED, "db-01"),
        ("vol-app-01", ResourceSource.ATTACHED, None),
    ]


def test_a_name_from_another_companys_project_is_never_linked(lan, backends, queued):
    hbr = backends.id_of("projects", "hbr-web")

    ticket = hand_off(opened(lan, "giống lỗi của web-03 hôm qua"))

    run = run_of(ticket)
    assert not run.resources.filter(name="web-03").exists()
    assert InfraQuery.objects.exists()
    assert not [q.compiled for q in InfraQuery.objects.all() if hbr in q.projects]
    assert not [c for c in backends.calls if hbr in c]


def test_enrichment_reads_the_masked_text_only(lan, backends, queued):
    ticket = hand_off(opened(lan, "Không gửi được mail cho [EMAIL_1]"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.OVERVIEW
    assert not run.resources.exists()


def test_a_ticket_whose_masking_failed_names_nothing(lan, backends, queued):
    ticket = hand_off(opened(lan, "db-01 chậm", pii_level=PIILevel.MASK_FAILED.value))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.OVERVIEW
    assert not run.resources.exists()


def test_nothing_named_runs_the_overview(lan, backends, queued, es: FakeElasticsearch):
    ticket = hand_off(opened(lan, "Hệ thống chạy chậm từ sáng"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.OVERVIEW
    assert not run.resources.exists()
    cues_ = list(run.cues.order_by("seq"))
    assert [c.template for c in cues_] == list(OVERVIEW)
    assert all(c.resource_id is None for c in cues_)
    by = {c.template: c for c in cues_}
    assert "CloudVolumeIopsAtQuota firing on vol-db-01" in by[CueTemplate.OVERVIEW_ALERTS].summary
    errors = by[CueTemplate.OVERVIEW_ERROR_LOGS]
    assert errors.summary == "Most error lines: db-01 37"
    assert errors.evidence["servers"][0]["resource_id"] == backends.id_of("servers", "db-01")
    [counted] = [
        term for b in es.bodies() for agg in b.get("aggs", {}).values() for term in agg.values()
    ]
    assert counted["field"] == "host.id"


def test_three_servers_or_fewer_are_all_linked(lan, backends, queued, settings):
    cues_caps = settings.THRESHOLDS.cues.model_copy(update={"max_resources": 4})
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"cues": cues_caps})

    ticket = hand_off(opened(lan, "Hệ thống chạy chậm từ sáng"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.DONE
    assert linked(run) == [
        ("app-01", ResourceSource.EVERY_SERVER, None),
        ("app-02", ResourceSource.EVERY_SERVER, None),
        ("db-01", ResourceSource.EVERY_SERVER, None),
        ("stg-app-01", ResourceSource.EVERY_SERVER, None),
    ]


# ── how a run reads (BR-F17-15, BR-F17-16, BR-F17-19) ──


def test_every_cue_read_has_no_actor_and_names_its_ticket(lan, backends, queued):
    ticket = hand_off(opened(lan, "db-01 trả lời rất chậm"))

    rows = list(InfraQuery.objects.all())
    assert {(q.via, q.actor_id, q.ticket_id) for q in rows} == {(InfraVia.CUE, None, ticket.id)}
    assert {q.backend for q in rows} == {"cloud", "prometheus", "elasticsearch", "alertmanager"}


def test_every_cue_query_carries_only_the_reporters_projects(
    lan, backends, queued, prom: FakePrometheus, es: FakeElasticsearch
):
    own = {backends.id_of("projects", "saomai-prod"), backends.id_of("projects", "saomai-staging")}

    hand_off(opened(lan, "Hệ thống chạy chậm từ sáng"))

    assert prom.projects and all(set(p) <= own and p for p in prom.projects)
    scoped = [
        f["terms"]["labels.openstack_project_id"]
        for body in es.bodies()
        for f in body["query"]["bool"]["filter"]
        if "labels.openstack_project_id" in f.get("terms", {})
    ]
    assert len(scoped) == len(es.searches)
    assert all(set(p) <= own for p in scoped)


def test_keystone_down_links_nothing_and_never_widens(lan, backends, queued):
    backends.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    ticket = hand_off(opened(lan, "db-01 chậm"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.SCOPE_UNAVAILABLE
    assert not run.resources.exists() and not run.cues.exists()
    assert list(InfraQuery.objects.values_list("outcome", "via", "ticket_id")) == [
        ("scope_unavailable", InfraVia.CUE, ticket.id)
    ]


def test_a_reporter_with_no_keystone_user_gets_no_cloud_user(employee_user, backends, queued):
    ticket = hand_off(opened(employee_user, "db-01 chậm"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.NO_CLOUD_USER
    assert not run.resources.exists()


def test_a_down_backend_fails_one_cue_not_the_run(lan, backends, queued, es: FakeElasticsearch):
    es.raises = httpx.ConnectError("Elasticsearch is down")

    ticket = hand_off(opened(lan, "db-01 chậm"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.DONE
    server = {c.template: c for c in run.cues.filter(resource__name="db-01")}
    logs = server[CueTemplate.SERVER_ERROR_LOGS]
    assert (logs.status, logs.summary) == (
        CueStatus.UNAVAILABLE,
        "Elasticsearch was unreachable; no log cue",
    )
    others = (CueTemplate.SERVER_CPU, CueTemplate.SERVER_MEMORY, CueTemplate.SERVER_ALERTS)
    assert [server[t].status for t in others] == [CueStatus.OK] * 3


def test_a_refused_cue_names_its_check(lan, backends, queued, settings):
    infra = settings.THRESHOLDS.infra.model_copy(update={"min_step_seconds": 120})
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"infra": infra})

    ticket = hand_off(opened(lan, "db-01 chậm"))

    cpu = run_of(ticket).cues.get(template=CueTemplate.SERVER_CPU)
    assert cpu.status == CueStatus.REFUSED
    assert cpu.evidence == {"check": "step"}
    assert cpu.summary.startswith("Prometheus CPU query refused (step)")


def test_a_long_window_reads_one_resource_at_most_max_points_a_series(
    lan, backends, queued, prom: FakePrometheus, settings
):
    ticket = hand_off(opened_ago(lan, "db-01 chậm", hours=20))

    run = run_of(ticket)
    seconds = window_of(run).total_seconds()
    assert prom.steps
    assert all(seconds // step + 1 <= settings.THRESHOLDS.cues.max_points for step in prom.steps)


def test_the_overview_reads_one_cpu_value_a_server_and_iops_at_overview_points(
    lan, backends, queued, prom: FakePrometheus, settings
):
    ticket = hand_off(opened_ago(lan, "Hệ thống chạy chậm từ sáng", hours=20))

    run = run_of(ticket)
    seconds = int(window_of(run).total_seconds())
    reads = list(zip(prom.queries, prom.steps, strict=True))
    [(cpu, step)] = [(q, s) for q, s in reads if "cpu" in q]
    assert cpu.startswith("max_over_time(") and cpu.endswith(f"[{seconds}s])")
    assert step == seconds
    iops = [s for q, s in reads if "iops" in q]
    assert iops
    assert all(seconds // s + 1 <= settings.THRESHOLDS.cues.overview_points for s in iops)


def test_a_window_never_starts_past_the_range_cap(lan, backends, queued, settings):
    hours = settings.THRESHOLDS.infra.max_range_hours

    ticket = hand_off(opened_ago(lan, "db-01 chậm", hours=hours + 24))

    run = run_of(ticket)
    assert window_of(run) == timedelta(hours=hours)
    assert not run.cues.filter(status=CueStatus.REFUSED).exists()


@pytest.mark.parametrize(
    ("long_first", "ending"),
    [
        (
            False,
            ", from part of the answer: the Prometheus CPU answer was over the result cap; "
            "open the query for all of it",
        ),
        (
            True,
            "No summary: the Prometheus CPU answer was over the result cap; open the query for it",
        ),
    ],
)
def test_an_answer_cut_to_the_result_cap_is_never_shown_complete(
    lan, backends, queued, prom: FakePrometheus, long_first, ending
):
    prod, db01 = backends.id_of("projects", "saomai-prod"), backends.id_of("servers", "db-01")
    long = series(prod, 0.9, server_id=db01)
    long["values"] = [[1764147600 + 60 * i, "0.9"] for i in range(2_000)]
    prom.series = [long, *prom.series] if long_first else [*prom.series, long]

    ticket = hand_off(opened(lan, "db-01 chậm"))

    cpu = run_of(ticket).cues.get(template=CueTemplate.SERVER_CPU)
    assert cpu.status == CueStatus.CUT
    assert cpu.summary.endswith(ending)
    assert cpu.evidence["cut"] is True
    assert cpu.link


def test_a_run_that_raises_is_failed_never_left_running(lan, backends, queued, monkeypatch):
    def broken(*args: Any) -> None:
        raise RuntimeError("a bug in a template")

    monkeypatch.setattr(cues.__class__, "open_window", broken)

    ticket = hand_off(opened(lan, "db-01 chậm"))

    run = run_of(ticket)
    assert run.outcome == CueRunOutcome.FAILED
    assert run.finished_at is not None


def test_cues_never_change_the_decision_priority_assignee_or_clocks(
    lan, backends, queued, monkeypatch
):
    insufficient_context_answers(monkeypatch)

    def processed() -> Ticket:
        ticket = opened(lan, "db-01 trả lời rất chậm")
        with TestCase.captureOnCommitCallbacks(execute=True):
            process_ticket.apply(args=(ticket.id,)).get()
        ticket.refresh_from_db()
        return ticket

    with_cues = processed()
    flags_off(FlagBranch.TICKET_CUES)
    without = processed()

    def outcome(t: Ticket) -> tuple[Any, ...]:
        return (
            t.routing_decisions.values("branch", "reason_code", "gate_failed").get(),
            (t.status, t.priority, t.assigned_to_id, t.team_id),
            list(t.sla_clocks.order_by("kind").values_list("kind", "state", "policy_id")),
        )

    assert run_of(with_cues).outcome == CueRunOutcome.DONE
    assert not CueRun.objects.filter(ticket=without).exists()
    assert outcome(with_cues) == outcome(without)


# ── what a cue stores (BR-F17-19) ──


def test_a_log_cue_stores_the_masked_line(lan, backends, queued, ner, es: FakeElasticsearch):
    prod = backends.id_of("projects", "saomai-prod")
    es.docs = [log_doc(prod, "login failed for lan.nt@saomai.vn")]

    ticket = hand_off(opened(lan, "db-01 chậm"))

    logs = run_of(ticket).cues.get(template=CueTemplate.SERVER_ERROR_LOGS)
    assert [line["message"] for line in logs.evidence["lines"]] == ["login failed for [EMAIL_1]"]


def test_ner_down_withholds_a_log_cues_lines(lan, backends, queued, ner):
    def down(text: str) -> Any:
        raise NERError("down")

    ner(down)

    ticket = hand_off(opened(lan, "db-01 chậm"))

    logs = run_of(ticket).cues.get(template=CueTemplate.SERVER_ERROR_LOGS)
    assert [line["message"] for line in logs.evidence["lines"]] == [WITHHELD]
