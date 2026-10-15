"""Fills `{{path}}` placeholders in action parameters from a flat variable map. Pure."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

# The variables an action's parameters can name, for the catalog.
VARIABLES: dict[str, str] = {
    "ticket.id": "The ticket's public id (TKT-…)",
    "ticket.subject": "The masked subject",
    "ticket.body": "The masked body",
    "ticket.status": "The current status key",
    "ticket.statusName": "The current status name",
    "ticket.baseStatus": "The current system status name",
    "ticket.workflow": "The workflow name",
    "ticket.category": "The category the router chose, if any",
    "ticket.assignedTeam": "The assigned team",
    "ticket.assignee": "The assignee's username",
    "ticket.reporter": "The reporter's username",
    "ticket.reporterEmail": "The reporter's email",
    "ticket.piiLevel": "The ticket's PII level",
    "ticket.source": "form or chat",
    "ticket.slaDueAt": "The SLA due time, ISO 8601",
    "ticket.createdAt": "When the ticket was submitted, ISO 8601",
    "transfer.id": "The transfer's id",
    "transfer.trigger": "manual, action, force, …",
    "transfer.direction": "forward or reverse",
    "transfer.by": "Who moved the ticket, or 'system'",
    "transfer.beforeStatus": "The status name moved from",
    "transfer.beforeStatusKey": "The status key moved from",
    "transfer.afterStatus": "The status name moved to",
    "transfer.afterStatusKey": "The status key moved to",
    "field.<name>": "A custom field's value",
    "now": "The current time, ISO 8601",
    "today": "Today's date, ISO 8601",
}


def has_placeholder(value: Any) -> bool:
    return isinstance(value, str) and _PLACEHOLDER.search(value) is not None


def render_json(text: Any, variables: Mapping[str, str], unknown: list[str]) -> Any:
    """Fills placeholders inside the string values of a JSON template, so a value can never add
    keys or break the document; raises ValueError when `text` is not JSON."""
    if not isinstance(text, str) or not text.strip():
        return text
    return json.dumps(render(json.loads(text), variables, unknown), ensure_ascii=False)


def json_template_errors(text: Any) -> list[str]:
    """What is wrong with `text` as a JSON template: placeholders belong inside string values."""
    if not isinstance(text, str) or not text.strip():
        return []
    try:
        json.loads(text)
    except ValueError as e:
        return [f"not JSON (placeholders go inside quoted strings): {e}"]
    return []


def placeholders(value: Any) -> list[str]:
    """Every placeholder path named anywhere inside `value`."""
    if isinstance(value, str):
        return _PLACEHOLDER.findall(value)
    if isinstance(value, dict):
        return [p for v in value.values() for p in placeholders(v)]
    if isinstance(value, list):
        return [p for v in value for p in placeholders(v)]
    return []


def render(value: Any, variables: Mapping[str, str], unknown: list[str]) -> Any:
    """Fills the placeholders in every string inside `value`; appends unknown paths to `unknown`."""
    if isinstance(value, str):

        def fill(match: re.Match[str]) -> str:
            path = match.group(1)
            if path not in variables:
                unknown.append(path)
                return ""
            return variables[path]

        return _PLACEHOLDER.sub(fill, value)
    if isinstance(value, dict):
        return {k: render(v, variables, unknown) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables, unknown) for v in value]
    return value
