"""Business time on a calendar: working intervals per weekday, whole-day holidays, an IANA zone.
Pure: no database, no clock (ADR-0030 §4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# How far a walk looks for working time before it gives up on a calendar.
_MAX_DAYS = 3700


class CalendarError(ValueError):
    """The calendar can't count business time: no working hours, or a bad interval."""


def parse_hours(
    working_hours: Mapping[str, Iterable[Iterable[str]]],
) -> dict[int, list[tuple[int, int]]]:
    """`{"mon": [["08:00","17:30"]], …}` as minutes from midnight per weekday (0 = Monday);
    raises CalendarError for an interval that is malformed, empty or overlapping."""
    parsed: dict[int, list[tuple[int, int]]] = {}
    unknown = set(working_hours) - set(WEEKDAYS)
    if unknown:
        raise CalendarError(f"unknown weekday {sorted(unknown)[0]!r}")
    for index, day in enumerate(WEEKDAYS):
        spans = []
        for span in working_hours.get(day, []):
            start, end = list(span)
            spans.append((_minutes(start), _minutes(end)))
        spans.sort()
        for (s1, e1), (s2, _) in zip(spans, spans[1:]):
            if s2 < e1:
                raise CalendarError(f"{day}: intervals overlap")
        for s, e in spans:
            if e <= s:
                raise CalendarError(f"{day}: {s // 60:02d}:{s % 60:02d} is not before the end")
        parsed[index] = spans
    if not any(parsed.values()):
        raise CalendarError("the calendar has no working hours")
    return parsed


def _minutes(text: str) -> int:
    try:
        hours, minutes = text.split(":")
        value = int(hours) * 60 + int(minutes)
    except ValueError as e:
        raise CalendarError(f"{text!r} is not HH:MM") from e
    if not 0 <= value <= 24 * 60 or not 0 <= int(minutes) < 60:
        raise CalendarError(f"{text!r} is not a time of day")
    return value


@dataclass(frozen=True)
class BusinessCalendar:
    """When the clock runs. A 24×7 calendar counts every second."""

    zone: ZoneInfo
    hours: Mapping[int, list[tuple[int, int]]]
    holidays: frozenset[date]
    is_24x7: bool = False

    def spans(self, day: date) -> list[tuple[datetime, datetime]]:
        """The working intervals of one local day, as aware datetimes."""
        if day in self.holidays:
            return []
        out = []
        for start, end in self.hours.get(day.weekday(), []):
            begin = datetime.combine(day, time(0), self.zone) + timedelta(minutes=start)
            out.append((begin, datetime.combine(day, time(0), self.zone) + timedelta(minutes=end)))
        return out

    def elapsed(self, start: datetime, end: datetime) -> int:
        """Business seconds between `start` and `end` (0 when `end` is not after `start`)."""
        if end <= start:
            return 0
        if self.is_24x7:
            return int((end - start).total_seconds())
        total = 0.0
        day = start.astimezone(self.zone).date()
        last = end.astimezone(self.zone).date()
        while day <= last:
            for begin, finish in self.spans(day):
                overlap = min(finish, end) - max(begin, start)
                if overlap > timedelta(0):
                    total += overlap.total_seconds()
            day += timedelta(days=1)
        return int(total)

    def whole_days(self, start: datetime, end: datetime) -> int:
        """Working days after `start`'s day whose working hours were over by `end`."""
        count = 0
        day = start.astimezone(self.zone).date() + timedelta(days=1)
        last = end.astimezone(self.zone).date()
        while day <= last:
            if self.is_24x7:
                count += day < last
            else:
                spans = self.spans(day)
                count += bool(spans) and end >= spans[-1][1]
            day += timedelta(days=1)
        return count

    def add(self, start: datetime, seconds: float) -> datetime:
        """The moment `seconds` of business time after `start`."""
        if seconds <= 0:
            return start
        if self.is_24x7:
            return start + timedelta(seconds=seconds)
        remaining = timedelta(seconds=seconds)
        day = start.astimezone(self.zone).date()
        for _ in range(_MAX_DAYS):
            for begin, finish in self.spans(day):
                begin = max(begin, start)
                if finish <= begin:
                    continue
                if finish - begin >= remaining:
                    return begin + remaining
                remaining -= finish - begin
            day += timedelta(days=1)
        raise CalendarError("no working time within ten years")
