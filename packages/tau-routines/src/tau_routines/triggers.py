"""Clock triggers: when a routine fires.

Three forms, written the way ``tau routine add`` takes them:

- ``daily HH:MM``, optionally on chosen days: ``daily 07:00 weekdays``, ``daily 09:30
  weekends``, ``daily 18:00 mon,wed,fri`` (also ``mon-fri`` and full day names);
- ``once YYYY-MM-DD HH:MM``: one firing at a local date and time;
- ``every N minutes``, with N from 5 to 10080 (a week).

Times are wall-clock times in the routines' time zone (``[component.routines] timezone``,
default the hub's local zone). ``every`` counts real minutes from the routine's anchor (its
creation), whatever the zone does.

Every trigger answers two questions for the engine, given the zone and the anchor:
``next_after(t)`` (the first slot after ``t``) and ``between(after, until)`` (how many slots
fall in ``(after, until]``, and the latest of them). All datetimes in and out are aware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from tau_routines.settings import RoutineError

__all__ = [
    "DAY_NAMES",
    "EVERY_RANGE",
    "Daily",
    "Every",
    "Once",
    "Trigger",
    "TriggerError",
    "parse_trigger",
]

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_FULL_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
EVERY_RANGE = (5, 10080)
WEEKDAYS = frozenset(range(5))
WEEKENDS = frozenset({5, 6})
ALL_DAYS = frozenset(range(7))

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DAY_ALIASES = {name: i for i, name in enumerate(DAY_NAMES)} | {
    full.lower(): i for i, full in enumerate(_FULL_DAYS)
}
_UNITS = ("minutes", "minute", "mins", "min", "m")
EXAMPLES = '"daily 07:00", "daily 07:00 weekdays", "once 2026-10-05 07:00" or "every 15 minutes"'


class TriggerError(RoutineError, ValueError):
    """A trigger that cannot be parsed; the message says what was expected."""


def _local(day: date, at: time, zone: tzinfo) -> datetime:
    return datetime.combine(day, at, tzinfo=zone)


def _day_list(days: frozenset[int]) -> str:
    names = [_FULL_DAYS[i] for i in sorted(days)]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


@dataclass(frozen=True)
class Daily:
    """At ``at`` (wall-clock) on every day in ``days`` (0 = Monday)."""

    at: time
    days: frozenset[int] = ALL_DAYS

    @property
    def text(self) -> str:
        head = f"daily {self.at:%H:%M}"
        if self.days == ALL_DAYS:
            return head
        if self.days == WEEKDAYS:
            return f"{head} weekdays"
        if self.days == WEEKENDS:
            return f"{head} weekends"
        return f"{head} " + ",".join(DAY_NAMES[i] for i in sorted(self.days))

    def words(self) -> str:
        at = f"{self.at:%H:%M}"
        if self.days == ALL_DAYS:
            return f"every day at {at}"
        if self.days == WEEKDAYS:
            return f"every weekday (Monday to Friday) at {at}"
        return f"every {_day_list(self.days)} at {at}"

    def next_after(self, t: datetime, *, zone: tzinfo, anchor: datetime) -> datetime | None:
        start = t.astimezone(zone).date()
        for offset in range(9):
            day = start + timedelta(days=offset)
            if day.weekday() in self.days:
                slot = _local(day, self.at, zone)
                if slot > t:
                    return slot
        return None  # pragma: no cover  (every day set has a day within a week)

    def between(
        self, after: datetime, until: datetime, *, zone: tzinfo, anchor: datetime
    ) -> tuple[int, datetime | None]:
        if until <= after:
            return 0, None
        count, latest = 0, None
        day = after.astimezone(zone).date()
        last = until.astimezone(zone).date()
        while day <= last:
            if day.weekday() in self.days:
                slot = _local(day, self.at, zone)
                if after < slot <= until:
                    count, latest = count + 1, slot
            day += timedelta(days=1)
        return count, latest


@dataclass(frozen=True)
class Once:
    """Once, at the wall-clock datetime ``at`` (naive) in the routines' zone."""

    at: datetime

    @property
    def text(self) -> str:
        return f"once {self.at:%Y-%m-%d %H:%M}"

    def words(self) -> str:
        at = self.at
        return (
            f"once, on {_FULL_DAYS[at.weekday()]} {at.day} {_MONTHS[at.month - 1]} {at.year} "
            f"at {at:%H:%M}"
        )

    def slot(self, zone: tzinfo) -> datetime:
        return self.at.replace(tzinfo=zone)

    def next_after(self, t: datetime, *, zone: tzinfo, anchor: datetime) -> datetime | None:
        slot = self.slot(zone)
        return slot if slot > t else None

    def between(
        self, after: datetime, until: datetime, *, zone: tzinfo, anchor: datetime
    ) -> tuple[int, datetime | None]:
        slot = self.slot(zone)
        return (1, slot) if after < slot <= until else (0, None)


@dataclass(frozen=True)
class Every:
    """Every ``minutes`` minutes, counted from the anchor (the routine's creation)."""

    minutes: int

    @property
    def text(self) -> str:
        return f"every {self.minutes} minutes"

    def words(self) -> str:
        return self.text

    @property
    def step(self) -> timedelta:
        return timedelta(minutes=self.minutes)

    def next_after(self, t: datetime, *, zone: tzinfo, anchor: datetime) -> datetime | None:
        k = max(1, (t - anchor) // self.step + 1)
        return anchor + k * self.step

    def between(
        self, after: datetime, until: datetime, *, zone: tzinfo, anchor: datetime
    ) -> tuple[int, datetime | None]:
        if until <= after:
            return 0, None
        first = max(1, (after - anchor) // self.step + 1)
        last = (until - anchor) // self.step
        if last < first:
            return 0, None
        return last - first + 1, anchor + last * self.step


Trigger = Daily | Once | Every


def _parse_days(words: list[str]) -> frozenset[int]:
    text = " ".join(words).lower()
    if text.startswith("on "):
        text = text[3:]
    text = text.strip()
    if text in ("", "every day", "everyday", "daily", "all"):
        return ALL_DAYS
    if text in ("weekdays", "weekday", "workdays"):
        return WEEKDAYS
    if text in ("weekends", "weekend"):
        return WEEKENDS
    days: set[int] = set()
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        if "-" in part:
            first, _, last = part.partition("-")
            if first not in _DAY_ALIASES or last not in _DAY_ALIASES:
                raise TriggerError(f"{part!r} is not a range of days such as mon-fri.")
            start, end = _DAY_ALIASES[first], _DAY_ALIASES[last]
            if end < start:
                raise TriggerError(f"{part!r} runs backwards; write it as {last}-{first}.")
            days.update(range(start, end + 1))
        elif part in _DAY_ALIASES:
            days.add(_DAY_ALIASES[part])
        else:
            raise TriggerError(
                f"{part!r} is not a day: use weekdays, weekends or mon,tue,wed,thu,fri,sat,sun."
            )
    return frozenset(days)


def _parse_time(text: str) -> time:
    match = _TIME.match(text)
    if not match:
        raise TriggerError(f"{text!r} is not a time of day as HH:MM, for example 07:00.")
    return time(int(match.group(1)), int(match.group(2)))


def parse_trigger(text: str) -> Trigger:
    """Parse a trigger; :class:`TriggerError` names what was expected."""
    if not isinstance(text, str):
        raise TriggerError(f"A trigger is text such as {EXAMPLES}.")
    words = text.strip().split()
    if not words:
        raise TriggerError(f"The trigger is empty; write one such as {EXAMPLES}.")
    kind = words[0].lower()
    if kind == "daily":
        if len(words) < 2:
            raise TriggerError('"daily" needs a time, for example "daily 07:00".')
        return Daily(at=_parse_time(words[1]), days=_parse_days(words[2:]))
    if kind == "once":
        stamp = " ".join(words[1:]).replace("T", " ")
        try:
            at = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
        except ValueError:
            raise TriggerError(
                '"once" needs a local date and time as YYYY-MM-DD HH:MM, for example '
                '"once 2026-10-05 07:00".'
            ) from None
        return Once(at=at)
    if kind == "every":
        rest = " ".join(words[1:]).lower()
        match = re.fullmatch(r"(\d+)\s*(" + "|".join(_UNITS) + r")", rest)
        if not match:
            raise TriggerError('"every" needs a number of minutes, for example "every 15 minutes".')
        minutes = int(match.group(1))
        low, high = EVERY_RANGE
        if not low <= minutes <= high:
            raise TriggerError(
                f"every {minutes} minutes is not allowed: use {low} to {high} minutes."
            )
        return Every(minutes=minutes)
    raise TriggerError(f"{words[0]!r} is not a trigger; write one such as {EXAMPLES}.")
