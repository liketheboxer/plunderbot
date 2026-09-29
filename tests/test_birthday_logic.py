from datetime import date, datetime
from zoneinfo import ZoneInfo

from plunderbot.birthday_logic import (due_to_announce, is_birthday_on, next_occurrence, upcoming,
                                       valid_date, valid_timezone, zone)


def test_valid_dates():
    assert valid_date(2, 29)
    assert valid_date(12, 31)
    assert not valid_date(2, 30)
    assert not valid_date(4, 31)
    assert not valid_date(13, 1)
    assert not valid_date(1, 0)


def test_leap_day_birthdays_move_to_feb_28_in_common_years():
    assert is_birthday_on(2, 29, date(2027, 2, 28))
    assert not is_birthday_on(2, 29, date(2028, 2, 28))
    assert is_birthday_on(2, 29, date(2028, 2, 29))
    assert is_birthday_on(7, 4, date(2026, 7, 4))
    assert not is_birthday_on(7, 4, date(2026, 7, 5))


def test_next_occurrence_wraps_to_next_year():
    today = date(2026, 12, 30)
    assert next_occurrence(12, 30, today) == date(2026, 12, 30)
    assert next_occurrence(1, 2, today) == date(2027, 1, 2)
    assert next_occurrence(2, 29, date(2026, 3, 1)) == date(2027, 2, 28)
    assert next_occurrence(2, 29, date(2027, 3, 1)) == date(2028, 2, 29)


def test_upcoming_sorts_soonest_first_and_limits():
    today = date(2026, 9, 29)
    entries = [(1, 1, 5), (2, 9, 29), (3, 10, 1), (4, 9, 28)]
    result = upcoming(entries, today, limit=3)
    assert [uid for uid, _ in result] == [2, 3, 1]
    assert result[0][1] == today


def test_due_to_announce_at_or_after_the_hour_once_per_day():
    tz = ZoneInfo("America/Los_Angeles")
    before = datetime(2026, 9, 29, 8, 59, tzinfo=tz)
    at = datetime(2026, 9, 29, 9, 0, tzinfo=tz)
    late = datetime(2026, 9, 29, 22, 0, tzinfo=tz)
    assert not due_to_announce(before, 9, None)
    assert due_to_announce(at, 9, None)
    assert due_to_announce(late, 9, "2026-09-28")
    assert not due_to_announce(late, 9, "2026-09-29")


def test_timezones():
    assert valid_timezone("America/Los_Angeles")
    assert not valid_timezone("Mars/Olympus_Mons")
    assert str(zone(None, "America/New_York")) == "America/New_York"
    assert str(zone("Nope/Nope", "Also/Nope")) == "UTC"


def test_moving_the_time_zone_west_never_repeats_a_toast():
    tz = ZoneInfo("America/Los_Angeles")
    # Last toast was for Sep 30 (sent while the server was on UTC); local date is now Sep 29 again.
    assert not due_to_announce(datetime(2026, 9, 29, 20, 0, tzinfo=tz), 0, "2026-09-30")
    assert not due_to_announce(datetime(2026, 9, 30, 20, 0, tzinfo=tz), 0, "2026-09-30")
    assert due_to_announce(datetime(2026, 10, 1, 0, 5, tzinfo=tz), 0, "2026-09-30")


def test_birthday_change_limit():
    from datetime import timedelta, timezone as tzmod

    from plunderbot.birthday_logic import change_allowed
    t0 = datetime(2026, 9, 1, 12, 0, tzinfo=tzmod.utc)
    assert change_allowed(None, t0) == (True, True, None)
    assert change_allowed(t0, t0 + timedelta(minutes=30)) == (True, False, None)  # typo fix
    allowed, _, until = change_allowed(t0, t0 + timedelta(days=2))
    assert not allowed and until == t0 + timedelta(days=30)
    assert change_allowed(t0, t0 + timedelta(days=30)) == (True, True, None)
