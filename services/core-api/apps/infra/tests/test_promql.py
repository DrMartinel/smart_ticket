"""Raw PromQL: parsed by Prometheus, refused on what FR-F17-005 names and on anything core-api
can't check, written back out with the caller's projects on every selector, sent only through
prom-label-proxy, and recorded (F17 FR-F17-005, BR-F17-05, BR-F17-10, AC-F17-03, OQ-F17-05)."""

from __future__ import annotations

import re
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from django.conf import settings as django_settings

from apps.accounts.models import User
from apps.agent.testing import as_agent
from apps.infra.domain.promql import PromQLQuery, duration
from apps.infra.domain.queries import Window
from apps.infra.models import InfraQuery
from apps.infra.testing import (
    DAY,
    HOUR,
    MINUTE,
    Node,
    agg,
    binary,
    call,
    m,
    num,
    paren,
    ranged,
    string,
    subquery,
    unary,
    vs,
)
from apps.infra.tests.conftest import (
    LAN_SUBJECT,
    CloudSim,
    FakeElasticsearch,
    FakePrometheus,
    series,
)

pytestmark = pytest.mark.django_db

START, END = "2026-11-26T08:00:00Z", "2026-11-26T10:00:00Z"
STAFF = "/api/infra/metrics/promql"


def volume(metric: str) -> Node:
    return vs(metric, m("volume_id", "=", "vol-db-01"))


# rate(cloud_volume_iops_total{volume_id="vol-db-01"}[5m]) / cloud_volume_iops_quota{...}
IOPS_TEXT = (
    'rate(cloud_volume_iops_total{volume_id="vol-db-01"}[5m]) '
    '/ cloud_volume_iops_quota{volume_id="vol-db-01"}'
)
IOPS = binary(
    "/",
    call("rate", ranged(volume("cloud_volume_iops_total"), 5 * MINUTE)),
    volume("cloud_volume_iops_quota"),
)
CPU = vs("cloud_server_cpu_utilization_ratio", m("server", "=", "db-01"))


# ── helpers ──


@pytest.fixture
def customer(employee_user: User) -> User:
    """lan.nt: a member of saomai-prod and saomai-staging in the cloud's Keystone."""
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    return employee_user


def body(text: str = IOPS_TEXT, **extra: Any) -> dict[str, Any]:
    return {"promql": text, "start": START, "end": END, "step_seconds": 60, **extra}


def run(client: Any, **extra: Any) -> Any:
    return client.post(STAFF, data=body(**extra), content_type="application/json")


def refusal(reply: Any) -> tuple[int, str, str | None]:
    found = reply.json()
    return reply.status_code, found["code"], (found.get("details") or {}).get("reason")


def with_caps(settings: Any, **caps: int) -> None:
    infra = settings.THRESHOLDS.infra.model_copy(update=caps)
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(update={"infra": infra})


def selectors(promql: str) -> list[str]:
    """Each selector's braces in `promql`."""
    return re.findall(r"\{[^{}]*\}", promql)


class TooSlow(Exception):
    pass


@contextmanager
def within(seconds: float) -> Iterator[None]:
    """Raises `TooSlow` in the block once it has run for `seconds`."""

    def expire(signum: int, frame: Any) -> None:
        raise TooSlow(f"over {seconds} s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def scoped(tree: Node, projects: frozenset[str] = frozenset({"p1"})) -> str:
    """`tree` written back out by the domain alone, scoped to `projects`."""
    window = Window(datetime(2026, 11, 26, 8, tzinfo=UTC), datetime(2026, 11, 26, 10, tzinfo=UTC))
    query = PromQLQuery("as written", window, 60)
    return query.scoped(tree, django_settings.THRESHOLDS.infra, projects)


# ── scope ──


def test_every_selector_of_a_raw_query_carries_the_callers_project_and_only_the_proxy_runs_it(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prod = cloud_sim.id_of("projects", "saomai-prod")
    prom.tree = IOPS

    reply = run(api_as(technician_user), project_id=prod)

    assert reply.status_code == 200
    assert prom.parsed == [IOPS_TEXT]
    assert prom.queries == [
        f'rate(cloud_volume_iops_total{{volume_id="vol-db-01",project="{prod}"}}[5m]) '
        f'/ cloud_volume_iops_quota{{volume_id="vol-db-01",project="{prod}"}}'
    ]
    assert prom.projects == [[prod]]


def test_staff_raw_queries_are_scoped_to_every_keystone_project(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.tree = IOPS

    run(api_as(technician_user))

    every = sorted(cloud_sim.cloud.projects)
    found = selectors(prom.queries[0])
    assert prom.projects == [every]
    assert len(found) == 2
    assert all(s.endswith(f',project=~"{"|".join(every)}"}}') for s in found)


def test_every_selector_is_scoped_however_deep_it_sits():
    tree = binary(
        "or",
        binary(
            ">",
            call(
                "max_over_time",
                subquery(
                    agg("sum", call("rate", ranged(volume("a"), 5 * MINUTE)), by=("volume",)),
                    HOUR,
                    MINUTE,
                ),
            ),
            agg("max", vs("b", m("server", "!=", "db-02"))),
            card="many-to-one",
            on=True,
            labels=("volume",),
            returns_bool=True,
        ),
        unary("-", paren(vs("", m("__name__", "=~", "cloud_.+"), offset=HOUR))),
        card="many-to-many",
    )

    promql = scoped(tree)

    assert len(selectors(promql)) == 3
    assert all(s.endswith(',project="p1"}') for s in selectors(promql))


def test_a_raw_query_naming_the_project_is_refused(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    other = cloud_sim.id_of("projects", "hbr-web")
    prom.tree = vs("cloud_server_up", m("project", "=", other))

    reply = run(api_as(technician_user), text=f'cloud_server_up{{project="{other}"}}')

    assert refusal(reply) == (422, "infra_query_refused", "field")
    assert prom.queries == []


@pytest.mark.parametrize(
    "tree",
    [
        {"type": "durationExpr", "op": "*", "lhs": num("1"), "rhs": num("2")},
        vs("cloud_server_up", m("server", "~~", "db-01")),
        vs("cloud_server_up", m("server.name", "=", "db-01")),
        vs('cloud_server_up{project="x"} or vector(1)'),
        vs("cloud_server_up", at="now"),
        unary("!", CPU),
        binary("+", CPU, CPU, card="sideways"),
        agg("sum", CPU, by=("server) or vector(1) #",)),
        vs("cloud_server_up") | {"anchored": True},
        vs("cloud_server_up", m("server", "=", "db-01") | {"utf8": True}),
        binary("+", CPU, CPU)
        | {"matching": {"card": "one-to-one", "labels": [], "on": False, "include": [], "fill": 0}},
    ],
    ids=[
        "unknown_node",
        "unknown_matcher",
        "quoted_label",
        "metric_name_breakout",
        "unknown_at",
        "unknown_unary",
        "unknown_matching",
        "grouping_breakout",
        "unknown_node_key",
        "unknown_matcher_key",
        "unknown_matching_key",
    ],
)
def test_a_tree_core_api_cannot_check_is_refused_and_never_run(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, tree
):
    prom.tree = tree

    reply = run(api_as(technician_user))

    assert refusal(reply) == (422, "infra_query_refused", "unsupported")
    assert prom.queries == []


def test_a_label_value_cannot_break_out_of_its_matcher():
    evil = 'x"} or vector(1) #'

    promql = scoped(vs("cloud_server_up", m("server", "=", evil)))

    assert promql == 'cloud_server_up{server="x\\"} or vector(1) #",project="p1"}'


@pytest.mark.parametrize("depth", [1_500, 100_000])
def test_a_query_nested_too_deeply_is_refused_and_never_run(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, depth
):
    prom.tree = (
        '{"type":"parenExpr","expr":' * depth + '{"type":"numberLiteral","val":"1"}' + ("}" * depth)
    )

    reply = run(api_as(technician_user))

    assert refusal(reply) == (422, "infra_query_refused", "unsupported")
    assert prom.queries == []


# ── the parser ──


def test_an_unreachable_parser_refuses_the_query_and_never_runs_it(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.parse_raises = httpx.ConnectError("refused")

    reply = run(api_as(technician_user))

    assert reply.status_code == 424
    assert reply.json()["details"] == {"backend": "prometheus"}
    assert prom.queries == []
    row = InfraQuery.objects.get()
    assert (row.kind, row.outcome, row.compiled) == ("promql", "backend_unavailable", IOPS_TEXT)


@pytest.mark.parametrize("status", [404, 500, 503])
def test_a_parser_answering_an_error_refuses_the_query_and_never_runs_it(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, status
):
    prom.parse_status = status

    reply = run(api_as(technician_user))

    assert refusal(reply)[:2] == (424, "infra_backend_unavailable")
    assert prom.queries == []


@pytest.mark.parametrize(
    "tree",
    [
        None,
        {"type": "call"},
        vs("up") | {"offset": "5m"},
        vs("up", {"name": "server", "type": "=", "value": 5}),
        call("vector", {"type": "stringLiteral", "val": ["x"]}),
        num("1e3"),
        num("Inf"),
    ],
)
def test_an_unreadable_parse_refuses_the_query_and_never_runs_it(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, tree
):
    prom.tree = tree

    reply = run(api_as(technician_user))

    assert refusal(reply)[:2] == (424, "infra_backend_unavailable")
    assert prom.queries == []


def test_a_query_prometheus_cannot_parse_is_refused_with_its_message(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.parse_status, prom.parse_error = 400, '1:6: parse error: unexpected "}"'

    reply = run(api_as(technician_user), text="rate(}")

    assert refusal(reply) == (422, "infra_query_refused", "backend_refused")
    assert "unexpected" in reply.json()["message"]
    assert prom.queries == []


def test_an_unreachable_prometheus_after_parsing_is_424_and_recorded(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.tree, prom.status = IOPS, 503

    reply = run(api_as(technician_user))

    assert refusal(reply)[:2] == (424, "infra_backend_unavailable")
    assert InfraQuery.objects.get().outcome == "backend_unavailable"


# ── the checks (FR-F17-005) ──


def test_a_match_everything_selector_is_refused_ac_f17_03(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    text = 'rate(node_cpu_seconds_total{instance=~".*"}[5m])'
    prom.tree = call(
        "rate", ranged(vs("node_cpu_seconds_total", m("instance", "=~", ".*")), 5 * MINUTE)
    )

    reply = run(api_as(technician_user), text=text)

    assert refusal(reply) == (422, "infra_query_refused", "match_all")
    assert prom.queries == []
    row = InfraQuery.objects.get()
    assert (row.kind, row.outcome, row.refusal, row.compiled) == (
        "promql",
        "refused",
        "infra_query_refused",
        text,
    )


@pytest.mark.parametrize(
    ("tree", "reason"),
    [
        (
            call("label_replace", CPU, string("p"), string("x"), string("server"), string("")),
            "function",
        ),
        (call("info", CPU), "function"),
        (agg("count_values", CPU, param=string("value")), "function"),
        (call("rate", ranged(volume("cloud_volume_iops_total"), 8 * DAY)), "range"),
        (subquery(CPU, 8 * DAY, MINUTE), "range"),
        (subquery(CPU, HOUR, 5_000), "step"),
        (subquery(CPU, HOUR, 0), "step"),
        (vs("cloud_server_up", m("server", "=~", ".+")), "match_all"),
        (vs("cloud_server_up", m("server", "=~", "(.*)|db-01")), "match_all"),
        (vs("cloud_server_up", m("server", "!=", "")), "match_all"),
        (vs("cloud_server_up", m("server", "!~", "")), "match_all"),
        (vs("cloud_server_up", m("server", "!~", "()")), "match_all"),
        (vs("cloud_server_up", m("server", "!~", "^$")), "match_all"),
        (vs("cloud_server_up", m("server", "!~", "x{0}")), "match_all"),
        (vs("", m("__name__", "=~", ".*"), m("server", "=", "db-01")), "match_all"),
        (vs("cloud_server_up", m("server", "=~", "a{1001}")), "unsupported"),
        (
            binary(
                "*", CPU, CPU, card="many-to-one", on=True, labels=("server",), include=("project",)
            ),
            "field",
        ),
        (
            binary(
                "*", CPU, CPU, card="one-to-many", labels=("host",), include=("server", "project")
            ),
            "field",
        ),
        (binary("*", CPU, CPU, card="many-to-one", include=("project_name",)), "field"),
        (binary("*", CPU, CPU, card="one-to-many", include=("project_name",)), "field"),
    ],
)
def test_a_raw_query_outside_the_checks_is_refused_and_never_run(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, tree, reason
):
    prom.tree = tree

    reply = run(api_as(technician_user))

    assert refusal(reply) == (422, "infra_query_refused", reason)
    assert prom.queries == []
    assert InfraQuery.objects.get().outcome == "refused"


@pytest.mark.parametrize(
    "matcher",
    [
        m("server", "=~", "db-.*"),
        m("server", "=~", "(db-01)?"),
        m("server", "!=", "db-02"),
        m("server", "!~", "web-.*"),
        m("server", "!~", "a?"),
        m("server", "=", ""),
        m("server", "=~", "(?i)db-.*"),
    ],
)
def test_a_matcher_that_narrows_is_allowed(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, matcher
):
    prom.tree = vs("cloud_server_up", matcher)

    assert run(api_as(technician_user)).status_code == 200
    assert len(prom.queries) == 1


@pytest.mark.parametrize(
    ("kind", "pattern", "runs"),
    [("=~", "a|db-01|" + ".*" * 40 + "Q", True), ("!~", "|" + ".*" * 40 + "Q", False)],
)
def test_a_catastrophic_regex_is_checked_in_linear_time(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, kind, pattern, runs
):
    prom.tree = vs("cloud_server_up", m("server", kind, pattern))
    client = api_as(technician_user)

    with within(seconds=2):
        reply = run(client)

    assert reply.status_code == (200 if runs else 422)
    assert len(prom.queries) == (1 if runs else 0)


def test_a_regex_over_the_memory_cap_is_refused_and_never_run(
    api_as, technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus
):
    with_caps(settings, max_regex_kib=64)
    prom.tree = vs("cloud_server_up", m("server", "=~", r"\pL{10}"))

    reply = run(api_as(technician_user))

    assert refusal(reply) == (422, "infra_query_refused", "unsupported")
    assert prom.queries == []


@pytest.mark.parametrize(
    ("third", "runs"), [(m("server", "=~", "web-.*"), False), (m("server", "=", "web-01"), True)]
)
def test_more_regex_matchers_than_the_cap_are_refused(
    api_as, technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus, third, runs
):
    with_caps(settings, max_regex_matchers=2)
    prom.tree = binary(
        "+",
        vs("cloud_server_up", third),
        vs("cloud_server_up", m("server", "=~", "db-.*"), m("server_id", "!~", "s1")),
    )

    reply = run(api_as(technician_user))

    if runs:
        assert reply.status_code == 200 and len(prom.queries) == 1
    else:
        assert refusal(reply) == (422, "infra_query_refused", "selectors")
        assert prom.queries == []


@pytest.mark.parametrize(
    "path", ["metrics/promql", "metrics/query", "logs/search", "traces/search"]
)
def test_an_empty_project_id_is_refused_and_runs_nothing(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, es: FakeElasticsearch, path
):
    prom.tree = IOPS
    data = body(project_id="") | {"metric": "cloud_volume_read_latency_seconds"}

    reply = api_as(technician_user).post(
        f"/api/infra/{path}", data=data, content_type="application/json"
    )

    assert reply.status_code == 422
    assert prom.parsed == [] and prom.queries == [] and es.searches == []
    assert not InfraQuery.objects.exists()


def test_more_selectors_than_the_cap_are_refused(
    api_as, technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus
):
    with_caps(settings, max_selectors=2)
    prom.tree = binary("+", binary("+", CPU, CPU), CPU)

    reply = run(api_as(technician_user))

    assert refusal(reply) == (422, "infra_query_refused", "selectors")
    assert prom.queries == []


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"step_seconds": 5}, "step"),
        ({"start": "2026-11-01T00:00:00Z"}, "range"),
        ({"start": END, "end": START}, "range"),
    ],
)
def test_a_range_or_step_over_the_caps_is_refused_before_parsing(
    api_as, technician_user, cloud_sim: CloudSim, prom: FakePrometheus, extra, reason
):
    prom.tree = IOPS

    reply = run(api_as(technician_user), **extra)

    assert refusal(reply) == (422, "infra_query_refused", reason)
    assert prom.parsed == [] and prom.queries == []


def test_more_series_than_the_cap_are_refused(
    api_as, technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus
):
    with_caps(settings, max_series=1)
    prom.tree = IOPS
    prom.series = [series("p", volume_id="v1"), series("p", volume_id="v2")]

    reply = run(api_as(technician_user))

    assert refusal(reply) == (422, "infra_query_refused", "series")


# ── who may run it ──


def test_customers_have_no_raw_promql(api_as, customer, cloud_sim: CloudSim, prom: FakePrometheus):
    prom.tree = IOPS
    client = api_as(customer)

    staff = run(client)
    mine = client.post(
        "/api/requester/infra/metrics/promql", data=body(), content_type="application/json"
    )

    assert staff.status_code == 403
    assert staff.json()["details"]["permission"] == "urn:smart-ticket:perm:infra:read"
    assert mine.status_code == 404
    assert prom.parsed == [] and prom.queries == []


def test_an_agent_runs_raw_promql_as_its_person(
    technician_user, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.tree = IOPS

    reply = run(as_agent(technician_user, "run_promql"))

    assert reply.status_code == 200
    row = InfraQuery.objects.get()
    assert (row.via, row.actor, row.kind) == ("agent", technician_user, "promql")
    assert row.agent_turn is not None


# ── the record and the answer ──


def test_a_raw_query_writes_one_row_with_what_ran_and_its_link(
    api_as, technician_user, settings, cloud_sim: CloudSim, prom: FakePrometheus
):
    prom.tree = IOPS
    prom.series = [series("p", volume_id="vol-db-01", host="hv-01")]

    reply = api_as(technician_user).post(STAFF, data=body(), content_type="application/json")

    row = InfraQuery.objects.get(id=reply.json()["query_id"])
    assert (row.backend, row.kind, row.outcome, row.rows) == ("prometheus", "promql", "ok", 1)
    assert row.compiled == prom.queries[0]
    assert row.link.startswith(settings.PROMETHEUS_UI_URL + "/graph?g0.expr=")
    assert row.projects == ["*"]
    assert reply.json()["series"][0]["labels"]["host"] == "hv-01"


def test_the_catalog_lists_raw_promql_functions_for_staff_only(api_as, customer, technician_user):
    staff = api_as(technician_user).get("/api/infra/catalog").json()
    mine = api_as(customer).get("/api/requester/infra/catalog").json()

    assert "rate" in staff["promql_functions"] and "topk" in staff["promql_aggregations"]
    assert not {"info", "label_replace", "label_join"} & set(staff["promql_functions"])
    assert mine["promql_functions"] == mine["promql_aggregations"] == []
    assert staff["caps"]["max_selectors"] == django_settings.THRESHOLDS.infra.max_selectors


# ── writing a parsed query back out ──


@pytest.mark.parametrize(
    ("tree", "promql"),
    [
        (
            IOPS,
            'rate(cloud_volume_iops_total{volume_id="vol-db-01",project="p1"}[5m]) '
            '/ cloud_volume_iops_quota{volume_id="vol-db-01",project="p1"}',
        ),
        (
            agg(
                "topk",
                call("max_over_time", ranged(CPU, 90 * MINUTE)),
                by=("server", "project"),
                param=num("3"),
            ),
            "topk by (server, project) (3, max_over_time(cloud_server_cpu_utilization_ratio"
            '{server="db-01",project="p1"}[1h30m]))',
        ),
        (
            agg("sum", CPU, by=("host",), without=True),
            'sum without (host) (cloud_server_cpu_utilization_ratio{server="db-01",project="p1"})',
        ),
        (
            agg("avg", CPU),
            'avg(cloud_server_cpu_utilization_ratio{server="db-01",project="p1"})',
        ),
        (
            binary(">", CPU, num("0.9"), returns_bool=True),
            'cloud_server_cpu_utilization_ratio{server="db-01",project="p1"} > bool 0.9',
        ),
        (
            binary("*", CPU, CPU, card="one-to-many", labels=("server",), include=("host",)),
            'cloud_server_cpu_utilization_ratio{server="db-01",project="p1"} * ignoring (server) '
            'group_right (host) cloud_server_cpu_utilization_ratio{server="db-01",project="p1"}',
        ),
        (
            binary("*", CPU, CPU, card="many-to-one", include=("host",)),
            'cloud_server_cpu_utilization_ratio{server="db-01",project="p1"} * ignoring () '
            'group_left (host) cloud_server_cpu_utilization_ratio{server="db-01",project="p1"}',
        ),
        (
            binary("unless", CPU, CPU, card="many-to-many", on=True),
            'cloud_server_cpu_utilization_ratio{server="db-01",project="p1"} unless on () '
            'cloud_server_cpu_utilization_ratio{server="db-01",project="p1"}',
        ),
        (
            binary("-", num("1"), binary("*", CPU, num("-1"))),
            '1 - (cloud_server_cpu_utilization_ratio{server="db-01",project="p1"} * -1)',
        ),
        (
            binary("/", paren(binary("+", CPU, CPU)), num("+Inf")),
            '(cloud_server_cpu_utilization_ratio{server="db-01",project="p1"} + '
            'cloud_server_cpu_utilization_ratio{server="db-01",project="p1"}) / +Inf',
        ),
        (
            unary("-", CPU),
            '-(cloud_server_cpu_utilization_ratio{server="db-01",project="p1"})',
        ),
        (
            vs("cloud_server_up", offset=-5 * MINUTE, timestamp=1764147600123),
            'cloud_server_up{project="p1"} offset -5m @ 1764147600.123',
        ),
        (
            ranged(vs("cloud_volume_iops_total", offset=DAY, at="end"), 5 * MINUTE),
            'cloud_volume_iops_total{project="p1"}[5m] offset 1d @ end()',
        ),
        (
            subquery(call("rate", ranged(volume("a"), 5 * MINUTE)), HOUR, 30_000, offset=HOUR),
            '(rate(a{volume_id="vol-db-01",project="p1"}[5m]))[1h:30s] offset 1h',
        ),
        (
            vs("", m("__name__", "=~", "cloud_.+"), m("server", "!~", "web-.*")),
            '{__name__=~"cloud_.+",server!~"web-.*",project="p1"}',
        ),
        (
            call("histogram_quantile", num("0.9"), call("vector", num("NaN"))),
            "histogram_quantile(0.9, vector(NaN))",
        ),
        (call("time"), "time()"),
    ],
)
def test_a_parsed_query_is_written_back_out_as_the_same_promql(tree, promql):
    assert scoped(tree) == promql


def test_several_projects_are_one_regex_matcher():
    assert scoped(CPU, frozenset({"p2", "p1"})).endswith(',project=~"p1|p2"}')


@pytest.mark.parametrize(
    ("ms", "written"),
    [(0, "0s"), (1_500, "1s500ms"), (5 * MINUTE, "5m"), (8 * DAY, "1w1d"), (-HOUR, "-1h")],
)
def test_a_duration_is_written_in_promqls_units(ms, written):
    assert duration(ms) == written
