"""The structured metric, log and trace queries and the catalog: scope in every compiled query,
the catalog and the caps, refusals, masking and the row each query writes (F17 §h.1,
BR-F17-05..07, BR-F17-10, BR-F17-12, AC-F17-01, AC-F17-02, AC-F17-05)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from cloud_sim.faults import FaultKind

from apps.accounts.models import User
from apps.agent.models import AgentTurn
from apps.agent.testing import as_agent
from apps.infra.domain.catalog import PROJECT_FIELD, Catalog, Surface
from apps.infra.domain.queries import COUNTS, LogCount, Window
from apps.infra.domain.untrusted import WITHHELD
from apps.infra.domain.vocabulary import QueryRefused
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
from apps.tickets.domain.masking import NERError

pytestmark = pytest.mark.django_db

START, END = "2026-11-26T08:00:00Z", "2026-11-26T10:00:00Z"
MINE = "/api/requester/infra"
STAFF = "/api/infra"


@pytest.fixture
def customer(employee_user: User) -> User:
    """lan.nt: a member of saomai-prod and saomai-staging in the cloud's Keystone."""
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    return employee_user


def latency(**extra: Any) -> dict[str, Any]:
    """A structured metric query for volume read latency."""
    return {
        "metric": "cloud_volume_read_latency_seconds",
        "start": START,
        "end": END,
        "step_seconds": 60,
        **extra,
    }


def logs(**extra: Any) -> dict[str, Any]:
    return {"start": START, "end": END, **extra}


def scope_filter(body: dict[str, Any]) -> list[str]:
    """The project values a compiled search filters on."""
    (found,) = [
        f["terms"][PROJECT_FIELD]
        for f in body["query"]["bool"]["filter"]
        if "terms" in f and PROJECT_FIELD in f["terms"]
    ]
    return list(found)


def with_caps(settings: Any, **caps: int) -> None:
    infra = settings.THRESHOLDS.infra.model_copy(update=caps)
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"infra": infra})


def refusal(reply: Any) -> tuple[int, str, str | None]:
    body = reply.json()
    return reply.status_code, body["code"], (body.get("details") or {}).get("reason")


# ── scope ──


def test_every_log_search_filters_the_callers_projects(
    api_as, customer, cloud_sim: CloudSim, es: FakeElasticsearch
):
    api_as(customer).post(f"{MINE}/logs/search", data=logs(), content_type="application/json")
    prod = cloud_sim.id_of("projects", "saomai-prod")
    api_as(customer).post(
        f"{MINE}/logs/search", data=logs(project_id=prod), content_type="application/json"
    )

    first, second = es.bodies()
    assert scope_filter(first) == sorted([prod, cloud_sim.id_of("projects", "saomai-staging")])
    assert scope_filter(second) == [prod]


def test_a_log_count_filters_the_callers_projects_and_stays_under_the_cap(settings):
    caps = settings.THRESHOLDS.infra
    count = LogCount(
        window=Window(
            datetime(2026, 11, 26, 8, tzinfo=UTC), datetime(2026, 11, 26, 10, tzinfo=UTC)
        ),
        dataset="instance",
        by="server",
        size=3,
        filters={"level": ["ERROR"]},
    )

    search = count.search(Catalog(Surface.CUSTOMER), caps, frozenset({"p2", "p1"}))

    assert scope_filter(search.body) == ["p1", "p2"]
    assert search.body["aggs"] == {COUNTS: {"terms": {"field": "host.name", "size": 3}}}
    with pytest.raises(ValueError):
        count.search(Catalog(Surface.CUSTOMER), caps, frozenset())
    with pytest.raises(QueryRefused):
        replace(count, size=caps.max_log_docs + 1).search(
            Catalog(Surface.CUSTOMER), caps, frozenset({"p1"})
        )


def test_every_trace_search_filters_the_callers_projects(
    api_as, customer, cloud_sim: CloudSim, es: FakeElasticsearch
):
    api_as(customer).post(f"{MINE}/traces/search", data=logs(), content_type="application/json")
    api_as(customer).get(f"{MINE}/traces/t1")

    search, lookup = es.bodies()
    mine = sorted(
        [cloud_sim.id_of("projects", "saomai-prod"), cloud_sim.id_of("projects", "saomai-staging")]
    )
    assert scope_filter(search) == scope_filter(lookup) == mine


def test_every_metric_selector_carries_the_scope_matcher_and_the_proxy_its_projects(
    api_as, customer, cloud_sim: CloudSim, prom: FakePrometheus
):
    prod = cloud_sim.id_of("projects", "saomai-prod")

    reply = api_as(customer).post(
        f"{MINE}/metrics/query", data=latency(project_id=prod), content_type="application/json"
    )

    assert reply.status_code == 200
    assert prom.queries == [f'cloud_volume_read_latency_seconds{{project="{prod}"}}']
    assert prom.projects == [[prod]]


def test_staff_queries_send_the_proxy_every_keystone_project(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    api_as(technician_user).post(
        f"{STAFF}/metrics/query", data=latency(), content_type="application/json"
    )

    every = sorted(cloud_sim.cloud.projects)
    assert prom.projects == [every]
    assert f'project=~"{"|".join(every)}"' in prom.queries[0]


def test_another_companys_project_reaches_no_backend(
    api_as, customer, cloud_sim: CloudSim, prom: FakePrometheus, es: FakeElasticsearch
):
    other = cloud_sim.id_of("projects", "hbr-web")
    client = api_as(customer)

    metrics = client.post(
        f"{MINE}/metrics/query", data=latency(project_id=other), content_type="application/json"
    )
    found = client.post(
        f"{MINE}/logs/search", data=logs(project_id=other), content_type="application/json"
    )

    assert metrics.status_code == found.status_code == 200
    assert metrics.json()["series"] == [] and found.json()["lines"] == []
    assert prom.queries == [] and es.searches == []


def test_a_trace_outside_the_scope_is_not_found_like_a_missing_one(
    api_as, customer, cloud_sim: CloudSim, es: FakeElasticsearch
):
    reply = api_as(customer).get(f"{MINE}/traces/a-trace-of-hbr-web")

    assert refusal(reply)[:2] == (404, "infra_not_found")
    assert InfraQuery.objects.get().outcome == "refused"


def test_a_failed_membership_lookup_refuses_a_query_without_reaching_a_backend(
    api_as, customer, cloud_sim: CloudSim, prom: FakePrometheus
):
    cloud_sim.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    reply = api_as(customer).post(
        f"{MINE}/metrics/query", data=latency(), content_type="application/json"
    )

    assert refusal(reply)[:2] == (424, "infra_scope_unavailable")
    assert prom.queries == []


# ── the catalog and the caps ──


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        (latency(metric="node_cpu_seconds_total"), "dataset"),
        (latency(filters={"instance": ["db-01"]}), "field"),
        (latency(filters={"volume": []}), "field"),
        (latency(function="rate", function_seconds=300), "function"),
        (latency(metric="cloud_volume_iops_total"), "function"),
        (latency(aggregate="quantile"), "function"),
        (latency(by=["volume"]), "function"),
        (latency(aggregate="avg", by=["project"]), "field"),
        (latency(start=END, end=START), "range"),
        (latency(start="2026-11-01T00:00:00Z"), "range"),
        (latency(step_seconds=5), "step"),
        (latency(metric="cloud_volume_iops_total", function="rate", function_seconds=5), "step"),
    ],
)
def test_a_metric_query_outside_the_catalog_or_the_caps_is_refused(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, query, reason
):
    reply = api_as(technician_user).post(
        f"{STAFF}/metrics/query", data=query, content_type="application/json"
    )

    assert refusal(reply) == (422, "infra_query_refused", reason)
    assert prom.queries == []
    assert InfraQuery.objects.get().outcome == "refused"


@pytest.mark.parametrize(
    ("path", "query", "reason"),
    [
        ("/logs/search", logs(dataset="audit"), "dataset"),
        ("/logs/search", logs(filters={"user": ["lan"]}), "field"),
        ("/logs/search", logs(size=101), "size"),
        ("/logs/search", logs(start="2026-11-01T00:00:00Z"), "range"),
        ("/traces/search", logs(filters={"db.statement": ["x"]}), "field"),
        ("/traces/search", logs(size=501), "size"),
    ],
)
def test_a_search_outside_the_catalog_or_the_caps_is_refused(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch, path, query, reason
):
    reply = api_as(technician_user).post(
        f"{STAFF}{path}", data=query, content_type="application/json"
    )

    assert refusal(reply) == (422, "infra_query_refused", reason)
    assert es.searches == []


def test_more_series_than_the_cap_are_refused(
    api_as, technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus
):
    with_caps(settings, max_series=2)
    prom.series = [series("p", volume_id=f"v{i}") for i in range(3)]

    reply = api_as(technician_user).post(
        f"{STAFF}/metrics/query", data=latency(), content_type="application/json"
    )

    assert refusal(reply) == (422, "infra_query_refused", "series")


def test_customers_cannot_name_the_hypervisor_or_a_staff_only_dataset(
    api_as,
    customer,
    technician_user,
    cloud_sim: CloudSim,
    prom: FakePrometheus,
    es: FakeElasticsearch,
):
    host = latency(metric="cloud_server_up", filters={"host": ["hv-01"]})
    errors = logs(dataset="apm_errors")

    mine = api_as(customer)
    staff = api_as(technician_user)

    assert (
        refusal(mine.post(f"{MINE}/metrics/query", data=host, content_type="application/json"))[2]
        == "field"
    )
    assert (
        refusal(mine.post(f"{MINE}/logs/search", data=errors, content_type="application/json"))[2]
        == "dataset"
    )
    assert (
        staff.post(f"{STAFF}/metrics/query", data=host, content_type="application/json").status_code
        == 200
    )
    assert (
        staff.post(f"{STAFF}/logs/search", data=errors, content_type="application/json").status_code
        == 200
    )


def test_a_customer_answer_never_shows_the_hypervisor_label(
    api_as, customer, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.series = [series("p", server="db-01", host="hv-01")]

    reply = api_as(customer).post(
        f"{MINE}/metrics/query",
        data=latency(metric="cloud_server_up"),
        content_type="application/json",
    )

    assert reply.json()["series"][0]["labels"] == {"project": "p", "server": "db-01"}


def test_a_label_value_cannot_break_out_of_its_matcher(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    evil = 'x"} or vector(1) #'

    api_as(technician_user).post(
        f"{STAFF}/metrics/query",
        data=latency(filters={"volume": [evil, "vol.db+01"]}),
        content_type="application/json",
    )

    assert prom.queries[0].endswith(
        ',volume=~"vol\\\\.db\\\\+01|x\\"\\\\} or vector\\\\(1\\\\) #"}'
    )


def test_a_compiled_metric_query_applies_the_function_and_aggregate(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    query = latency(
        metric="cloud_volume_iops_total",
        filters={"volume": ["vol-db-01"]},
        function="rate",
        function_seconds=300,
        aggregate="sum",
        by=["volume"],
    )

    api_as(technician_user).post(
        f"{STAFF}/metrics/query", data=query, content_type="application/json"
    )

    assert prom.queries[0].startswith("sum by (volume) (rate(cloud_volume_iops_total{project=~")
    assert prom.queries[0].endswith(',volume="vol-db-01"}[300s]))')


# ── backends ──


def test_an_unreachable_elasticsearch_is_424_naming_it_and_recorded(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    es.raises = httpx.ConnectError("refused")

    reply = api_as(technician_user).post(
        f"{STAFF}/logs/search", data=logs(), content_type="application/json"
    )

    assert reply.status_code == 424
    assert reply.json()["code"] == "infra_backend_unavailable"
    assert reply.json()["details"] == {"backend": "elasticsearch"}
    row = InfraQuery.objects.get()
    assert (row.backend, row.outcome) == ("elasticsearch", "backend_unavailable")


def test_an_unreachable_prometheus_is_424_naming_it_and_recorded(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.raises = httpx.ReadTimeout("slow")

    reply = api_as(technician_user).post(
        f"{STAFF}/metrics/query", data=latency(), content_type="application/json"
    )

    assert reply.status_code == 424
    assert reply.json()["details"] == {"backend": "prometheus"}
    assert InfraQuery.objects.get().outcome == "backend_unavailable"


def test_a_query_prometheus_rejects_is_422_backend_refused(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.status, prom.error = 400, "exceeded maximum resolution of 11,000 points"

    reply = api_as(technician_user).post(
        f"{STAFF}/metrics/query", data=latency(), content_type="application/json"
    )

    assert refusal(reply) == (422, "infra_query_refused", "backend_refused")
    assert "11,000 points" in reply.json()["message"]


# ── masking and the cap on bytes ──


def test_ner_failure_withholds_log_messages_but_keeps_counts(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch, ner
):
    es.docs = [log_doc("p", "slow query on orders"), log_doc("p", "slow query on items")]

    def fail(text: str) -> Any:
        raise NERError("down")

    ner(fail)
    reply = api_as(technician_user).post(
        f"{STAFF}/logs/search", data=logs(), content_type="application/json"
    )

    body = reply.json()
    assert reply.status_code == 200
    assert [line["message"] for line in body["lines"]] == [WITHHELD, WITHHELD]
    assert (body["total"], body["withheld"]) == (2, 2)
    assert body["lines"][0]["server"] == "db-01"
    assert InfraQuery.objects.get().withheld == 2


def test_pii_in_a_log_line_or_span_attribute_is_masked(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    es.docs = [log_doc("p", "login failed for lan.nt@saomai.vn")]
    lines = api_as(technician_user).post(
        f"{STAFF}/logs/search", data=logs(), content_type="application/json"
    )
    es.docs = [span_doc("p", user="lan.nt@saomai.vn")]
    spans = api_as(technician_user).post(
        f"{STAFF}/traces/search", data=logs(), content_type="application/json"
    )

    assert "lan.nt@saomai.vn" not in lines.json()["lines"][0]["message"]
    assert "lan.nt@saomai.vn" not in spans.json()["spans"][0]["attributes"]["user"]
    assert "openstack_project_id" not in spans.json()["spans"][0]["attributes"]


def test_an_answer_is_cut_to_the_result_cap(
    api_as, technician_user, settings, cloud_sim: CloudSim, es: FakeElasticsearch
):
    with_caps(settings, max_result_bytes=700)
    es.docs = [log_doc("p", f"line {i} " + "x" * 100) for i in range(10)]

    reply = api_as(technician_user).post(
        f"{STAFF}/logs/search", data=logs(), content_type="application/json"
    )

    body = reply.json()
    assert body["truncated"] is True
    assert 0 < len(body["lines"]) < 10
    assert body["total"] == 10


# ── the record ──


def test_each_query_writes_one_row_with_its_compiled_query_and_link(
    api_as,
    technician_user,
    settings,
    cloud_sim: CloudSim,
    prom: FakePrometheus,
    es: FakeElasticsearch,
):
    client = api_as(technician_user)
    metrics = client.post(f"{STAFF}/metrics/query", data=latency(), content_type="application/json")
    found = client.post(
        f"{STAFF}/logs/search", data=logs(text="slow"), content_type="application/json"
    )

    by_id = {str(q.id): q for q in InfraQuery.objects.all()}
    metric_row = by_id[metrics.json()["query_id"]]
    log_row = by_id[found.json()["query_id"]]
    assert (metric_row.backend, metric_row.kind) == ("prometheus", "structured")
    assert metric_row.compiled == prom.queries[0]
    assert metric_row.link.startswith(settings.PROMETHEUS_UI_URL + "/graph?g0.expr=")
    assert (log_row.backend, log_row.kind) == ("elasticsearch", "structured")
    assert log_row.compiled.startswith("POST /logs-apm.app*/_search\n")
    assert log_row.link.startswith(settings.KIBANA_URL + "/app/discover#/")
    assert metric_row.projects == log_row.projects == ["*"]


def test_a_trace_links_to_kibanas_trace_page(
    api_as, technician_user, cloud_sim: CloudSim, es: FakeElasticsearch
):
    es.docs = [span_doc("p", trace_id="t1")]

    reply = api_as(technician_user).get(f"{STAFF}/traces/t1")

    assert reply.status_code == 200
    assert reply.json()["spans"][0]["duration_ms"] == 120.0
    assert InfraQuery.objects.get().link.endswith("/app/apm/link-to/trace/t1")


# ── the catalog ──


def test_the_customer_catalog_hides_the_hypervisor_label_and_staff_only_datasets(
    api_as, customer, technician_user
):
    mine = api_as(customer).get(f"{MINE}/catalog").json()
    staff = api_as(technician_user).get(f"{STAFF}/catalog").json()

    def labels(catalog: dict[str, Any]) -> set[str]:
        return {label for m in catalog["metrics"] for label in m["labels"]}

    assert "host" in labels(staff) and "host" not in labels(mine)
    assert "project" not in labels(staff)
    assert {d["name"] for d in mine["log_datasets"]} == {"instance"}
    assert {d["name"] for d in staff["log_datasets"]} == {"instance", "apm_errors"}
    assert staff["caps"]["max_series"] == mine["caps"]["max_series"]


# ── an agent's queries (F17 FR-F17-010, FR-F17-011) ──


def test_an_agent_s_post_query_counts_as_a_read_never_a_write(
    technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus
):
    agent = settings.THRESHOLDS.agent.model_copy(
        update={"max_read_calls_per_turn": 5, "max_tool_calls_per_turn": 0}
    )
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"agent": agent})
    client = as_agent(technician_user, tool="query_metrics")

    reply = client.post(f"{STAFF}/metrics/query", data=latency(), content_type="application/json")

    assert reply.status_code == 200, reply.content
    turn = AgentTurn.objects.get()
    assert (turn.read_calls, turn.write_calls) == (1, 0)
    assert turn.ran_a_read()
