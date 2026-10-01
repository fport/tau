"""``[component.routines]`` in ``tau.toml``, the hub's local time zone and the error types.

```toml
[component.routines]
timezone = "Europe/Istanbul"   # an IANA zone; default: the hub's local zone
grace_minutes = 10             # a firing missed while the hub was off runs if this recent
```

A key that is not listed here is an error, not a silent default: a typo such as
``grace_minuts`` must not leave a lamp switching at the wrong hour.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tau_core import Config

__all__ = [
    "COMPONENT",
    "GRACE_DEFAULT",
    "GRACE_RANGE",
    "SETTING_KEYS",
    "RoutineConfigError",
    "RoutineError",
    "RoutineSettings",
    "local_zone",
]

logger = logging.getLogger(__name__)

COMPONENT = "routines"
"""The component name: ``[component.routines]``, the hub service ``routines``."""
GRACE_DEFAULT = 10
GRACE_RANGE = (0, 1440)
SETTING_KEYS = frozenset({"timezone", "grace_minutes"})


class RoutineError(Exception):
    """A routine that cannot be registered, found or stored; the message is plain English."""


class RoutineConfigError(RoutineError):
    """``[component.routines]`` is not valid."""


def _zone_name_from_localtime() -> str | None:
    """The IANA name ``/etc/localtime`` links to (macOS and most Linux systems), else ``None``."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    marker = "zoneinfo/"
    index = target.rfind(marker)
    return target[index + len(marker) :] if index >= 0 else None


def local_zone() -> tuple[tzinfo, str]:
    """The hub's local time zone and its name.

    ``TZ`` first, then the zone ``/etc/localtime`` names, so daylight saving time is followed;
    when neither names a zone, the current fixed UTC offset of the system clock.
    """
    candidates = [os.environ.get("TZ", "").lstrip(":").strip(), _zone_name_from_localtime()]
    for name in candidates:
        if not name:
            continue
        try:
            return ZoneInfo(name), name
        except (ZoneInfoNotFoundError, ValueError):
            continue
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone, zone.tzname(None) or "local"


@dataclass(frozen=True)
class RoutineSettings:
    """The parsed ``[component.routines]`` table."""

    zone: tzinfo
    zone_name: str
    grace_minutes: int = GRACE_DEFAULT

    @classmethod
    def from_mapping(cls, table: dict[str, Any]) -> RoutineSettings:
        unknown = sorted(set(table) - SETTING_KEYS)
        if unknown:
            raise RoutineConfigError(
                f"[component.{COMPONENT}] has unknown keys: {', '.join(unknown)} "
                f"(known: {', '.join(sorted(SETTING_KEYS))})."
            )
        name = table.get("timezone")
        if name is None:
            zone, zone_name = local_zone()
        else:
            if not isinstance(name, str) or not name.strip():
                raise RoutineConfigError(
                    f"[component.{COMPONENT}] timezone must be a zone name such as "
                    f'"Europe/Istanbul", not {name!r}.'
                )
            zone_name = name.strip()
            try:
                zone = ZoneInfo(zone_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise RoutineConfigError(
                    f"[component.{COMPONENT}] timezone {zone_name!r} is not a known time zone."
                ) from exc
        grace = table.get("grace_minutes", GRACE_DEFAULT)
        low, high = GRACE_RANGE
        if isinstance(grace, bool) or not isinstance(grace, int) or not low <= grace <= high:
            raise RoutineConfigError(
                f"[component.{COMPONENT}] grace_minutes must be a whole number from {low} to "
                f"{high}, not {grace!r}."
            )
        return cls(zone=zone, zone_name=zone_name, grace_minutes=grace)

    @classmethod
    def from_config(cls, config: Config) -> RoutineSettings:
        return cls.from_mapping(config.component(COMPONENT))
