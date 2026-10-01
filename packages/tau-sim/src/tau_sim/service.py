"""The ``sim`` hub service: the simulated lamps as a :class:`tau_core.DeviceSource`.

A ``tau.hub_services`` component (``sim = "tau_sim.service:make_service"``) that runs inside
``tau hub run``. tau-web (178) finds it, like every started hub service that implements
``DeviceSource``, serves its lamps at ``/api/devices`` and pushes every change as a ``device``
event.

- :meth:`SimService.devices` reads the state file (and adds a configured lamp it does not know
  yet, see :mod:`tau_sim.lamps`).
- :meth:`SimService.subscribe` calls back with the lamp's new :class:`~tau_core.DeviceState` on
  every change, wherever it was made: a ``lamp_set`` in the hub (Telegram, the web app) or in
  another process (``tau tui``, ``tau chat``). The service watches the state file with a cheap
  ``stat`` every :data:`POLL_SECONDS`; every write is a rename, so a new inode is a change.
  Callbacks run on the hub's event loop; one that raises is logged and the others still run.
- ``GET /status`` gains ``sim``: ``simulated: true``, each lamp's ``on`` as last seen, the
  number of subscribers and the last error of the watcher.
- A ``[component.sim]`` that is not valid fails :func:`make_service`; the hub logs it and runs
  without the service. ``[components.hub] services`` without ``sim`` switches it off, and
  ``[components.tools] disabled = ["dist:tau-sim"]`` the tools.

Nothing here talks to hardware.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from tau_core import Config, DeviceState

from tau_sim.lamps import COMPONENT, Lamp, LampStore

if TYPE_CHECKING:
    from tau_core.hub.daemon import Hub

DeviceCallback = Callable[[DeviceState], None]
Unsubscribe = Callable[[], None]

__all__ = ["POLL_SECONDS", "SERVICE_NAME", "SimService", "make_service"]

logger = logging.getLogger(__name__)

SERVICE_NAME = COMPONENT
POLL_SECONDS = 0.5


class SimService:
    """The ``sim`` hub service. Tests pass a ``store`` and a short ``poll_seconds`` and call
    :meth:`check` to look at the file once without waiting for the watcher."""

    name = SERVICE_NAME

    def __init__(
        self,
        config: Config,
        *,
        store: LampStore | None = None,
        poll_seconds: float = POLL_SECONDS,
    ):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.config = config
        self.store = store if store is not None else LampStore.from_config(config)
        self.poll_seconds = poll_seconds
        self.last_error: str | None = None
        self._subscribers: dict[int, DeviceCallback] = {}
        self._tokens = itertools.count()
        self._subscribers_lock = threading.Lock()
        self._watch_lock = threading.Lock()
        self._known: dict[str, Lamp] = {}
        self._signature: tuple[int, int, int] | None = None
        self._primed = False
        self._task: asyncio.Task[None] | None = None

    # -- DeviceSource --------------------------------------------------------------------------

    def devices(self) -> list[DeviceState]:
        """Every configured lamp, in config order, as of now."""
        return [lamp.device() for lamp in self.store.lamps()]

    def subscribe(self, callback: DeviceCallback) -> Unsubscribe:
        """Call ``callback(state)`` on every lamp change; returns the unsubscribe."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        token = next(self._tokens)
        with self._subscribers_lock:
            self._subscribers[token] = callback

        def unsubscribe() -> None:
            with self._subscribers_lock:
                self._subscribers.pop(token, None)

        return unsubscribe

    # -- watching ------------------------------------------------------------------------------

    def prime(self) -> None:
        """Take the current state as known without telling anyone (done by :meth:`start`)."""
        with self._watch_lock:
            lamps = self.store.lamps()  # adds the lamps the file does not know yet
            self._signature = self.store.signature()
            self._known = {lamp.name: lamp for lamp in lamps}
            self._primed = True

    def changes(self) -> list[DeviceState]:
        """The lamps that changed since the last look, without telling anyone. The first look
        (without :meth:`prime`) only takes the state as known."""
        with self._watch_lock:
            if not self._primed:
                self._known = {lamp.name: lamp for lamp in self.store.peek()}
                self._signature = self.store.signature()
                self._primed = True
                return []
            signature = self.store.signature()
            if signature == self._signature:
                return []
            self._signature = signature
            changed: list[DeviceState] = []
            for lamp in self.store.peek():
                if self._known.get(lamp.name) != lamp:
                    changed.append(lamp.device())
                self._known[lamp.name] = lamp
            return changed

    def notify(self, changes: list[DeviceState]) -> None:
        """Hand every change to every subscriber; a subscriber that raises is logged."""
        if not changes:
            return
        with self._subscribers_lock:
            subscribers = list(self._subscribers.values())
        for state in changes:
            for callback in subscribers:
                try:
                    callback(state)
                except Exception:
                    logger.exception("sim: a device subscriber failed on %s", state.id)

    def check(self) -> list[DeviceState]:
        """Look at the state file once, tell the subscribers and return what changed."""
        changes = self.changes()
        self.notify(changes)
        return changes

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            try:
                changes = await asyncio.to_thread(self.changes)
            except Exception as exc:  # a bad file must never stop the hub
                message = f"{type(exc).__name__}: {exc}"
                if message != self.last_error:
                    logger.warning("sim: watching %s failed: %s", self.store.path, message)
                self.last_error = message
                continue
            self.last_error = None
            self.notify(changes)  # on the hub's loop

    # -- HubService ----------------------------------------------------------------------------

    async def start(self, hub: Hub) -> None:
        hub.add_status_source(lambda: {SERVICE_NAME: self.status()})
        await asyncio.to_thread(self.prime)
        self._task = asyncio.create_task(self._watch(), name="tau-sim-watch")
        logger.info(
            "sim: %d simulated lamp(s): %s", len(self.store.names), ", ".join(self.store.names)
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def status(self) -> dict[str, Any]:
        """The ``sim`` key of the hub's ``/status`` (no file access: the last state seen)."""
        with self._watch_lock:
            lamps = {name: {"on": lamp.on} for name, lamp in self._known.items()}
        with self._subscribers_lock:
            subscribers = len(self._subscribers)
        return {
            "simulated": True,
            "lamps": lamps,
            "subscribers": subscribers,
            "watching": self._task is not None and not self._task.done(),
            "last_error": self.last_error,
        }


def make_service(config: Config) -> SimService:
    """The ``tau.hub_services`` factory."""
    return SimService(config)
