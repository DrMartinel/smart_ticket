"""
The cloud tools (spec F17 §h.1): the technician's on the console, over every
project, and the customer's on the chat, over their own. Each project,
server, volume and network a result holds gets a ref the person could pick
(FR-F17-024), and the text the cloud holds is wrapped as untrusted
(BR-F17-06).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field

from ai_engine.agent.tools.chat import nothing
from ai_engine.agent.tools.console import drafted
from ai_engine.agent.tools.projection import WITHHELD, person, ref, untrusted
from ai_engine.agent.tools.tool import Context, PublicIdIn, Tier, Tool, ToolInput

ResourceId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Filters = dict[Name, list[Annotated[str, Field(min_length=1, max_length=200)]]]

# A name a ref's label may show; any other name is shown by its resource's id.
_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def cloud_text(text: str | None) -> dict[str, str] | str | None:
    """Text the cloud holds, as untrusted, or `[withheld]` when core-api withheld it."""
    return WITHHELD if text == WITHHELD else untrusted(text)


def cloud_pairs(mapping: dict[str, Any] | None) -> list[dict[str, str] | str | None]:
    """Keys and values the cloud holds, each pair as one untrusted `key=value`."""
    return [
        WITHHELD if value == WITHHELD else untrusted(f"{key}={value}")
        for key, value in (mapping or {}).items()
    ]


def resource_ref(context: Context, kind: str, row: dict[str, Any]) -> dict[str, str]:
    """The ref of a project, server, volume or network, labelled by its name when that is a
    plain name and by its id otherwise; none for a row with no id."""
    item_id, name = row.get("id"), row.get("name") or ""
    if not item_id:
        return {}
    label = name if _PLAIN_NAME.fullmatch(name) else str(item_id)
    return {"ref": ref(context, kind, str(item_id), label)}


# ── resources ──


def project(row: Any, context: Context) -> dict[str, Any]:
    return {**resource_ref(context, "project", row), "id": row.get("id"), "name": row.get("name")}


def projects(body: Any, context: Context) -> list[dict[str, Any]]:
    """A caller's cloud projects."""
    return [project(row, context) for row in body]


def attachments(rows: list[Any] | None) -> list[dict[str, Any]]:
    return [
        {
            "volume_id": a.get("volume_id"),
            "server_id": a.get("server_id"),
            "device": a.get("device"),
        }
        for a in rows or []
    ]


def server(row: Any, context: Context) -> dict[str, Any]:
    """A server: its state, size, addresses, volumes and groups, with its text untrusted."""
    shown = {
        **resource_ref(context, "server", row),
        **{
            name: row.get(name)
            for name in (
                "id",
                "name",
                "project_id",
                "status",
                "task_state",
                "host",
                "flavor",
                "vcpus",
                "ram_mb",
                "volume_ids",
                "security_groups",
                "created",
                "updated",
            )
        },
        "addresses": [
            {"network": a.get("network"), "ip": a.get("ip")} for a in row.get("addresses") or []
        ],
        "description": cloud_text(row.get("description")),
        "metadata": cloud_pairs(row.get("metadata")),
    }
    if "attachments" in row:
        shown["attachments"] = attachments(row["attachments"])
    return shown


def servers(body: Any, context: Context) -> list[dict[str, Any]]:
    """A caller's servers."""
    return [server(row, context) for row in body]


def volume(row: Any, context: Context) -> dict[str, Any]:
    """A volume: its state, size, type and attachments, with its text untrusted."""
    return {
        **resource_ref(context, "volume", row),
        **{
            name: row.get(name)
            for name in ("id", "name", "project_id", "status", "size_gb", "volume_type", "created")
        },
        "attachments": attachments(row.get("attachments")),
        "description": cloud_text(row.get("description")),
        "metadata": cloud_pairs(row.get("metadata")),
    }


def volumes(body: Any, context: Context) -> list[dict[str, Any]]:
    """A caller's volumes."""
    return [volume(row, context) for row in body]


def security_group(row: Any) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": cloud_text(row.get("description")),
        "rules": [
            {
                name: rule.get(name)
                for name in (
                    "id",
                    "direction",
                    "ethertype",
                    "protocol",
                    "port_min",
                    "port_max",
                    "remote_ip_prefix",
                )
            }
            for rule in row.get("rules") or []
        ],
    }


def network(row: Any, context: Context) -> dict[str, Any]:
    """A network, and on its own page its subnets, ports and its project's security groups."""
    shown = {
        **resource_ref(context, "network", row),
        **{name: row.get(name) for name in ("id", "name", "project_id", "status")},
        "description": cloud_text(row.get("description")),
    }
    if "subnets" in row:
        shown["subnets"] = [
            {name: s.get(name) for name in ("id", "name", "cidr", "ip_version")}
            for s in row.get("subnets") or []
        ]
        shown["ports"] = [
            {
                name: p.get(name)
                for name in ("id", "device_id", "ips", "status", "security_group_ids")
            }
            for p in row.get("ports") or []
        ]
        shown["security_groups"] = [security_group(g) for g in row.get("security_groups") or []]
    return shown


def networks(body: Any, context: Context) -> list[dict[str, Any]]:
    """A caller's networks."""
    return [network(row, context) for row in body]


def alerts(body: Any, context: Context) -> list[dict[str, Any]]:
    """Firing alerts, with their summary and description untrusted."""
    return [
        {
            **{
                name: row.get(name)
                for name in ("name", "state", "severity", "project_id", "labels", "starts_at")
            },
            "summary": cloud_text(row.get("summary")),
            "description": cloud_text(row.get("description")),
        }
        for row in body
    ]


def silences(body: Any, context: Context) -> list[dict[str, Any]]:
    """Alertmanager silences, their author shown as a person and their comment untrusted."""
    return [
        {
            **{
                name: row.get(name)
                for name in ("id", "state", "project_id", "starts_at", "ends_at")
            },
            "matchers": [
                {name: m.get(name) for name in ("name", "value", "is_regex", "is_equal")}
                for m in row.get("matchers") or []
            ],
            "created_by": person(row.get("created_by"), context.actor_username),
            "comment": cloud_text(row.get("comment")),
        }
        for row in body
    ]


# ── queries ──


def catalog(body: Any, context: Context) -> dict[str, Any]:
    """What a query may name, and the caps it is checked against."""
    entries = ("name", "help")
    return {
        "metrics": [
            {name: m.get(name) for name in ("name", "kind", "help", "labels")}
            for m in body.get("metrics") or []
        ],
        "range_functions": body.get("range_functions"),
        "aggregations": body.get("aggregations"),
        "log_datasets": [
            {name: d.get(name) for name in entries} for d in body.get("log_datasets") or []
        ],
        "log_fields": [
            {name: f.get(name) for name in entries} for f in body.get("log_fields") or []
        ],
        "trace_fields": [
            {name: f.get(name) for name in entries} for f in body.get("trace_fields") or []
        ],
        "promql_functions": body.get("promql_functions"),
        "promql_aggregations": body.get("promql_aggregations"),
        "caps": body.get("caps"),
    }


def metric_answer(body: Any, context: Context) -> dict[str, Any]:
    """A metric query's series and the id of its recorded query."""
    return {
        "query_id": body.get("query_id"),
        "series": [
            {"labels": s.get("labels"), "points": s.get("points")} for s in body.get("series") or []
        ],
        "truncated": body.get("truncated"),
    }


def log_answer(body: Any, context: Context) -> dict[str, Any]:
    """A log search's lines, their messages untrusted, and the id of its recorded query."""
    return {
        **{name: body.get(name) for name in ("query_id", "total", "truncated", "withheld")},
        "lines": [
            {
                **{
                    name: line.get(name)
                    for name in ("at", "level", "project_id", "server", "server_id", "service")
                },
                "message": cloud_text(line.get("message")),
            }
            for line in body.get("lines") or []
        ],
    }


def trace_answer(body: Any, context: Context) -> dict[str, Any]:
    """A trace search's spans, their attributes untrusted, and the id of its recorded query."""
    return {
        **{name: body.get(name) for name in ("query_id", "truncated", "withheld")},
        "spans": [
            {
                **{
                    name: span.get(name)
                    for name in (
                        "trace_id",
                        "id",
                        "parent_id",
                        "name",
                        "project_id",
                        "service",
                        "server",
                        "started_at",
                        "duration_ms",
                        "outcome",
                    )
                },
                "attributes": cloud_pairs(span.get("attributes")),
            }
            for span in body.get("spans") or []
        ],
    }


# ── arguments ──


class ProjectIn(ToolInput):
    project_id: ResourceId | None = None


class ServerIn(ToolInput):
    server_id: ResourceId


class VolumeIn(ToolInput):
    volume_id: ResourceId


class NetworkIn(ToolInput):
    network_id: ResourceId


class TraceIn(ToolInput):
    trace_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z-]+$")]


class WindowIn(ToolInput):
    start: AwareDatetime
    end: AwareDatetime
    project_id: ResourceId | None = None


class MetricQueryIn(WindowIn):
    metric: Name
    step_seconds: int = Field(ge=1)
    filters: Filters = {}
    function: Name | None = None
    function_seconds: int | None = Field(None, ge=1)
    aggregate: Name | None = None
    by: list[Name] = []


class PromQLIn(WindowIn):
    promql: str = Field(min_length=1, max_length=2_000)
    step_seconds: int = Field(ge=1)


class LogSearchIn(WindowIn):
    dataset: Name | None = None
    text: str | None = Field(None, min_length=1, max_length=500)
    filters: Filters = {}
    size: int | None = Field(None, ge=1)


class TraceSearchIn(WindowIn):
    filters: Filters = {}
    min_duration_ms: int | None = Field(None, ge=0)
    size: int | None = Field(None, ge=1)


class ServerChangeIn(PublicIdIn):
    server_id: ResourceId


class VolumeChangeIn(PublicIdIn):
    volume_id: ResourceId


class AttachIn(VolumeChangeIn):
    server_id: ResourceId


class SecurityRuleIn(PublicIdIn):
    group_id: ResourceId
    direction: Literal["ingress", "egress"]
    ethertype: Literal["IPv4", "IPv6"] | None = None
    protocol: Literal["tcp", "udp", "icmp"] | None = None
    port_range_min: int | None = Field(None, ge=1, le=65535)
    port_range_max: int | None = Field(None, ge=1, le=65535)
    remote_ip_prefix: str | None = Field(None, min_length=1, max_length=50)


class SecurityRuleRemoveIn(PublicIdIn):
    group_id: ResourceId
    rule_id: ResourceId


# ── the tools ──

_LISTING = ("project_id",)
_WINDOW = "start and end need a UTC offset; project_id narrows it to one project."
_FOR_TICKET = "public_id names the open ticket it is for."
_CATALOG = (
    "List the metrics, labels, log datasets, fields and functions a query may name, and its caps."
)
_METRICS = (
    "Query one metric from the catalog over a time range, filtered on its labels, optionally "
    f"through a range function and an aggregate. {_WINDOW}"
)
_LOGS = (
    "Search the log lines of one dataset from the catalog over a time range, by text and by "
    f"fields. {_WINDOW}"
)
_TRACES = f"Search trace spans over a time range, by fields and by duration. {_WINDOW}"


def _read(
    surface: Literal["chat", "console"],
    name: str,
    method: str,
    path: str,
    Input: type[ToolInput],
    project: Callable[[Any, Context], Any],
    description: str,
    query: tuple[str, ...] = (),
) -> Tool:
    return Tool(
        name=name,
        surface=surface,
        tier=Tier.READ,
        method=method,
        path=path,
        Input=Input,
        description=description,
        project=project,
        query=query,
    )


def _change(
    name: str,
    tier: Tier,
    method: str,
    path: str,
    Input: type[ToolInput],
    description: str,
    fixed: Mapping[str, Any] | None = None,
) -> Tool:
    """A console change on a resource, for an open ticket the technician covers."""
    return Tool(
        name=name,
        surface="console",
        tier=tier,
        method=method,
        path=path,
        Input=Input,
        description=f"{description} {_FOR_TICKET}",
        project=nothing if tier is Tier.CONFIRM else drafted,
        fixed=fixed or {},
    )


def _my_change(
    name: str, path: str, description: str, fixed: Mapping[str, Any] | None = None
) -> Tool:
    """A chat change on one of the customer's own servers, which they confirm."""
    return Tool(
        name=name,
        surface="chat",
        tier=Tier.CONFIRM,
        method="POST",
        path=path,
        Input=ServerIn,
        description=description,
        project=nothing,
        fixed=fixed or {},
    )


CONSOLE_TOOLS = (
    _read("console", "infra_catalog", "GET", "/api/infra/catalog", ToolInput, catalog, _CATALOG),
    _read(
        "console",
        "list_projects",
        "GET",
        "/api/infra/projects",
        ToolInput,
        projects,
        "List every cloud project.",
    ),
    _read(
        "console",
        "list_servers",
        "GET",
        "/api/infra/servers",
        ProjectIn,
        servers,
        "List the servers of every project, or of one.",
        _LISTING,
    ),
    _read(
        "console",
        "get_server",
        "GET",
        "/api/infra/servers/{server_id}",
        ServerIn,
        server,
        "Read one server by id: its state, size, addresses and attached volumes.",
    ),
    _read(
        "console",
        "list_volumes",
        "GET",
        "/api/infra/volumes",
        ProjectIn,
        volumes,
        "List the volumes of every project, or of one.",
        _LISTING,
    ),
    _read(
        "console",
        "get_volume",
        "GET",
        "/api/infra/volumes/{volume_id}",
        VolumeIn,
        volume,
        "Read one volume by id: its state, size, type and attachments.",
    ),
    _read(
        "console",
        "list_networks",
        "GET",
        "/api/infra/networks",
        ProjectIn,
        networks,
        "List the networks of every project, or of one.",
        _LISTING,
    ),
    _read(
        "console",
        "get_network",
        "GET",
        "/api/infra/networks/{network_id}",
        NetworkIn,
        network,
        "Read one network by id: its subnets, ports and security groups.",
    ),
    _read(
        "console",
        "list_alerts",
        "GET",
        "/api/infra/alerts",
        ProjectIn,
        alerts,
        "List the alerts firing in every project, or in one.",
        _LISTING,
    ),
    _read(
        "console",
        "list_silences",
        "GET",
        "/api/infra/alerts/silences",
        ProjectIn,
        silences,
        "List the alert silences of every project, or of one.",
        _LISTING,
    ),
    _read(
        "console",
        "query_metrics",
        "POST",
        "/api/infra/metrics/query",
        MetricQueryIn,
        metric_answer,
        _METRICS,
    ),
    _read(
        "console",
        "run_promql",
        "POST",
        "/api/infra/metrics/promql",
        PromQLIn,
        metric_answer,
        "Run a raw PromQL range query with the functions and caps the catalog lists. The system "
        f"adds the project matcher, so never name the project label. {_WINDOW}",
    ),
    _read(
        "console", "search_logs", "POST", "/api/infra/logs/search", LogSearchIn, log_answer, _LOGS
    ),
    _read(
        "console",
        "search_traces",
        "POST",
        "/api/infra/traces/search",
        TraceSearchIn,
        trace_answer,
        _TRACES,
    ),
    _read(
        "console",
        "get_trace",
        "GET",
        "/api/infra/traces/{trace_id}",
        TraceIn,
        trace_answer,
        "Read every span of one trace.",
    ),
    _change(
        "reboot_server",
        Tier.CONFIRM,
        "POST",
        "/api/infra/servers/{server_id}/reboot",
        ServerChangeIn,
        "Prepare a soft reboot of a server. The technician confirms it first.",
        fixed={"type": "soft"},
    ),
    _change(
        "draft_hard_reboot",
        Tier.HUMAN_ONLY,
        "POST",
        "/api/infra/servers/{server_id}/hard-reboot",
        ServerChangeIn,
        "Draft a hard reboot of a server. Only the technician can apply it.",
    ),
    _change(
        "start_server",
        Tier.CONFIRM,
        "POST",
        "/api/infra/servers/{server_id}/start",
        ServerChangeIn,
        "Prepare starting a stopped server. The technician confirms it first.",
    ),
    _change(
        "stop_server",
        Tier.CONFIRM,
        "POST",
        "/api/infra/servers/{server_id}/stop",
        ServerChangeIn,
        "Prepare stopping a server. The technician confirms it first.",
    ),
    _change(
        "attach_volume",
        Tier.CONFIRM,
        "POST",
        "/api/infra/volumes/{volume_id}/attach",
        AttachIn,
        "Prepare attaching a volume to a server. The technician confirms it first.",
    ),
    _change(
        "draft_detach_volume",
        Tier.HUMAN_ONLY,
        "POST",
        "/api/infra/volumes/{volume_id}/detach",
        VolumeChangeIn,
        "Draft detaching a volume. Only the technician can apply it.",
    ),
    _change(
        "draft_security_rule",
        Tier.HUMAN_ONLY,
        "POST",
        "/api/infra/security-groups/{group_id}/rules",
        SecurityRuleIn,
        "Draft adding a rule to a security group. Only the technician can apply it.",
    ),
    _change(
        "draft_remove_security_rule",
        Tier.HUMAN_ONLY,
        "DELETE",
        "/api/infra/security-groups/{group_id}/rules",
        SecurityRuleRemoveIn,
        "Draft removing a rule from a security group. Only the technician can apply it.",
    ),
)

CHAT_TOOLS = (
    _read(
        "chat",
        "my_infra_catalog",
        "GET",
        "/api/requester/infra/catalog",
        ToolInput,
        catalog,
        _CATALOG,
    ),
    _read(
        "chat",
        "list_my_projects",
        "GET",
        "/api/requester/infra/projects",
        ToolInput,
        projects,
        "List the customer's own cloud projects.",
    ),
    _read(
        "chat",
        "list_my_servers",
        "GET",
        "/api/requester/infra/servers",
        ProjectIn,
        servers,
        "List the servers of the customer's projects, or of one.",
        _LISTING,
    ),
    _read(
        "chat",
        "get_my_server",
        "GET",
        "/api/requester/infra/servers/{server_id}",
        ServerIn,
        server,
        "Read one of the customer's servers by id: its state, size, addresses and volumes.",
    ),
    _read(
        "chat",
        "list_my_volumes",
        "GET",
        "/api/requester/infra/volumes",
        ProjectIn,
        volumes,
        "List the volumes of the customer's projects, or of one.",
        _LISTING,
    ),
    _read(
        "chat",
        "get_my_volume",
        "GET",
        "/api/requester/infra/volumes/{volume_id}",
        VolumeIn,
        volume,
        "Read one of the customer's volumes by id: its state, size, type and attachments.",
    ),
    _read(
        "chat",
        "list_my_networks",
        "GET",
        "/api/requester/infra/networks",
        ProjectIn,
        networks,
        "List the networks of the customer's projects, or of one.",
        _LISTING,
    ),
    _read(
        "chat",
        "get_my_network",
        "GET",
        "/api/requester/infra/networks/{network_id}",
        NetworkIn,
        network,
        "Read one of the customer's networks by id: its subnets, ports and groups.",
    ),
    _read(
        "chat",
        "list_my_alerts",
        "GET",
        "/api/requester/infra/alerts",
        ProjectIn,
        alerts,
        "List the alerts firing in the customer's projects, or in one.",
        _LISTING,
    ),
    _read(
        "chat",
        "list_my_silences",
        "GET",
        "/api/requester/infra/alerts/silences",
        ProjectIn,
        silences,
        "List the alert silences of the customer's projects, or of one.",
        _LISTING,
    ),
    _read(
        "chat",
        "query_my_metrics",
        "POST",
        "/api/requester/infra/metrics/query",
        MetricQueryIn,
        metric_answer,
        _METRICS,
    ),
    _read(
        "chat",
        "search_my_logs",
        "POST",
        "/api/requester/infra/logs/search",
        LogSearchIn,
        log_answer,
        _LOGS,
    ),
    _read(
        "chat",
        "search_my_traces",
        "POST",
        "/api/requester/infra/traces/search",
        TraceSearchIn,
        trace_answer,
        _TRACES,
    ),
    _read(
        "chat",
        "get_my_trace",
        "GET",
        "/api/requester/infra/traces/{trace_id}",
        TraceIn,
        trace_answer,
        "Read every span of one of the customer's traces.",
    ),
    _my_change(
        "reboot_my_server",
        "/api/requester/infra/servers/{server_id}/reboot",
        "Prepare a soft reboot of one of the customer's servers. They confirm it first.",
        fixed={"type": "soft"},
    ),
    _my_change(
        "start_my_server",
        "/api/requester/infra/servers/{server_id}/start",
        "Prepare starting one of the customer's stopped servers. They confirm it first.",
    ),
    _my_change(
        "stop_my_server",
        "/api/requester/infra/servers/{server_id}/stop",
        "Prepare stopping one of the customer's servers. They confirm it first.",
    ),
)

TOOLS = (*CONSOLE_TOOLS, *CHAT_TOOLS)
