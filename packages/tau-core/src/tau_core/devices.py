"""Device sources: how hub services tell the rest of tau about devices (ADR 0015 §5).

A *device source* is anything that knows devices and their state: the ``sim`` hub service of
tau-sim with its simulated lamps today, the mesh (032, 033) later. tau-web finds every started
hub service that implements :class:`DeviceSource`, serves ``/api/devices`` from
:meth:`DeviceSource.devices` and pushes each change from :meth:`DeviceSource.subscribe` as a
``device`` event, serialized with :func:`to_json`.

- :class:`DeviceState` is one device at one moment. ``updated`` is a timezone-aware
  :class:`~datetime.datetime` in UTC: when the state last changed, as far as the source knows.
  ``simulated`` is ``True`` for a stand-in such as tau-sim's lamp, and every channel that shows
  the device must say so.
- :class:`DeviceSource` is a structural protocol (``runtime_checkable``): a service needs no base
  class, only the two methods. ``isinstance`` checks that the methods exist, not their types.

The contract of ``subscribe``:

- ``callback(state)`` is called once for every change of a device, with the device's new
  :class:`DeviceState`; it is not called for the current state when it subscribes (read
  :meth:`DeviceSource.devices` for that).
- A source calls back on a thread of its choosing (a hub service: the hub's event loop), so a
  callback returns quickly and hops to its own loop itself (``loop.call_soon_threadsafe``).
- An exception raised by a callback is logged by the source and never reaches the other
  subscribers or stops the source.
- ``subscribe`` returns a function that unsubscribes; calling it twice is harmless.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

__all__ = ["DeviceCallback", "DeviceSource", "DeviceState", "Unsubscribe", "to_json"]

DeviceCallback = Callable[["DeviceState"], None]
"""What :meth:`DeviceSource.subscribe` calls with a device's new state."""
Unsubscribe = Callable[[], None]
"""What :meth:`DeviceSource.subscribe` returns: call it to stop the callbacks."""


@dataclass(frozen=True)
class DeviceState:
    """One device at one moment.

    - ``id``: stable and unique across sources, for example ``sim:lamp:desk``.
    - ``name``: what the owner calls it, for example ``desk``.
    - ``kind``: what it is, for example ``lamp``.
    - ``simulated``: ``True`` for a stand-in; every channel that shows it says so.
    - ``state``: the device's own JSON-safe fields, for example ``{"on": True}``.
    - ``updated``: when the state last changed; timezone-aware, normalized to UTC.

    A naive ``updated`` raises ``ValueError``: a time without a zone means nothing on a hub
    whose channels are in other time zones.
    """

    id: str
    name: str
    kind: str
    simulated: bool
    state: dict[str, Any]
    updated: datetime

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "kind"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"DeviceState.{field_name} must be a non-empty string")
        if not isinstance(self.simulated, bool):
            raise ValueError("DeviceState.simulated must be a bool")
        if not isinstance(self.state, dict):
            raise ValueError("DeviceState.state must be a dict")
        if not isinstance(self.updated, datetime) or self.updated.utcoffset() is None:
            raise ValueError("DeviceState.updated must be a timezone-aware datetime")
        object.__setattr__(self, "updated", self.updated.astimezone(UTC))


@runtime_checkable
class DeviceSource(Protocol):
    """Something that knows devices: their current state and every change of it."""

    def devices(self) -> list[DeviceState]:
        """Every device the source knows, in a stable order, as of now."""
        ...

    def subscribe(self, callback: DeviceCallback) -> Unsubscribe:
        """Call ``callback`` with the new state on every change; returns the unsubscribe."""
        ...


def to_json(device: DeviceState) -> dict[str, Any]:
    """``device`` as a JSON-safe dict for the web API: ``updated`` becomes an ISO 8601 string
    in UTC (``2026-10-01T07:00:00+00:00``) and ``state`` is a copy the caller may change."""
    return {
        "id": device.id,
        "name": device.name,
        "kind": device.kind,
        "simulated": device.simulated,
        "state": copy.deepcopy(device.state),
        "updated": device.updated.isoformat(),
    }
