"""Fields every audit row written inside a block carries, such as the agent a request acts for
(BR-F15-15)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

_EMPTY: MappingProxyType[str, Any] = MappingProxyType({})
_fields: ContextVar[MappingProxyType[str, Any]] = ContextVar("audit_fields", default=_EMPTY)


@contextmanager
def audit_context(fields: dict[str, Any]) -> Iterator[None]:
    """Adds `fields` to the payload of every audit row written inside the block."""
    token = _fields.set(MappingProxyType({**_fields.get(), **fields}))
    try:
        yield
    finally:
        _fields.reset(token)


def context_fields() -> dict[str, Any]:
    return dict(_fields.get())
