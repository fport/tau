"""The ``routines`` hub service (``tau.hub_services`` entry point ``routines``).

It runs the :class:`~tau_routines.engine.RoutineEngine` for as long as the hub runs. It needs
no credentials, no model and no network; it reads ``TAU_DATA_DIR/routines/routines.json`` and
picks up what ``tau routine`` and the tools write there within :data:`~tau_routines.engine.
POLL_SECONDS` (the file's stamp changes with every write). A bad ``[component.routines]``
table makes :meth:`RoutinesService.start` raise; the hub logs it and runs on without routines.

Channels see each firing as a ``routine`` agent event on :attr:`RoutinesService.events`
(``hub.find_service("routines").events.subscribe(...)``); ``tau hub status`` gets a
``routines`` entry.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from strands.types.tools import AgentTool
from tau_core import Config, EventBus

from tau_routines.engine import RoutineEngine
from tau_routines.model import stamp
from tau_routines.registration import tool_catalog
from tau_routines.settings import COMPONENT, RoutineSettings
from tau_routines.store import RoutineStore

if TYPE_CHECKING:
    from tau_core.hub.daemon import Hub

__all__ = ["RoutinesService", "make_service"]

logger = logging.getLogger(__name__)


class RoutinesService:
    """Runs the routine engine inside the hub."""

    name = COMPONENT

    def __init__(
        self,
        config: Config,
        *,
        tools: Iterable[AgentTool] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.config = config
        self.events = EventBus()
        """Every firing's ``routine`` event, and the gate's ``tool_call``/``approval`` events."""
        self.engine: RoutineEngine | None = None
        self._tools = list(tools) if tools is not None else None
        self._clock = clock
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    async def start(self, hub: Hub) -> None:
        settings = RoutineSettings.from_config(self.config)
        catalog = tool_catalog(self.config, self._tools)
        self.engine = RoutineEngine(
            RoutineStore.for_config(self.config),
            settings,
            tools=catalog.values(),
            events=self.events,
            clock=self._clock,
            sleep=self._sleep,
        )
        self._task = asyncio.create_task(self.engine.run(), name="tau-routines")
        add_status_source = getattr(hub, "add_status_source", None)
        if callable(add_status_source):
            add_status_source(self.status)
        logger.info(
            "routines: engine started (%s time, grace %d min, %d tools)",
            settings.zone_name,
            settings.grace_minutes,
            len(catalog),
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def status(self) -> dict[str, Any]:
        """The ``routines`` entry of the hub's ``/status``."""
        engine = self.engine
        if engine is None:
            return {"routines": None}
        routines = engine.routines
        upcoming = engine.next_due()
        return {
            "routines": {
                "total": len(routines),
                "enabled": sum(1 for r in routines if r.enabled),
                "next_at": stamp(upcoming) if upcoming is not None else None,
            }
        }


def make_service(config: Config) -> RoutinesService:
    """The ``tau.hub_services`` factory."""
    return RoutinesService(config)
