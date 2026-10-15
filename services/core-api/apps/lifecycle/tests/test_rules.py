"""Field rules, field events and value checks: what each lets through and what it refuses."""

from datetime import date

import pytest

from apps.lifecycle.utils.rules import (
    EVENTS,
    RULES,
    ConfiguredRule,
    EventCode,
    FieldType,
    RuleCode,
    RuleContext,
    accepts,
    coerce,
    event_param_errors,
    rule_param_errors,
    violations,
)

CTX = RuleContext(today=date(2026, 10, 15), sla_due=date(2026, 10, 20), pattern_timeout=0.05)


def check(code: RuleCode, value, **params) -> bool:
    rule = ConfiguredRule("r1", code, params, "f1", "Resolution note")
    return not violations([rule], {"f1": value}, CTX)


@pytest.mark.parametrize("value", [None, "", []])
def test_an_empty_value_breaks_required(value):
    assert not check(RuleCode.REQUIRED, value)


@pytest.mark.parametrize(
    ("code", "params"),
    [
        (RuleCode.MIN_LENGTH, {"min": 5}),
        (RuleCode.MAX_LENGTH, {"max": 5}),
        (RuleCode.PATTERN, {"pattern": "[A-Z]+"}),
        (RuleCode.MIN, {"min": 1}),
        (RuleCode.MAX, {"max": 1}),
        (RuleCode.NOT_PAST, {}),
        (RuleCode.BEFORE_SLA, {}),
        (RuleCode.ONE_OF, {"values": "a,b"}),
        (RuleCode.VALID_URL, {}),
    ],
)
def test_an_empty_value_passes_every_rule_but_required(code, params):
    assert check(code, None, **params)
    assert check(code, "", **params)


def test_the_length_rules_count_characters():
    assert not check(RuleCode.MIN_LENGTH, "abcd", min=5)
    assert check(RuleCode.MIN_LENGTH, "abcde", min=5)
    assert not check(RuleCode.MAX_LENGTH, "abcdef", max="5")


def test_a_pattern_must_match_the_whole_value():
    assert not check(RuleCode.PATTERN, "ABC1", pattern="[A-Z]+")
    assert check(RuleCode.PATTERN, "ABC", pattern="[A-Z]+")


def test_dates_are_checked_against_today_and_the_sla():
    assert not check(RuleCode.NOT_PAST, "2026-10-14")
    assert check(RuleCode.NOT_PAST, "2026-10-15")
    assert not check(RuleCode.BEFORE_SLA, "2026-10-21")
    assert check(RuleCode.BEFORE_SLA, "2026-10-20T09:00:00")


def test_must_be_checked_refuses_anything_but_true():
    assert not check(RuleCode.MUST_BE_CHECKED, False)
    assert not check(RuleCode.MUST_BE_CHECKED, "true")
    assert check(RuleCode.MUST_BE_CHECKED, True)


def test_a_rule_that_raises_counts_as_broken():
    """A broken parameter must not let a value through."""

    assert not check(RuleCode.MIN, 3, min="not a number")


def test_a_violation_message_names_the_field_and_parameter():
    rule = ConfiguredRule("r1", RuleCode.MIN_LENGTH, {"min": 5}, "f1", "Resolution note")

    [violation] = violations([rule], {"f1": "abc"}, CTX)

    assert violation.message == "Resolution note needs at least 5 characters"


def test_every_violation_is_reported_not_just_the_first():
    rules = [
        ConfiguredRule("r1", RuleCode.REQUIRED, {}, "f1", "A"),
        ConfiguredRule("r2", RuleCode.REQUIRED, {}, "f2", "B"),
    ]

    assert len(violations(rules, {}, CTX)) == 2


def test_a_rule_on_the_wrong_field_type_is_refused_as_config():
    assert rule_param_errors(RuleCode.MIN, FieldType.TEXT, {"min": 1})


def test_a_missing_or_non_numeric_parameter_is_refused_as_config():
    assert rule_param_errors(RuleCode.MIN_LENGTH, FieldType.TEXT, {})
    assert rule_param_errors(RuleCode.MIN_LENGTH, FieldType.TEXT, {"min": "five"})
    assert not rule_param_errors(RuleCode.MIN_LENGTH, FieldType.TEXT, {"min": "5"})


def test_an_invalid_regular_expression_is_refused_as_config():
    assert rule_param_errors(RuleCode.PATTERN, FieldType.TEXT, {"pattern": "("})


@pytest.mark.parametrize(
    ("field_type", "good", "bad"),
    [
        (FieldType.TEXT, "x", 1),
        (FieldType.NUMBER, 1.5, True),
        (FieldType.DATE, "2026-10-15", "15/10/2026"),
        (FieldType.SELECT, "a", "z"),
        (FieldType.CHECKBOX, False, "false"),
    ],
)
def test_a_value_of_the_wrong_shape_is_not_accepted(field_type, good, bad):
    assert accepts(field_type, good, ["a", "b"])
    assert not accepts(field_type, bad, ["a", "b"])


def test_none_clears_any_field():
    assert all(accepts(t, None, []) for t in FieldType)


def test_templated_text_is_read_as_the_fields_type():
    assert coerce(FieldType.NUMBER, "3") == 3
    assert coerce(FieldType.NUMBER, "2.5") == 2.5
    assert coerce(FieldType.CHECKBOX, "TRUE") is True
    assert coerce(FieldType.DATE, "") is None
    assert coerce(FieldType.TEXT, "") == ""


@pytest.mark.parametrize(
    ("code", "old", "new", "params", "fires"),
    [
        (EventCode.ON_CHANGE, "a", "a", {}, False),
        (EventCode.ON_CHANGE, "a", "b", {}, True),
        (EventCode.ON_SET, None, "b", {}, True),
        (EventCode.ON_SET, "a", "b", {}, False),
        (EventCode.ON_CLEAR, "a", "", {}, True),
        (EventCode.ON_CLEAR, None, "", {}, False),
        (EventCode.ON_EQUALS, "a", "done", {"value": "done"}, True),
        (EventCode.ON_EQUALS, "done", "done", {"value": "done"}, False),
    ],
)
def test_an_event_fires_only_on_its_change(code, old, new, params, fires):
    assert EVENTS[code].fires(old, new, params) is fires


def test_on_equals_needs_its_value():
    assert event_param_errors(EventCode.ON_EQUALS, {})


def test_every_rule_code_is_in_the_catalog():
    assert set(RULES) == set(RuleCode)
    assert set(EVENTS) == set(EventCode)
