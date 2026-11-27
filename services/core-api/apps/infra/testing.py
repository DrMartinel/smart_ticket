"""Test helpers for raw PromQL: syntax trees as Prometheus's parse_query answers them."""

from __future__ import annotations

from typing import Any

MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000

Node = dict[str, Any]


def m(name: str, kind: str, value: str) -> Node:
    return {"name": name, "type": kind, "value": value}


def vs(
    name: str = "",
    *matchers: Node,
    offset: int = 0,
    timestamp: int | None = None,
    at: str | None = None,
) -> Node:
    """A vector selector; Prometheus lists the name as a `__name__` matcher too."""
    named = [m("__name__", "=", name)] if name else []
    return {
        "type": "vectorSelector",
        "name": name,
        "offset": offset,
        "matchers": [*matchers, *named],
        "timestamp": timestamp,
        "startOrEnd": at,
    }


def ranged(selector: Node, ms: int) -> Node:
    return {**selector, "type": "matrixSelector", "range": ms}


def call(name: str, *args: Node) -> Node:
    func = {"name": name, "argTypes": ["matrix"], "variadic": 0, "returnType": "vector"}
    return {"type": "call", "func": func, "args": list(args)}


def agg(
    op: str,
    expr: Node,
    *,
    by: tuple[str, ...] = (),
    without: bool = False,
    param: Node | None = None,
) -> Node:
    return {
        "type": "aggregation",
        "op": op,
        "expr": expr,
        "param": param,
        "grouping": list(by),
        "without": without,
    }


def binary(
    op: str,
    lhs: Node,
    rhs: Node,
    *,
    card: str = "one-to-one",
    on: bool = False,
    labels: tuple[str, ...] = (),
    include: tuple[str, ...] = (),
    returns_bool: bool = False,
) -> Node:
    matching = {"card": card, "labels": list(labels), "on": on, "include": list(include)}
    return {
        "type": "binaryExpr",
        "op": op,
        "lhs": lhs,
        "rhs": rhs,
        "matching": matching,
        "bool": returns_bool,
    }


def subquery(expr: Node, ms: int, step: int, offset: int = 0) -> Node:
    return {
        "type": "subquery",
        "expr": expr,
        "range": ms,
        "offset": offset,
        "step": step,
        "timestamp": None,
        "startOrEnd": None,
    }


def num(value: str) -> Node:
    return {"type": "numberLiteral", "val": value}


def string(value: str) -> Node:
    return {"type": "stringLiteral", "val": value}


def paren(expr: Node) -> Node:
    return {"type": "parenExpr", "expr": expr}


def unary(op: str, expr: Node) -> Node:
    return {"type": "unaryExpr", "op": op, "expr": expr}
