"""A ticket's cue routes: shown only to staff with `infra:read` who reach the ticket, and a
resource a person links read as their own (F17 §o.9, BR-F17-20, BR-F17-25, UC-F17-13)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.test import TestCase

from apps.accounts.domain.access import Access
from apps.accounts.domain.catalog import Permission
from apps.accounts.models import User
from apps.infra import tasks
from apps.infra.domain.cues import TEMPLATES
from apps.infra.domain.vocabulary import CueRunOutcome, ResourceKind, ResourceSource
from apps.infra.models import CueRun, InfraQuery, InfraVia, TicketCue
from apps.infra.tests.test_cues import hand_off, linked, opened

pytestmark = pytest.mark.django_db


def test_cue_routes_refuse_the_reporter(lan, api_as):
    ticket = opened(lan, "db-01 chậm")

    read = api_as(lan).get(f"/api/tickets/{ticket.public_id}/cues")
    link = api_as(lan).post(
        f"/api/tickets/{ticket.public_id}/cues/resources",
        {"kind": "server", "resource_id": "x"},
        content_type="application/json",
    )

    assert (read.status_code, link.status_code) == (403, 403)


def test_cue_routes_refuse_staff_who_do_not_reach_the_ticket(
    lan, technician_user, api_as, monkeypatch
):
    ticket = opened(lan, "db-01 chậm")
    reaches = Access.covers_ticket
    monkeypatch.setattr(
        Access,
        "covers_ticket",
        lambda self, permission, t: (
            permission is not Permission.TICKETS_READ and reaches(self, permission, t)
        ),
    )

    read = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/cues")
    link = api_as(technician_user).post(
        f"/api/tickets/{ticket.public_id}/cues/resources",
        {"kind": "server", "resource_id": "x"},
        content_type="application/json",
    )

    assert (read.status_code, link.status_code) == (403, 403)
    assert not CueRun.objects.exists()


def test_the_ticket_page_reads_the_handoff_run(lan, technician_user, backends, queued, api_as):
    ticket = hand_off(opened(lan, "db-01 chậm"))

    reply = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/cues")

    assert reply.status_code == 200
    [run] = reply.json()["runs"]
    assert (run["outcome"], run["started_by"], run["overview"]) == ("done", None, [])
    assert [r["name"] for r in run["resources"]] == ["db-01", "vol-db-01"]
    cpu = next(c for c in run["resources"][0]["cues"] if c["template"] == "server.cpu")
    assert cpu["status"] == "ok" and cpu["link"]


def test_a_linked_resource_is_read_as_the_person(lan, technician_user, backends, queued, api_as):
    ticket = hand_off(opened(lan, "Hệ thống chạy chậm từ sáng"))
    vol = backends.id_of("volumes", "vol-db-01")

    with TestCase.captureOnCommitCallbacks(execute=True):
        reply = api_as(technician_user).post(
            f"/api/tickets/{ticket.public_id}/cues/resources",
            {"kind": "volume", "resource_id": vol},
            content_type="application/json",
        )

    assert reply.status_code == 202
    run = CueRun.objects.get(pk=reply.json()["id"])
    assert (run.outcome, run.started_by_id, run.transfer_id) == (
        CueRunOutcome.DONE,
        technician_user.id,
        None,
    )
    assert linked(run) == [("vol-db-01", ResourceSource.LINKED, None)]
    assert list(run.cues.order_by("seq").values_list("template", flat=True)) == list(
        TEMPLATES[ResourceKind.VOLUME]
    )
    reads = {c.query for c in run.cues.select_related("query")}
    assert {(q.via, q.actor_id, q.ticket_id) for q in reads if q} == {
        (InfraVia.HUMAN, technician_user.id, ticket.id)
    }
    assert None not in reads
    shown = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/cues").json()["runs"]
    assert [r["outcome"] for r in shown] == ["overview", "done"]
    assert shown[1]["started_by"] == technician_user.username


def test_linking_a_resource_the_cloud_lacks_is_404(lan, technician_user, backends, api_as):
    ticket = opened(lan, "db-01 chậm")

    reply = api_as(technician_user).post(
        f"/api/tickets/{ticket.public_id}/cues/resources",
        {"kind": "server", "resource_id": "no-such-server"},
        content_type="application/json",
    )

    assert reply.status_code == 404
    assert reply.json()["code"] == "infra_not_found"
    assert not CueRun.objects.exists()


@pytest.mark.parametrize("lost", ["infra_read", "the_ticket", "active"])
def test_a_person_who_lost_reach_before_the_run_reads_nothing(
    lan, technician_user, backends, queued, api_as, monkeypatch, lost
):
    ticket = opened(lan, "db-01 chậm")
    held: list[str] = []
    monkeypatch.setattr(tasks.linked_cues, "delay", held.append)
    with TestCase.captureOnCommitCallbacks(execute=True):
        api_as(technician_user).post(
            f"/api/tickets/{ticket.public_id}/cues/resources",
            {"kind": "server", "resource_id": backends.id_of("servers", "db-01")},
            content_type="application/json",
        )
    before = InfraQuery.objects.count()
    if lost == "infra_read":
        holds: Callable[[Access, Permission], bool] = Access.holds
        monkeypatch.setattr(
            Access, "holds", lambda self, p: p is not Permission.INFRA_READ and holds(self, p)
        )
    elif lost == "the_ticket":
        reaches = Access.covers_ticket
        monkeypatch.setattr(
            Access,
            "covers_ticket",
            lambda self, p, t: p is not Permission.TICKETS_READ and reaches(self, p, t),
        )
    else:
        User.objects.filter(pk=technician_user.pk).update(is_active=False)

    tasks.linked_cues.apply(args=(held[0],)).get()

    run = CueRun.objects.get(pk=held[0])
    assert run.outcome == CueRunOutcome.FAILED
    assert not TicketCue.objects.filter(run=run).exists()
    assert InfraQuery.objects.count() == before
