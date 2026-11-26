"""Raw PromQL, checked on the syntax tree Prometheus's `parse_query` answers and written back
out from that tree with the caller's projects on every selector (F17 FR-F17-005, BR-F17-05,
ADR-0048 §4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import re2

from apps.infra.domain.catalog import PROJECT_LABEL, PROMQL_AGGREGATIONS, PROMQL_FUNCTIONS
from apps.infra.domain.queries import Window, matcher, promql_string
from apps.infra.domain.vocabulary import QueryCheck, QueryRefused

if TYPE_CHECKING:
    from config.settings.base import InfraThresholds

Node = dict[str, Any]

LABEL_NAME = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
METRIC_NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
NUMBER = re.compile(r"-?\d+(\.\d+)?|[+-]Inf|NaN")
BINARY_OPS = frozenset(
    {"+", "-", "*", "/", "%", "^", "atan2", "==", "!=", ">", "<", ">=", "<=", "and", "or", "unless"}
)
# Label values of every shape; a regex matcher accepting all of them matches everything.
SAMPLES = ("a", "db-01", "Zz 9.:/_é\n")
# How a matcher's regex is read: RE2, the engine and syntax Prometheus uses, in linear time.
RE2_OPTIONS = re2.Options()
RE2_OPTIONS.log_errors = False
# The keys `parse_query` gives each node, matcher and vector matching core-api knows.
SELECTOR_KEYS = frozenset({"type", "name", "offset", "matchers", "timestamp", "startOrEnd"})
NODE_KEYS = {
    "vectorSelector": SELECTOR_KEYS,
    "matrixSelector": SELECTOR_KEYS | {"range"},
    "subquery": frozenset({"type", "expr", "range", "offset", "step", "timestamp", "startOrEnd"}),
    "call": frozenset({"type", "func", "args"}),
    "aggregation": frozenset({"type", "op", "expr", "param", "grouping", "without"}),
    "binaryExpr": frozenset({"type", "op", "lhs", "rhs", "matching", "bool"}),
    "unaryExpr": frozenset({"type", "op", "expr"}),
    "parenExpr": frozenset({"type", "expr"}),
    "numberLiteral": frozenset({"type", "val"}),
    "stringLiteral": frozenset({"type", "val"}),
}
MATCHER_KEYS = frozenset({"name", "type", "value"})
MATCHING_KEYS = frozenset({"card", "labels", "on", "include"})
# Prometheus durations, largest first.
UNITS = (
    ("y", 365 * 24 * 3600 * 1000),
    ("w", 7 * 24 * 3600 * 1000),
    ("d", 24 * 3600 * 1000),
    ("h", 3600 * 1000),
    ("m", 60 * 1000),
    ("s", 1000),
    ("ms", 1),
)


def duration(ms: int) -> str:
    """`ms` milliseconds as a PromQL duration."""
    if not isinstance(ms, int):
        raise TypeError(f"a duration of {ms!r}")
    if ms < 0:
        return "-" + duration(-ms)
    parts = []
    for unit, size in UNITS:
        count, ms = divmod(ms, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts) or "0s"


def text(value: Any) -> str:
    """`value`, which a parsed string must be."""
    if not isinstance(value, str):
        raise TypeError(f"a string of {value!r}")
    return value


def matches_everything(kind: str, value: str) -> bool:
    """Whether a matcher accepts every value a label has: `!=""`, a regex accepting every sample,
    or a negative regex excluding the empty string and no sample."""
    if kind == "=":
        return False
    if kind == "!=":
        return value == ""
    try:
        pattern = re2.compile(f"(?s:{value})", RE2_OPTIONS)
    except re2.error as e:
        raise QueryRefused(
            QueryCheck.UNSUPPORTED, f"core-api can't read the regular expression {value!r}"
        ) from e
    if kind == "=~":
        return all(pattern.fullmatch(sample) for sample in SAMPLES)
    return bool(pattern.fullmatch("")) and not any(pattern.fullmatch(s) for s in SAMPLES)


class ScopedPromQL:
    """Writes a parsed expression back out as PromQL, refusing what the checks don't allow and
    adding the scope matcher to every selector."""

    def __init__(self, caps: InfraThresholds, scope: str) -> None:
        self.caps = caps
        self.scope = scope
        self.selectors = 0

    def expr(self, node: Node) -> str:
        """`node` as PromQL."""
        if node["type"] in NODE_KEYS:
            self.expect(node, NODE_KEYS[node["type"]], f"a {node['type']}")
        match node["type"]:
            case "vectorSelector":
                return self.selector(node) + self.modifiers(node)
            case "matrixSelector":
                return f"{self.selector(node)}[{self.range(node['range'])}]{self.modifiers(node)}"
            case "subquery":
                return self.subquery(node)
            case "call":
                return self.call(node)
            case "aggregation":
                return self.aggregation(node)
            case "binaryExpr":
                return self.binary(node)
            case "unaryExpr":
                if node["op"] not in ("-", "+"):
                    raise self.unsupported(f"the unary operator {node['op']!r}")
                return f"{node['op']}({self.expr(node['expr'])})"
            case "parenExpr":
                return f"({self.expr(node['expr'])})"
            case "numberLiteral":
                if not isinstance(node["val"], str) or not NUMBER.fullmatch(node["val"]):
                    raise ValueError(f"a number literal of {node['val']!r}")
                return node["val"]
            case "stringLiteral":
                return promql_string(text(node["val"]))
            case other:
                raise self.unsupported(f"a {other!r} expression")

    def selector(self, node: Node) -> str:
        """A selector's name and matchers, with the scope matcher last; refuses a matcher on the
        project, one that matches everything, or one too many selectors."""
        self.selectors += 1
        if self.selectors > self.caps.max_selectors:
            raise QueryRefused(
                QueryCheck.SELECTORS,
                f"more than {self.caps.max_selectors} selectors; split the query",
            )
        name = node["name"]
        if name and not METRIC_NAME.fullmatch(name):
            raise self.unsupported(f"the metric name {name!r}")
        matchers = []
        for found in node["matchers"]:
            self.expect(found, MATCHER_KEYS, "a matcher")
            label, kind, value = found["name"], found["type"], found["value"]
            if name and (label, kind, value) == ("__name__", "=", name):
                continue
            if label == PROJECT_LABEL:
                raise QueryRefused(
                    QueryCheck.FIELD, "core-api sets the project; narrow with project_id"
                )
            if kind not in ("=", "!=", "=~", "!~"):
                raise self.unsupported(f"the matcher type {kind!r}")
            value = text(value)
            if matches_everything(kind, value):
                raise QueryRefused(
                    QueryCheck.MATCH_ALL,
                    f"{label}{kind}{promql_string(value)} matches every value; name the ones "
                    "you want",
                )
            matchers.append(f"{self.label(label)}{kind}{promql_string(value)}")
        return f"{name}{{{','.join([*matchers, self.scope])}}}"

    def range(self, ms: int) -> str:
        """A range selector's or subquery's range; refuses one over the cap."""
        if ms > self.caps.max_range_hours * 3600 * 1000:
            raise QueryRefused(
                QueryCheck.RANGE, f"a range is over {self.caps.max_range_hours} hours; narrow it"
            )
        return duration(ms)

    def subquery(self, node: Node) -> str:
        """A subquery; refuses one with no step or a step under the floor."""
        step = node["step"]
        if step < self.caps.min_step_seconds * 1000:
            raise QueryRefused(
                QueryCheck.STEP,
                f"a subquery needs a step of at least {self.caps.min_step_seconds} s",
            )
        inner = self.expr(node["expr"])
        return f"({inner})[{self.range(node['range'])}:{duration(step)}]{self.modifiers(node)}"

    def modifiers(self, node: Node) -> str:
        """A selector's or subquery's `offset` and `@`."""
        written = f" offset {duration(node['offset'])}" if node["offset"] else ""
        at, timestamp = node["startOrEnd"], node["timestamp"]
        if at is not None:
            if at not in ("start", "end"):
                raise self.unsupported(f"@ {at}")
            written += f" @ {at}()"
        elif timestamp is not None:
            if not isinstance(timestamp, int):
                raise TypeError(f"a timestamp of {timestamp!r}")
            written += f" @ {timestamp / 1000:.3f}"
        return written

    def call(self, node: Node) -> str:
        """A function call; refuses a function not allowlisted."""
        name = node["func"]["name"]
        if name not in PROMQL_FUNCTIONS:
            raise QueryRefused(
                QueryCheck.FUNCTION, f"{name!r} isn't allowed in raw PromQL; see the catalog"
            )
        return f"{name}({', '.join(self.expr(arg) for arg in node['args'])})"

    def aggregation(self, node: Node) -> str:
        """An aggregation; refuses an operator not allowlisted."""
        op = node["op"]
        if op not in PROMQL_AGGREGATIONS:
            raise QueryRefused(
                QueryCheck.FUNCTION, f"{op!r} isn't allowed in raw PromQL; see the catalog"
            )
        labels = self.labels(node["grouping"])
        args = self.expr(node["expr"])
        if node["param"] is not None:
            args = f"{self.expr(node['param'])}, {args}"
        if node["without"]:
            return f"{op} without ({labels}) ({args})"
        return f"{op} by ({labels}) ({args})" if labels else f"{op}({args})"

    def binary(self, node: Node) -> str:
        """A binary operation, with its `bool` and vector matching."""
        op = node["op"]
        if op not in BINARY_OPS:
            raise self.unsupported(f"the operator {op!r}")
        written = [self.operand(node["lhs"]), op]
        if node["bool"]:
            written.append("bool")
        matching = node["matching"]
        if matching is not None:
            self.expect(matching, MATCHING_KEYS, "a vector matching")
            labels = self.labels(matching["labels"])
            card = matching["card"]
            if matching["on"]:
                written.append(f"on ({labels})")
            elif labels or card in ("many-to-one", "one-to-many"):
                written.append(f"ignoring ({labels})")
            if card == "many-to-one":
                written.append(f"group_left ({self.labels(matching['include'])})")
            elif card == "one-to-many":
                written.append(f"group_right ({self.labels(matching['include'])})")
            elif card not in ("one-to-one", "many-to-many"):
                raise self.unsupported(f"the matching {card!r}")
        written.append(self.operand(node["rhs"]))
        return " ".join(written)

    def operand(self, node: Node) -> str:
        """A binary operand, in parentheses when it is itself a binary operation."""
        written = self.expr(node)
        return f"({written})" if node["type"] == "binaryExpr" else written

    def labels(self, names: list[str]) -> str:
        return ", ".join(self.label(name) for name in names)

    def label(self, name: str) -> str:
        """`name` if PromQL can carry it unquoted; refuses any other."""
        if not isinstance(name, str) or not LABEL_NAME.fullmatch(name):
            raise self.unsupported(f"the label name {name!r}")
        return name

    def expect(self, found: Node, keys: frozenset[str], what: str) -> None:
        """Refuses `found` if it holds a key besides `keys`."""
        if extra := set(found) - keys:
            raise self.unsupported(f"{', '.join(sorted(map(str, extra)))} on {what}")

    @staticmethod
    def unsupported(what: str) -> QueryRefused:
        return QueryRefused(
            QueryCheck.UNSUPPORTED, f"core-api can't check {what}; rewrite the query without it"
        )


@dataclass(frozen=True)
class PromQLQuery:
    """A PromQL expression as its author wrote it, over a range at a step."""

    text: str
    window: Window
    step_seconds: int

    def check(self, caps: InfraThresholds) -> None:
        """Refuses a range or step over the caps, before the text is parsed."""
        self.window.check(caps)
        if self.step_seconds < caps.min_step_seconds:
            raise QueryRefused(QueryCheck.STEP, f"the step is under {caps.min_step_seconds} s")

    def scoped(self, tree: Node, caps: InfraThresholds, projects: frozenset[str]) -> str:
        """The PromQL `tree` writes back out to, scoped to `projects`; refuses what FR-F17-005
        refuses and anything core-api can't check."""
        if not projects:
            raise ValueError("a PromQL query needs at least one project")
        return ScopedPromQL(caps, matcher(PROJECT_LABEL, sorted(projects))).expr(tree)

    def link(self, base: str, promql: str) -> str:
        """The query in Prometheus's own graph page."""
        return self.window.graph_link(base, promql, self.step_seconds)
