"""
The cloud tools (spec F17 §h.1): the technician's on the console, over every
project, and the customer's on the chat, over their own. Each project,
server, volume and network a result holds gets a ref the person could pick
(FR-F17-024), and the text the cloud holds, its names and label values among
it unless they are plain names, is wrapped as untrusted (BR-F17-06).
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
from ai_engine.graph.nodes.injection_patterns import matches

ResourceId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Filters = dict[Name, list[Annotated[str, Field(min_length=1, max_length=200)]]]

# The shape of a name the model and a ref's label may see as it is (see `plain`).
_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# A Prometheus label name.
_LABEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def plain(value: str) -> bool:
    """Whether a name the cloud holds may be shown as it is: it has a plain name's shape and the
    injection screen finds nothing in it."""
    return bool(_PLAIN_NAME.fullmatch(value)) and not matches(value)


def cloud_text(text: str | None) -> dict[str, str] | str | None:
    """Text the cloud holds, as untrusted, or `[withheld]` when core-api withheld it."""
    return WITHHELD if text == WITHHELD else untrusted(text)


def cloud_name(value: Any) -> Any:
    """A name or label value the cloud holds: as it is when it is a plain name or not text,
    untrusted otherwise."""
    if not isinstance(value, str) or value == WITHHELD or plain(value):
        return value
    return untrusted(value)


def cloud_labels(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    """Labels the cloud holds, each value as `cloud_name` shows it; only label names Prometheus
    allows."""
    if mapping is None:
        return None
    return {key: cloud_name(value) for key, value in mapping.items() if _LABEL_NAME.fullmatch(key)}


def cloud_pairs(mapping: dict[str, Any] | None) -> list[dict[str, str] | str | None]:
    """Keys and values the cloud holds, each pair as one untrusted `key=value`."""
    return [
        WITHHELD if value == WITHHELD else untrusted(f"{key}={value}")
        for key, value in (mapping or {}).items()
    ]


def resource_ref(context: Context, kind: str, row: dict[str, Any]) -> dict[str, str]:
    """The ref of a project, server, volume or network, labelled by its name and the start of its
    id when the name is `plain`, and by its id otherwise; none for a row whose id is not."""
    item_id, name = str(row.get("id") or ""), row.get("name")
    if not plain(item_id):
        return {}
    named = isinstance(name, str) and plain(name) and name != item_id
    label = f"{name} ({item_id[:8]})" if named else item_id
    return {"ref": ref(context, kind, item_id, label)}


# ── resources ──


def project(row: Any, context: Context) -> dict[str, Any]:
    return {
        **resource_ref(context, "project", row),
        "id": row.get("id"),
        "name": cloud_name(row.get("name")),
    }


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
                "project_id",
                "status",
                "task_state",
                "vcpus",
                "ram_mb",
                "volume_ids",
                "created",
                "updated",
            )
        },
        **{name: cloud_name(row.get(name)) for name in ("name", "host", "flavor")},
        "security_groups": [cloud_name(g) for g in row.get("security_groups") or []],
        "addresses": [
            {"network": cloud_name(a.get("network")), "ip": a.get("ip")}
            for a in row.get("addresses") or []
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
        **{name: row.get(name) for name in ("id", "project_id", "status", "size_gb", "created")},
        **{name: cloud_name(row.get(name)) for name in ("name", "volume_type")},
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
        "name": cloud_name(row.get("name")),
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
        **{name: row.get(name) for name in ("id", "project_id", "status")},
        "name": cloud_name(row.get("name")),
        "description": cloud_text(row.get("description")),
    }
    if "subnets" in row:
        shown["subnets"] = [
            {
                **{name: s.get(name) for name in ("id", "cidr", "ip_version")},
                "name": cloud_name(s.get("name")),
            }
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
            **{name: row.get(name) for name in ("state", "project_id", "starts_at")},
            **{name: cloud_name(row.get(name)) for name in ("name", "severity")},
            "labels": cloud_labels(row.get("labels")),
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
                {
                    **{name: m.get(name) for name in ("is_regex", "is_equal")},
                    **{name: cloud_name(m.get(name)) for name in ("name", "value")},
                }
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
            {"labels": cloud_labels(s.get("labels")), "points": s.get("points")}
            for s in body.get("series") or []
        ],
        "truncated": body.get("truncated"),
    }


def log_answer(body: Any, context: Context) -> dict[str, Any]:
    """A log search's lines, their messages untrusted, and the id of its recorded query."""
    return {
        **{name: body.get(name) for name in ("query_id", "total", "truncated", "withheld")},
        "lines": [
            {
                **{name: line.get(name) for name in ("at", "project_id")},
                **{
                    name: cloud_name(line.get(name))
                    for name in ("level", "server", "server_id", "service")
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
                **{name: span.get(name) for name in ("project_id", "started_at", "duration_ms")},
                **{
                    name: cloud_name(span.get(name))
                    for name in (
                        "trace_id",
                        "id",
                        "parent_id",
                        "name",
                        "service",
                        "server",
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
    *,
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
    *,
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
    *, name: str, path: str, description: str, fixed: Mapping[str, Any] | None = None
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
    _read(
        surface="console",
        name="infra_catalog",
        method="GET",
        path="/api/infra/catalog",
        Input=ToolInput,
        project=catalog,
        description=_CATALOG,
    ),
    _read(
        surface="console",
        name="list_projects",
        method="GET",
        path="/api/infra/projects",
        Input=ToolInput,
        project=projects,
        description="List every cloud project.",
    ),
    _read(
        surface="console",
        name="list_servers",
        method="GET",
        path="/api/infra/servers",
        Input=ProjectIn,
        project=servers,
        description="List the servers of every project, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="console",
        name="get_server",
        method="GET",
        path="/api/infra/servers/{server_id}",
        Input=ServerIn,
        project=server,
        description="Read one server by id: its state, size, addresses and attached volumes.",
    ),
    _read(
        surface="console",
        name="list_volumes",
        method="GET",
        path="/api/infra/volumes",
        Input=ProjectIn,
        project=volumes,
        description="List the volumes of every project, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="console",
        name="get_volume",
        method="GET",
        path="/api/infra/volumes/{volume_id}",
        Input=VolumeIn,
        project=volume,
        description="Read one volume by id: its state, size, type and attachments.",
    ),
    _read(
        surface="console",
        name="list_networks",
        method="GET",
        path="/api/infra/networks",
        Input=ProjectIn,
        project=networks,
        description="List the networks of every project, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="console",
        name="get_network",
        method="GET",
        path="/api/infra/networks/{network_id}",
        Input=NetworkIn,
        project=network,
        description="Read one network by id: its subnets, ports and security groups.",
    ),
    _read(
        surface="console",
        name="list_alerts",
        method="GET",
        path="/api/infra/alerts",
        Input=ProjectIn,
        project=alerts,
        description="List the alerts firing in every project, or in one.",
        query=_LISTING,
    ),
    _read(
        surface="console",
        name="list_silences",
        method="GET",
        path="/api/infra/alerts/silences",
        Input=ProjectIn,
        project=silences,
        description="List the alert silences of every project, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="console",
        name="query_metrics",
        method="POST",
        path="/api/infra/metrics/query",
        Input=MetricQueryIn,
        project=metric_answer,
        description=_METRICS,
    ),
    _read(
        surface="console",
        name="run_promql",
        method="POST",
        path="/api/infra/metrics/promql",
        Input=PromQLIn,
        project=metric_answer,
        description="Run a raw PromQL range query with the functions and caps the catalog lists. The system "
        f"adds the project matcher, so never name the project label. {_WINDOW}",
    ),
    _read(
        surface="console",
        name="search_logs",
        method="POST",
        path="/api/infra/logs/search",
        Input=LogSearchIn,
        project=log_answer,
        description=_LOGS,
    ),
    _read(
        surface="console",
        name="search_traces",
        method="POST",
        path="/api/infra/traces/search",
        Input=TraceSearchIn,
        project=trace_answer,
        description=_TRACES,
    ),
    _read(
        surface="console",
        name="get_trace",
        method="GET",
        path="/api/infra/traces/{trace_id}",
        Input=TraceIn,
        project=trace_answer,
        description="Read every span of one trace.",
    ),
    _change(
        name="reboot_server",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/infra/servers/{server_id}/reboot",
        Input=ServerChangeIn,
        description="Prepare a soft reboot of a server. The technician confirms it first.",
        fixed={"type": "soft"},
    ),
    _change(
        name="draft_hard_reboot",
        tier=Tier.HUMAN_ONLY,
        method="POST",
        path="/api/infra/servers/{server_id}/hard-reboot",
        Input=ServerChangeIn,
        description="Draft a hard reboot of a server. Only the technician can apply it.",
    ),
    _change(
        name="start_server",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/infra/servers/{server_id}/start",
        Input=ServerChangeIn,
        description="Prepare starting a stopped server. The technician confirms it first.",
    ),
    _change(
        name="stop_server",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/infra/servers/{server_id}/stop",
        Input=ServerChangeIn,
        description="Prepare stopping a server. The technician confirms it first.",
    ),
    _change(
        name="attach_volume",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/infra/volumes/{volume_id}/attach",
        Input=AttachIn,
        description="Prepare attaching a volume to a server. The technician confirms it first.",
    ),
    _change(
        name="draft_detach_volume",
        tier=Tier.HUMAN_ONLY,
        method="POST",
        path="/api/infra/volumes/{volume_id}/detach",
        Input=VolumeChangeIn,
        description="Draft detaching a volume. Only the technician can apply it.",
    ),
    _change(
        name="draft_security_rule",
        tier=Tier.HUMAN_ONLY,
        method="POST",
        path="/api/infra/security-groups/{group_id}/rules",
        Input=SecurityRuleIn,
        description="Draft adding a rule to a security group. Only the technician can apply it.",
    ),
    _change(
        name="draft_remove_security_rule",
        tier=Tier.HUMAN_ONLY,
        method="DELETE",
        path="/api/infra/security-groups/{group_id}/rules",
        Input=SecurityRuleRemoveIn,
        description="Draft removing a rule from a security group. Only the technician can apply it.",
    ),
)

CHAT_TOOLS = (
    _read(
        surface="chat",
        name="my_infra_catalog",
        method="GET",
        path="/api/requester/infra/catalog",
        Input=ToolInput,
        project=catalog,
        description=_CATALOG,
    ),
    _read(
        surface="chat",
        name="list_my_projects",
        method="GET",
        path="/api/requester/infra/projects",
        Input=ToolInput,
        project=projects,
        description="List the customer's own cloud projects.",
    ),
    _read(
        surface="chat",
        name="list_my_servers",
        method="GET",
        path="/api/requester/infra/servers",
        Input=ProjectIn,
        project=servers,
        description="List the servers of the customer's projects, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="chat",
        name="get_my_server",
        method="GET",
        path="/api/requester/infra/servers/{server_id}",
        Input=ServerIn,
        project=server,
        description="Read one of the customer's servers by id: its state, size, addresses and volumes.",
    ),
    _read(
        surface="chat",
        name="list_my_volumes",
        method="GET",
        path="/api/requester/infra/volumes",
        Input=ProjectIn,
        project=volumes,
        description="List the volumes of the customer's projects, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="chat",
        name="get_my_volume",
        method="GET",
        path="/api/requester/infra/volumes/{volume_id}",
        Input=VolumeIn,
        project=volume,
        description="Read one of the customer's volumes by id: its state, size, type and attachments.",
    ),
    _read(
        surface="chat",
        name="list_my_networks",
        method="GET",
        path="/api/requester/infra/networks",
        Input=ProjectIn,
        project=networks,
        description="List the networks of the customer's projects, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="chat",
        name="get_my_network",
        method="GET",
        path="/api/requester/infra/networks/{network_id}",
        Input=NetworkIn,
        project=network,
        description="Read one of the customer's networks by id: its subnets, ports and groups.",
    ),
    _read(
        surface="chat",
        name="list_my_alerts",
        method="GET",
        path="/api/requester/infra/alerts",
        Input=ProjectIn,
        project=alerts,
        description="List the alerts firing in the customer's projects, or in one.",
        query=_LISTING,
    ),
    _read(
        surface="chat",
        name="list_my_silences",
        method="GET",
        path="/api/requester/infra/alerts/silences",
        Input=ProjectIn,
        project=silences,
        description="List the alert silences of the customer's projects, or of one.",
        query=_LISTING,
    ),
    _read(
        surface="chat",
        name="query_my_metrics",
        method="POST",
        path="/api/requester/infra/metrics/query",
        Input=MetricQueryIn,
        project=metric_answer,
        description=_METRICS,
    ),
    _read(
        surface="chat",
        name="search_my_logs",
        method="POST",
        path="/api/requester/infra/logs/search",
        Input=LogSearchIn,
        project=log_answer,
        description=_LOGS,
    ),
    _read(
        surface="chat",
        name="search_my_traces",
        method="POST",
        path="/api/requester/infra/traces/search",
        Input=TraceSearchIn,
        project=trace_answer,
        description=_TRACES,
    ),
    _read(
        surface="chat",
        name="get_my_trace",
        method="GET",
        path="/api/requester/infra/traces/{trace_id}",
        Input=TraceIn,
        project=trace_answer,
        description="Read every span of one of the customer's traces.",
    ),
    _my_change(
        name="reboot_my_server",
        path="/api/requester/infra/servers/{server_id}/reboot",
        description="Prepare a soft reboot of one of the customer's servers. They confirm it first.",
        fixed={"type": "soft"},
    ),
    _my_change(
        name="start_my_server",
        path="/api/requester/infra/servers/{server_id}/start",
        description="Prepare starting one of the customer's stopped servers. They confirm it first.",
    ),
    _my_change(
        name="stop_my_server",
        path="/api/requester/infra/servers/{server_id}/stop",
        description="Prepare stopping one of the customer's servers. They confirm it first.",
    ),
)

TOOLS = (*CONSOLE_TOOLS, *CHAT_TOOLS)
