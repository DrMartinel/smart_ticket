"""Custom field types, the rules that gate a field's value, and the events a change fires."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

import regex


class FieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    USER = "user"
    CHECKBOX = "checkbox"
    URL = "url"


# Free text a person types: masked before it is stored (ADR-0028 decision 6).
FREE_TEXT_TYPES = frozenset({FieldType.TEXT, FieldType.TEXTAREA, FieldType.URL})


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def parse_date(value: Any) -> date | None:
    """Reads an ISO date or datetime string as a date."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def is_finite_number(value: Any) -> bool:
    """Whether `value` is a JSON number a float can hold: not a bool, NaN, infinite or huge."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def accepts(field_type: FieldType, value: Any, options: list[str]) -> bool:
    """Whether `value` is a well-formed value of `field_type`; None clears any field."""
    if value is None:
        return True
    match field_type:
        case FieldType.TEXT | FieldType.TEXTAREA | FieldType.URL | FieldType.USER:
            return isinstance(value, str)
        case FieldType.NUMBER:
            return is_finite_number(value)
        case FieldType.DATE:
            return parse_date(value) is not None
        case FieldType.SELECT:
            return isinstance(value, str) and value in options
        case FieldType.CHECKBOX:
            return isinstance(value, bool)


def coerce(field_type: FieldType, value: Any) -> Any:
    """Reads a templated string as a number or checkbox value; anything else is unchanged."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if field_type is FieldType.NUMBER:
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return value
    if field_type is FieldType.CHECKBOX and text.lower() in ("true", "false"):
        return text.lower() == "true"
    if text == "" and field_type is not FieldType.TEXT and field_type is not FieldType.TEXTAREA:
        return None
    return value


@dataclass(frozen=True)
class RuleContext:
    """What a rule may read besides the value."""

    today: date
    sla_due: date | None
    # Seconds a `pattern` rule may spend matching before it counts as broken.
    pattern_timeout: float


class RuleCode(StrEnum):
    REQUIRED = "required"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    PATTERN = "pattern"
    MIN = "min"
    MAX = "max"
    NOT_PAST = "not_past"
    BEFORE_SLA = "before_sla"
    ONE_OF = "one_of"
    MUST_BE_CHECKED = "must_be_checked"
    VALID_URL = "valid_url"


type RuleCheck = Callable[[Any, Mapping[str, Any], RuleContext], bool]


@dataclass(frozen=True)
class RuleSpec:
    """One rule in the catalog: what it checks, on which field types, with which parameters."""

    code: RuleCode
    name: str
    description: str
    err_message: str
    params: tuple[str, ...]
    numeric_params: tuple[str, ...]
    field_types: frozenset[FieldType]
    check: RuleCheck


_TEXTUAL = frozenset({FieldType.TEXT, FieldType.TEXTAREA, FieldType.URL})
_URL_SHAPE = re.compile(r"^https?://\S+$")


def _length(value: Any) -> int:
    return len(str(value))


RULES: dict[RuleCode, RuleSpec] = {
    spec.code: spec
    for spec in [
        RuleSpec(
            RuleCode.REQUIRED,
            "Required",
            "The field has a value.",
            "{field} is required",
            (),
            (),
            frozenset(FieldType),
            lambda v, p, c: not is_empty(v),
        ),
        RuleSpec(
            RuleCode.MIN_LENGTH,
            "Minimum length",
            "At least `min` characters, when set.",
            "{field} needs at least {min} characters",
            ("min",),
            ("min",),
            _TEXTUAL,
            lambda v, p, c: is_empty(v) or _length(v) >= float(p["min"]),
        ),
        RuleSpec(
            RuleCode.MAX_LENGTH,
            "Maximum length",
            "At most `max` characters.",
            "{field} takes at most {max} characters",
            ("max",),
            ("max",),
            _TEXTUAL,
            lambda v, p, c: is_empty(v) or _length(v) <= float(p["max"]),
        ),
        RuleSpec(
            RuleCode.PATTERN,
            "Pattern",
            "The whole value matches the regular expression `pattern`, when set.",
            "{field} has an invalid format",
            ("pattern",),
            (),
            _TEXTUAL,
            lambda v, p, c: (
                is_empty(v)
                or regex.fullmatch(str(p["pattern"]), str(v), timeout=c.pattern_timeout) is not None
            ),
        ),
        RuleSpec(
            RuleCode.MIN,
            "Minimum",
            "At least `min`, when set.",
            "{field} must be at least {min}",
            ("min",),
            ("min",),
            frozenset({FieldType.NUMBER}),
            lambda v, p, c: is_empty(v) or float(v) >= float(p["min"]),
        ),
        RuleSpec(
            RuleCode.MAX,
            "Maximum",
            "At most `max`, when set.",
            "{field} must be at most {max}",
            ("max",),
            ("max",),
            frozenset({FieldType.NUMBER}),
            lambda v, p, c: is_empty(v) or float(v) <= float(p["max"]),
        ),
        RuleSpec(
            RuleCode.NOT_PAST,
            "Not in the past",
            "Today or later, when set.",
            "{field} cannot be in the past",
            (),
            (),
            frozenset({FieldType.DATE}),
            lambda v, p, c: is_empty(v) or (parse_date(v) or c.today) >= c.today,
        ),
        RuleSpec(
            RuleCode.BEFORE_SLA,
            "Before the SLA",
            "On or before the ticket's SLA due date, when both are set.",
            "{field} must be on or before the SLA due date",
            (),
            (),
            frozenset({FieldType.DATE}),
            lambda v, p, c: (
                is_empty(v) or c.sla_due is None or (parse_date(v) or c.sla_due) <= c.sla_due
            ),
        ),
        RuleSpec(
            RuleCode.ONE_OF,
            "One of",
            "One of the comma-separated `values`, when set.",
            "{field} must be one of {values}",
            ("values",),
            (),
            frozenset({FieldType.TEXT, FieldType.SELECT, FieldType.USER}),
            lambda v, p, c: (
                is_empty(v) or str(v) in [s.strip() for s in str(p["values"]).split(",")]
            ),
        ),
        RuleSpec(
            RuleCode.MUST_BE_CHECKED,
            "Must be checked",
            "The box is ticked.",
            "{field} must be checked",
            (),
            (),
            frozenset({FieldType.CHECKBOX}),
            lambda v, p, c: v is True,
        ),
        RuleSpec(
            RuleCode.VALID_URL,
            "Valid URL",
            "An http or https URL, when set.",
            "{field} must be an http(s) URL",
            (),
            (),
            frozenset({FieldType.URL}),
            lambda v, p, c: is_empty(v) or _URL_SHAPE.match(str(v)) is not None,
        ),
    ]
}


def rule_param_errors(
    code: RuleCode, field_type: FieldType, params: Mapping[str, Any]
) -> list[str]:
    """Lists what is wrong with configuring rule `code` on a `field_type` field with `params`."""
    spec = RULES[code]
    errors = []
    if field_type not in spec.field_types:
        errors.append(f"rule {code.value!r} does not apply to {field_type.value} fields")
    for name in spec.params:
        if is_empty(params.get(name)):
            errors.append(f"rule {code.value!r} needs parameter {name!r}")
        elif name in spec.numeric_params:
            try:
                float(params[name])
            except (TypeError, ValueError):
                errors.append(f"rule {code.value!r} parameter {name!r} must be a number")
    if code is RuleCode.PATTERN and not is_empty(params.get("pattern")):
        try:
            regex.compile(str(params["pattern"]))
        except regex.error as e:
            errors.append(f"rule 'pattern' has an invalid regular expression: {e}")
    return errors


@dataclass(frozen=True)
class ConfiguredRule:
    """A rule as configured on a field or a transition, ready to evaluate."""

    rule_id: str
    code: RuleCode
    params: Mapping[str, Any]
    field_id: str
    field_name: str


@dataclass(frozen=True)
class RuleViolation:
    field_id: str
    field_name: str
    rule_id: str
    rule: str
    message: str


def violations(
    rules: list[ConfiguredRule], values: Mapping[str, Any], ctx: RuleContext
) -> list[RuleViolation]:
    """Every rule in `rules` that the field values in `values` (by field id) break."""
    found = []
    for rule in rules:
        spec = RULES[rule.code]
        try:
            ok = spec.check(values.get(rule.field_id), rule.params, ctx)
        except (TypeError, ValueError, KeyError, OverflowError, TimeoutError, regex.error):
            ok = False
        if not ok:
            message = spec.err_message.format_map(
                _Placeholders(field=rule.field_name, **{k: str(v) for k, v in rule.params.items()})
            )
            found.append(
                RuleViolation(
                    rule.field_id, rule.field_name, rule.rule_id, rule.code.value, message
                )
            )
    return found


class _Placeholders(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class EventCode(StrEnum):
    ON_CHANGE = "on_change"
    ON_SET = "on_set"
    ON_CLEAR = "on_clear"
    ON_EQUALS = "on_equals"


@dataclass(frozen=True)
class EventSpec:
    """One field event in the catalog: when a change fires it."""

    code: EventCode
    name: str
    description: str
    params: tuple[str, ...]
    fires: Callable[[Any, Any, Mapping[str, Any]], bool]


EVENTS: dict[EventCode, EventSpec] = {
    spec.code: spec
    for spec in [
        EventSpec(
            EventCode.ON_CHANGE,
            "On change",
            "The value changed.",
            (),
            lambda old, new, p: old != new,
        ),
        EventSpec(
            EventCode.ON_SET,
            "On set",
            "The field went from empty to a value.",
            (),
            lambda old, new, p: is_empty(old) and not is_empty(new),
        ),
        EventSpec(
            EventCode.ON_CLEAR,
            "On clear",
            "The field went from a value to empty.",
            (),
            lambda old, new, p: not is_empty(old) and is_empty(new),
        ),
        EventSpec(
            EventCode.ON_EQUALS,
            "On equals",
            "The value became `value`.",
            ("value",),
            lambda old, new, p: old != new and str(new) == str(p["value"]),
        ),
    ]
}


def event_param_errors(code: EventCode, params: Mapping[str, Any]) -> list[str]:
    """Lists what is wrong with configuring event `code` with `params`."""
    return [
        f"event {code.value!r} needs parameter {name!r}"
        for name in EVENTS[code].params
        if is_empty(params.get(name))
    ]
