"""The hub process: lock, crash check, services, heartbeat, clean stop.

:meth:`Hub.run` is what ``tau hub run`` (and launchd / systemd through it) executes:

1. take the single-instance :class:`~tau_core.hub.lock.HubLock` (or raise ``AlreadyRunning``);
2. turn a stale ``state.json`` from a previous run into a crash report;
3. write the new ``state.json`` and start the services in order;
4. refresh ``state.json`` every ``heartbeat_seconds`` until SIGTERM/SIGINT or
   :meth:`Hub.request_stop`;
5. stop the services in reverse order and write ``stopped_at`` (exit 0).

If anything raises, the services that started are stopped, ``crash.json`` records the reason
and ``run()`` returns 1, so launchd (``KeepAlive.SuccessfulExit = false``) and systemd
(``Restart=on-failure``) start it again and the next start reports why it died.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import traceback
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from tau_core import __version__
from tau_core.config import Config
from tau_core.hub.lock import HubLock
from tau_core.hub.state import CrashReport, HubFiles, HubState, parse_timestamp, timestamp, utc_now

logger = logging.getLogger(__name__)

StatusSource = Callable[[], dict[str, Any]]
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


@runtime_checkable
class HubService(Protocol):
    """Something the hub starts after its crash check and stops before it exits."""

    name: str

    async def start(self, hub: Hub) -> None: ...

    async def stop(self) -> None: ...


class Hub:
    """The long-lived hub process. Build it, add services, call :meth:`run` once."""

    def __init__(
        self,
        config: Config,
        *,
        services: Iterable[HubService] = (),
        clock: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self.services: list[HubService] = list(services)
        self.files = HubFiles(config.hub_dir)
        self.state: HubState | None = None
        self.crash_report: CrashReport | None = None  # found by this start, if any
        self.crash_reason: str | None = None  # set when this run ended in a crash
        self.loop: asyncio.AbstractEventLoop | None = None
        self._clock = clock or utc_now
        self._status_sources: list[StatusSource] = []
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = False

    # -- wiring ---------------------------------------------------------------------------

    def add_service(self, service: HubService) -> None:
        self.services.append(service)

    def add_status_source(self, source: StatusSource) -> None:
        """Merge ``source()`` into :meth:`status` (later issues: spend, approvals, nodes)."""
        self._status_sources.append(source)

    # -- status ---------------------------------------------------------------------------

    def uptime_s(self) -> float | None:
        started = parse_timestamp(self.state.started_at) if self.state else None
        if started is None:
            return None
        return round(max(0.0, (self._clock() - started).total_seconds()), 1)

    def status(self) -> dict[str, Any]:
        """The ``/status`` payload. Base keys are fixed; status sources add more."""
        state = self.state
        data: dict[str, Any] = {
            "pid": state.pid if state else os.getpid(),
            "role": self.config.role,
            "profile": self.config.profile,
            "version": __version__,
            "started_at": state.started_at if state else None,
            "heartbeat_at": state.heartbeat_at if state else None,
            "uptime_s": self.uptime_s(),
            "last_crash": state.last_crash if state else None,
            "approvals_pending": 0,
            "nodes": None,
        }
        for source in list(self._status_sources):
            try:
                data.update(source())
            except Exception:
                logger.exception("hub status source %r failed", source)
        return data

    # -- lifecycle ------------------------------------------------------------------------

    def request_stop(self) -> None:
        """Ask a running hub to stop cleanly; safe from any thread and before ``run()``."""
        self._stop_requested = True
        loop, event = self.loop, self._stop_event
        if loop is not None and event is not None and not loop.is_closed():
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(event.set)

    def run(self) -> int:
        """Run until stopped. 0 = clean stop, 1 = crash. Raises ``AlreadyRunning``."""
        lock = HubLock(self.files.lock)
        lock.acquire()
        try:
            return asyncio.run(self._main())
        except KeyboardInterrupt:
            # Only reachable before the signal handlers are in place; still a user stop.
            self._mark_stopped()
            return 0
        except SystemExit as exc:
            if exc.code in (0, None):
                self._mark_stopped()
            else:
                self._record_crash(exc)
            raise
        except Exception as exc:
            self._record_crash(exc)
            return 1
        finally:
            self.loop = None
            self._stop_event = None
            lock.release()

    def beat(self) -> None:
        """Refresh ``heartbeat_at`` in ``state.json``."""
        if self.state is None:
            return
        self.state.heartbeat_at = timestamp(self._clock())
        try:
            self.files.write_state(self.state)
        except OSError as exc:
            logger.warning("hub heartbeat could not write %s: %s", self.files.state, exc)

    async def _main(self) -> int:
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        if self._stop_requested:
            self._stop_event.set()
        installed = self._install_signal_handlers()
        try:
            await self._serve()
        finally:
            for sig in installed:
                with suppress(Exception):
                    self.loop.remove_signal_handler(sig)
        self._mark_stopped()
        logger.info("tau hub stopped cleanly (pid %s)", os.getpid())
        return 0

    async def _serve(self) -> None:
        self.crash_report = self.files.check_previous_run(now=self._clock())
        if self.crash_report is not None:
            # INFO: the log file keeps it; the terminal gets the Turkish line from the CLI.
            logger.info(
                "previous hub (pid %s) did not stop cleanly: %s",
                self.crash_report.pid,
                self.crash_report.reason,
            )
        now = timestamp(self._clock())
        self.state = HubState(
            pid=os.getpid(),
            started_at=now,
            heartbeat_at=now,
            version=__version__,
            role=self.config.role,
            profile=self.config.profile,
            last_crash=self.files.read_last_crash(),
        )
        self.files.write_state(self.state)

        started: list[HubService] = []
        heartbeat: asyncio.Task[None] | None = None
        try:
            for service in self.services:
                logger.info("starting hub service %s", service.name)
                await service.start(self)
                started.append(service)
            heartbeat = asyncio.create_task(self._heartbeat(), name="tau-hub-heartbeat")
            logger.info("tau hub running (pid %s)", os.getpid())
            assert self._stop_event is not None
            await self._stop_event.wait()
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            for service in reversed(started):
                try:
                    await service.stop()
                except Exception:
                    logger.exception("hub service %s failed to stop", service.name)

    async def _heartbeat(self) -> None:
        interval = self.config.hub.heartbeat_seconds
        while True:
            await asyncio.sleep(interval)
            self.beat()

    def _install_signal_handlers(self) -> list[signal.Signals]:
        if threading.current_thread() is not threading.main_thread():
            return []
        assert self.loop is not None
        installed = []
        for sig in STOP_SIGNALS:
            try:
                self.loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError, ValueError):
                continue
            installed.append(sig)
        return installed

    def _on_signal(self, sig: signal.Signals) -> None:
        logger.info("tau hub received %s; stopping", sig.name)
        self.request_stop()

    def _mark_stopped(self) -> None:
        if self.state is None:
            return
        now = timestamp(self._clock())
        self.state.heartbeat_at = now
        self.state.stopped_at = now
        self.files.write_state(self.state)

    def _record_crash(self, exc: BaseException) -> None:
        reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        self.crash_reason = reason
        logger.error("tau hub crashed: %s", reason, exc_info=exc)
        try:
            self.files.write_crash_marker(
                pid=os.getpid(),
                reason=reason,
                at=timestamp(self._clock()),
                traceback="".join(traceback.format_exception(exc)),
            )
        except OSError as write_error:
            logger.error("could not write %s: %s", self.files.crash, write_error)
