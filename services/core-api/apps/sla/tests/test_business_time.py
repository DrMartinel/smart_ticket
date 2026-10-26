"""Business time on the VN office calendar: F1 §g's worked example and AC-F1-02."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from apps.sla.utils.business_time import BusinessCalendar, CalendarError, parse_hours

VN = ZoneInfo("Asia/Ho_Chi_Minh")
OFFICE = {d: [["08:00", "17:30"]] for d in ("mon", "tue", "wed", "thu", "fri")}


def office(*holidays: date) -> BusinessCalendar:
    return BusinessCalendar(VN, parse_hours(OFFICE), frozenset(holidays))


def vn(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=VN)


def test_business_time_skips_weekend_and_holiday():
    """§g: Fri 23 Oct 15:30 + 240 business minutes is Mon 10:00; + 1,710 is Wed 15:30."""
    start = vn(2026, 10, 23, 15, 30)

    assert office().add(start, 240 * 60) == vn(2026, 10, 26, 10, 0)
    assert office().add(start, 1710 * 60) == vn(2026, 10, 28, 15, 30)
    assert office().add(start, 0.75 * 1710 * 60) == vn(2026, 10, 28, 8, 22, 30)


def test_a_holiday_does_not_count():
    """AC-F1-02: Mon 23 Nov 16:30 + 240 min skips Tue 24 Nov, due Wed 25 Nov 11:00."""
    calendar = office(date(2026, 11, 24))

    assert calendar.add(vn(2026, 11, 23, 16, 30), 240 * 60) == vn(2026, 11, 25, 11, 0)


def test_elapsed_counts_working_minutes_only():
    """§g step 4: Fri 15:30 to Tue 10:00 is 120 + 570 + 120 = 810 minutes."""
    assert office().elapsed(vn(2026, 10, 23, 15, 30), vn(2026, 10, 27, 10, 0)) == 810 * 60


def test_24x7_counts_every_second():
    """AC-F1-05: Sat 22:00 + 240 minutes is Sun 02:00."""
    calendar = BusinessCalendar(VN, parse_hours(OFFICE), frozenset(), is_24x7=True)

    assert calendar.add(vn(2026, 10, 24, 22, 0), 240 * 60) == vn(2026, 10, 25, 2, 0)


def test_dst_free_zone_round_trip_utc():
    """A due time computed in +07 and stored in UTC is the same instant."""
    due = office().add(datetime(2026, 10, 23, 8, 30, tzinfo=UTC), 1710 * 60)

    assert due.astimezone(UTC) == datetime(2026, 10, 28, 8, 30, tzinfo=UTC)


def test_starting_outside_hours_starts_at_the_next_opening():
    assert office().add(vn(2026, 10, 24, 12, 0), 60) == vn(2026, 10, 26, 8, 1)


@pytest.mark.parametrize(
    "hours",
    [
        {"mon": [["17:30", "08:00"]]},
        {"mon": [["08:00", "12:00"], ["11:00", "13:00"]]},
        {"funday": [["08:00", "09:00"]]},
        {"mon": [["8am", "5pm"]]},
        {},
    ],
)
def test_a_bad_calendar_is_refused(hours):
    with pytest.raises(CalendarError):
        parse_hours(hours)
