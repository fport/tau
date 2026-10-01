"""Trigger parsing, wording and the slot arithmetic the engine relies on."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from routine_helpers import ZONE, local
from tau_core.routines import Daily, Every, Once, TriggerError, parse_trigger
from tau_core.routines.triggers import ALL_DAYS, WEEKDAYS, WEEKENDS

ANCHOR = local(2026, 10, 1, 6, 0)


@pytest.mark.parametrize(
    ("text", "parsed", "canonical"),
    [
        ("daily 07:00", Daily(time(7, 0)), "daily 07:00"),
        ("DAILY 7:05 every day", Daily(time(7, 5)), "daily 07:05"),
        ("daily 07:00 weekdays", Daily(time(7, 0), WEEKDAYS), "daily 07:00 weekdays"),
        ("daily 07:00 on mon-fri", Daily(time(7, 0), WEEKDAYS), "daily 07:00 weekdays"),
        ("daily 09:30 weekends", Daily(time(9, 30), WEEKENDS), "daily 09:30 weekends"),
        (
            "daily 18:00 Monday, wed fri",
            Daily(time(18, 0), frozenset({0, 2, 4})),
            "daily 18:00 mon,wed,fri",
        ),
        ("daily 23:59 sun", Daily(time(23, 59), frozenset({6})), "daily 23:59 sun"),
        ("once 2026-10-05 07:00", Once(datetime(2026, 10, 5, 7, 0)), "once 2026-10-05 07:00"),
        ("once 2026-10-05T07:00", Once(datetime(2026, 10, 5, 7, 0)), "once 2026-10-05 07:00"),
        ("every 15 minutes", Every(15), "every 15 minutes"),
        ("every 5 min", Every(5), "every 5 minutes"),
        ("every 60m", Every(60), "every 60 minutes"),
    ],
)
def test_parse_and_canonical_text(text: str, parsed, canonical: str) -> None:
    assert parse_trigger(text) == parsed
    assert parsed.text == canonical
    assert parse_trigger(canonical) == parsed


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("", "empty"),
        ("hourly", "not a trigger"),
        ("daily", "needs a time"),
        ("daily 24:00", "HH:MM"),
        ("daily 7", "HH:MM"),
        ("daily 07:00 funday", "not a day"),
        ("daily 07:00 fri-mon", "backwards"),
        ("once 2026-13-01 07:00", "YYYY-MM-DD"),
        ("once tomorrow", "YYYY-MM-DD"),
        ("every 4 minutes", "5 to 10080"),
        ("every 10081 minutes", "5 to 10080"),
        ("every hour", "number of minutes"),
    ],
)
def test_bad_triggers_say_what_was_expected(text: str, complaint: str) -> None:
    with pytest.raises(TriggerError, match=complaint):
        parse_trigger(text)


def test_plain_words() -> None:
    assert Daily(time(7, 0)).words() == "every day at 07:00"
    assert Daily(time(7, 0), WEEKDAYS).words() == "every weekday (Monday to Friday) at 07:00"
    assert Daily(time(9, 0), WEEKENDS).words() == "every Saturday and Sunday at 09:00"
    assert Daily(time(9, 0), frozenset({0, 2, 4})).words() == (
        "every Monday, Wednesday and Friday at 09:00"
    )
    assert Once(datetime(2026, 10, 5, 7, 0)).words() == "once, on Monday 5 October 2026 at 07:00"
    assert Every(15).words() == "every 15 minutes"


def test_daily_next_after_skips_days_not_chosen() -> None:
    weekdays = Daily(time(7, 0), WEEKDAYS)
    friday_8 = local(2026, 10, 2, 8, 0)
    assert weekdays.next_after(friday_8, zone=ZONE, anchor=ANCHOR) == local(2026, 10, 5, 7, 0)
    friday_6 = local(2026, 10, 2, 6, 59)
    assert weekdays.next_after(friday_6, zone=ZONE, anchor=ANCHOR) == local(2026, 10, 2, 7, 0)
    exactly = local(2026, 10, 2, 7, 0)
    assert weekdays.next_after(exactly, zone=ZONE, anchor=ANCHOR) == local(2026, 10, 5, 7, 0)
    sunday = Daily(time(7, 0), frozenset({6}))
    assert sunday.next_after(friday_8, zone=ZONE, anchor=ANCHOR) == local(2026, 10, 4, 7, 0)


def test_daily_between_counts_slots_in_the_half_open_interval() -> None:
    every_day = Daily(time(7, 0), ALL_DAYS)
    after, until = local(2026, 10, 1, 7, 0), local(2026, 10, 4, 7, 0)
    assert every_day.between(after, until, zone=ZONE, anchor=ANCHOR) == (
        3,
        local(2026, 10, 4, 7, 0),
    )
    weekdays = Daily(time(7, 0), WEEKDAYS)
    assert weekdays.between(after, until, zone=ZONE, anchor=ANCHOR) == (1, local(2026, 10, 2, 7))
    assert weekdays.between(until, after, zone=ZONE, anchor=ANCHOR) == (0, None)


def test_daily_follows_daylight_saving_time() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    daily = Daily(time(7, 0))
    before = datetime(2026, 10, 23, 12, 0, tzinfo=berlin)  # CEST, UTC+2; CET from the 25th
    first = daily.next_after(before, zone=berlin, anchor=before)
    second = daily.next_after(first, zone=berlin, anchor=before)
    assert first.astimezone(UTC).hour == 5  # 07:00 CEST
    assert second.astimezone(UTC).hour == 6  # 07:00 CET, after the clocks went back
    assert second.astimezone(berlin).hour == 7


def test_once_is_one_slot() -> None:
    once = Once(datetime(2026, 10, 5, 7, 0))
    slot = local(2026, 10, 5, 7, 0)
    assert once.next_after(local(2026, 10, 2), zone=ZONE, anchor=ANCHOR) == slot
    assert once.next_after(slot, zone=ZONE, anchor=ANCHOR) is None
    assert once.between(local(2026, 10, 2), local(2026, 10, 6), zone=ZONE, anchor=ANCHOR) == (
        1,
        slot,
    )
    assert once.between(slot, local(2026, 10, 6), zone=ZONE, anchor=ANCHOR) == (0, None)


def test_every_counts_real_minutes_from_the_anchor() -> None:
    every = Every(5)
    anchor = datetime(2026, 10, 2, 6, 0, 30, tzinfo=UTC)
    assert every.next_after(anchor, zone=ZONE, anchor=anchor) == anchor + timedelta(minutes=5)
    before_anchor = anchor - timedelta(hours=1)
    assert every.next_after(before_anchor, zone=ZONE, anchor=anchor) == anchor + timedelta(
        minutes=5
    )
    later = anchor + timedelta(minutes=12)
    assert every.next_after(later, zone=ZONE, anchor=anchor) == anchor + timedelta(minutes=15)
    count, latest = every.between(anchor, anchor + timedelta(minutes=32), zone=ZONE, anchor=anchor)
    assert (count, latest) == (6, anchor + timedelta(minutes=30))
    count, latest = every.between(
        anchor + timedelta(minutes=10), anchor + timedelta(minutes=20), zone=ZONE, anchor=anchor
    )
    assert (count, latest) == (2, anchor + timedelta(minutes=20))
    # a year offline is arithmetic, not a loop
    count, _ = every.between(anchor, anchor + timedelta(days=365), zone=ZONE, anchor=anchor)
    assert count == 365 * 24 * 12
