"""The receipt of each query an agent turn ran, the warning its reply carries for a source that
did not answer, and the link on every answer (F17 BR-F17-07, BR-F17-10, FR-F17-012, AC-F17-04)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from cloud_sim.faults import FaultKind
from django.test import Client

from apps.accounts.models import User
from apps.agent.models import AgentConversation, AgentSurface, AgentTurn, AgentTurnState
from apps.agent.testing import as_agent
from apps.infra.models import InfraQuery
from apps.infra.tests.conftest import (
    LAN_SUBJECT,
    CloudSim,
    FakeElasticsearch,
    FakePrometheus,
    log_doc,
    series,
    span_doc,
)

pytestmark = pytest.mark.django_db

START, END = "2026-11-26T08:00:00Z", "2026-11-26T10:00:00Z"
STAFF = "/api/infra"
MINE = "/api/requester/infra"
LATENCY = {
    "metric": "cloud_volume_read_latency_seconds",
    "start": START,
    "end": END,
    "step_seconds": 60,
}
LOGS = {"start": START, "end": END}
ES_DOWN = "Elasticsearch was unreachable; this answer has no logs or traces."
PROMETHEUS_DOWN = "Prometheus was unreachable; this answer has no metrics."
PROJECTS_UNLISTED = "The cloud's API was unreachable, so no projects could be listed; "
QUERIES_TO_READ_A_CONVERSATION = 6


def post(client: Client, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, data=body, content_type="application/json")


def console_turn(user: User) -> uuid.UUID:
    """A running turn in a new console conversation of `user`."""
    conversation = AgentConversation.objects.create(user=user, surface=AgentSurface.CONSOLE.value)
    return AgentTurn.objects.create(
        conversation=conversation,
        seq=1,
        message_masked="Why is db-01 slow?",
        pii_level="routine",
        session_family=uuid.uuid4(),
        state=AgentTurnState.RUNNING.value,
    ).id


def turn_view(api_as: Any, user: User, turn: uuid.UUID) -> dict[str, Any]:
    reply = api_as(user).get(f"/api/agent/turns/{turn}")
    assert reply.status_code == 200
    return reply.json()


# ── warnings (BR-F17-07) ──


def test_a_reply_after_an_unreachable_elasticsearch_says_so_in_code_s_words(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch, prom: FakePrometheus
):
    turn = console_turn(technician_user)
    es.raises = httpx.ConnectError("refused")

    logs = post(as_agent(technician_user, "search_logs", turn), f"{STAFF}/logs/search", LOGS)
    metrics = post(
        as_agent(technician_user, "query_metrics", turn), f"{STAFF}/metrics/query", LATENCY
    )

    assert (logs.status_code, metrics.status_code) == (424, 200)
    view = turn_view(api_as, technician_user, turn)
    assert view["warnings"] == [ES_DOWN]
    assert [(q["backend"], q["outcome"]) for q in view["queries"]] == [
        ("elasticsearch", "backend_unavailable"),
        ("prometheus", "ok"),
    ]


def test_each_unreachable_source_is_named_once_in_the_order_it_failed(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch, prom: FakePrometheus
):
    turn = console_turn(technician_user)
    es.raises = httpx.ConnectError("refused")
    prom.raises = httpx.ReadTimeout("slow")

    post(as_agent(technician_user, "search_logs", turn), f"{STAFF}/logs/search", LOGS)
    post(as_agent(technician_user, "query_metrics", turn), f"{STAFF}/metrics/query", LATENCY)
    post(as_agent(technician_user, "search_traces", turn), f"{STAFF}/traces/search", LOGS)

    assert turn_view(api_as, technician_user, turn)["warnings"] == [ES_DOWN, PROMETHEUS_DOWN]


def test_a_customer_whose_projects_could_not_be_read_is_told_so(
    api_as, employee_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    turn = uuid.uuid4()
    cloud_sim.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    reply = post(
        as_agent(employee_user, "query_my_metrics", turn),
        f"{MINE}/metrics/query",
        LATENCY,
    )

    assert reply.status_code == 424
    (warning,) = turn_view(api_as, employee_user, turn)["warnings"]
    assert warning.startswith("Keystone did not answer")


@pytest.mark.parametrize(
    ("tool", "path", "body", "backend", "missing"),
    [
        ("query_metrics", "/metrics/query", LATENCY, "prometheus", "this answer has no metrics."),
        (
            "search_logs",
            "/logs/search",
            LOGS,
            "elasticsearch",
            "this answer has no logs or traces.",
        ),
        (
            "search_traces",
            "/traces/search",
            LOGS,
            "elasticsearch",
            "this answer has no logs or traces.",
        ),
    ],
)
def test_a_staff_query_whose_project_list_failed_blames_the_cloud_for_its_own_missing_data(
    api_as,
    technician_user,
    cloud_sim: CloudSim,
    prom: FakePrometheus,
    es: FakeElasticsearch,
    tool,
    path,
    body,
    backend,
    missing,
):
    turn = console_turn(technician_user)
    cloud_sim.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    reply = post(as_agent(technician_user, tool, turn), f"{STAFF}{path}", body)

    assert reply.status_code == 424
    view = turn_view(api_as, technician_user, turn)
    assert view["warnings"] == [PROJECTS_UNLISTED + missing]
    (receipt,) = view["queries"]
    assert (receipt["backend"], receipt["failed_backend"]) == (backend, "cloud")


def test_the_warning_is_in_the_language_of_the_message(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    turn = console_turn(technician_user)
    es.raises = httpx.ConnectError("refused")
    post(as_agent(technician_user, "search_logs", turn), f"{STAFF}/logs/search", LOGS)
    AgentTurn.objects.filter(id=turn).update(message_masked="Vì sao db-01 chậm từ 9h sáng?")

    (warning,) = turn_view(api_as, technician_user, turn)["warnings"]
    assert warning.startswith("Không kết nối được Elasticsearch")


def test_a_turn_whose_sources_all_answered_has_no_warning(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    turn = console_turn(technician_user)
    post(as_agent(technician_user, "search_logs", turn), f"{STAFF}/logs/search", LOGS)

    view = turn_view(api_as, technician_user, turn)
    assert view["warnings"] == []
    assert [q["outcome"] for q in view["queries"]] == ["ok"]


# ── receipts (BR-F17-10) ──


def test_a_turn_shows_only_the_queries_it_ran(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    mine, other = console_turn(technician_user), console_turn(technician_user)
    post(as_agent(technician_user, "search_logs", mine), f"{STAFF}/logs/search", LOGS)
    post(as_agent(technician_user, "search_logs", other), f"{STAFF}/logs/search", LOGS)
    post(api_as(technician_user), f"{STAFF}/logs/search", LOGS)

    (receipt,) = turn_view(api_as, technician_user, mine)["queries"]
    assert receipt["id"] == str(InfraQuery.objects.get(agent_turn_id=mine).id)


def test_a_receipt_names_the_check_that_refused_its_query(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    turn = console_turn(technician_user)

    reply = post(
        as_agent(technician_user, "query_metrics", turn),
        f"{STAFF}/metrics/query",
        {**LATENCY, "step_seconds": 5},
    )

    assert reply.status_code == 422
    (receipt,) = turn_view(api_as, technician_user, turn)["queries"]
    assert (receipt["outcome"], receipt["refusal"], receipt["refusal_reason"]) == (
        "refused",
        "infra_query_refused",
        "step",
    )


def test_a_receipt_says_its_answer_was_cut_to_the_result_cap(
    api_as, technician_user, settings, cloud_sim: CloudSim, es: FakeElasticsearch
):
    infra = settings.THRESHOLDS.infra.model_copy(update={"max_result_bytes": 700})
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"infra": infra})
    es.docs = [log_doc("p", f"line {i} " + "x" * 100) for i in range(10)]
    turn = console_turn(technician_user)

    post(as_agent(technician_user, "search_logs", turn), f"{STAFF}/logs/search", LOGS)

    (receipt,) = turn_view(api_as, technician_user, turn)["queries"]
    assert receipt["truncated"] is True
    assert receipt["sent"]["link"].startswith(settings.KIBANA_URL)


def test_an_answer_that_was_not_cut_is_not_recorded_as_cut(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    es.docs = [log_doc("p", "slow query")]

    post(api_as(technician_user), f"{STAFF}/logs/search", LOGS)

    assert InfraQuery.objects.get().truncated is False


# ── links on answers ──


def test_every_answer_carries_the_link_its_row_records(
    api_as,
    technician_user,
    settings,
    cloud_sim: CloudSim,
    prom: FakePrometheus,
    es: FakeElasticsearch,
):
    prom.series = [series("p")]
    client = api_as(technician_user)

    answers = [
        post(client, f"{STAFF}/metrics/query", LATENCY),
        post(client, f"{STAFF}/logs/search", LOGS),
        post(client, f"{STAFF}/traces/search", LOGS),
    ]

    rows = {str(q.id): q.link for q in InfraQuery.objects.all()}
    for answer in answers:
        body = answer.json()
        assert answer.status_code == 200
        assert body["link"] and body["link"] == rows[body["query_id"]]


# ── what a customer never sees ──


def test_the_customer_routes_answer_without_a_link(
    api_as,
    employee_user,
    cloud_sim: CloudSim,
    prom: FakePrometheus,
    es: FakeElasticsearch,
):
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    prom.series = [series("p")]
    es.docs = [span_doc("p")]
    client = api_as(employee_user)

    answers = [
        post(client, f"{MINE}/metrics/query", LATENCY),
        post(client, f"{MINE}/logs/search", LOGS),
        post(client, f"{MINE}/traces/search", LOGS),
        client.get(f"{MINE}/traces/t1"),
    ]

    assert [a.status_code for a in answers] == [200, 200, 200, 200]
    assert all("link" not in a.json() for a in answers)
    assert all(q.link for q in InfraQuery.objects.exclude(compiled=""))


def test_a_customer_s_turn_shows_no_query_text_or_link(
    api_as, employee_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    turn = uuid.uuid4()

    post(as_agent(employee_user, "query_my_metrics", turn), f"{MINE}/metrics/query", LATENCY)

    (receipt,) = turn_view(api_as, employee_user, turn)["queries"]
    assert receipt["outcome"] == "ok"
    assert receipt["sent"] is None
    assert not {"compiled", "link"} & receipt.keys()


def test_a_staff_turn_shows_what_each_query_sent_and_its_link(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    turn = console_turn(technician_user)

    post(as_agent(technician_user, "query_metrics", turn), f"{STAFF}/metrics/query", LATENCY)

    (receipt,) = turn_view(api_as, technician_user, turn)["queries"]
    row = InfraQuery.objects.get()
    assert receipt["sent"] == {"compiled": row.compiled, "link": row.link}
    assert row.compiled and row.link


# ── reading a conversation ──


@pytest.mark.parametrize("turns", [1, 4])
def test_a_conversation_s_receipts_are_read_in_one_query_however_many_turns_it_has(
    api_as, technician_user, django_assert_num_queries, turns
):
    conversation = AgentConversation.objects.create(
        user=technician_user, surface=AgentSurface.CONSOLE.value
    )
    for seq in range(1, turns + 1):
        turn = AgentTurn.objects.create(
            conversation=conversation,
            seq=seq,
            message_masked="Why is db-01 slow?",
            pii_level="routine",
            session_family=uuid.uuid4(),
            state=AgentTurnState.REPLIED.value,
        )
        for backend in ("prometheus", "elasticsearch"):
            InfraQuery.objects.create(
                actor=technician_user,
                via="agent",
                agent_turn=turn,
                backend=backend,
                kind="structured",
                compiled="q",
                outcome="ok",
            )
    client = api_as(technician_user)

    with django_assert_num_queries(QUERIES_TO_READ_A_CONVERSATION):
        reply = client.get(f"/api/agent/conversations/{conversation.id}")

    assert reply.status_code == 200
    assert [len(t["queries"]) for t in reply.json()["turns"]] == [2] * turns
