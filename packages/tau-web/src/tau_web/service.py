"""The ``web`` hub service: the web app's server inside ``tau hub run`` (ADR 0015 §2).

It binds its socket itself (so a port in use fails ``start`` cleanly instead of uvicorn's
``sys.exit``), serves the app with uvicorn on the hub's event loop without touching the hub's
signal handlers, and runs the turns of the ``web`` channel through :class:`Runtime`. The guard
is the hub's ``guard`` service when there is one (``DISCOVER`` otherwise, which resolves it from
the configuration), so a web turn is admitted like a TUI turn; a guard lock rejects pending
approvals and cancels running turns.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import uvicorn
from tau_core import (
    Config,
    DeviceSource,
    Guard,
    HubService,
    SessionStore,
    build_agent,
    open_session_store,
)
from tau_core.guard import DISCOVER
from tau_core.turn_protocol import PROTOCOL_VERSION

from tau_web.access import AccessVerifier
from tau_web.app import create_app
from tau_web.devices import DeviceRegistry
from tau_web.settings import COMPONENT, WebSettings
from tau_web.turns import AgentFactory, Runtime

logger = logging.getLogger(__name__)

SERVICE_NAME = COMPONENT
SWEEP_SECONDS = 30.0

OPTIONAL_PAGES = {"guard": "guard", "routines": "routines", "net": "net", "telegram": "telegram"}
"""Hub service name → the app page it enables, when that service runs."""


class _HubServer(uvicorn.Server):
    """uvicorn on the hub's loop: the hub owns SIGTERM and SIGINT, not the web server."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[override]
        yield


def static_dir() -> Path | None:
    """The built app shipped in the wheel (``tau_web/static``), if any."""
    path = Path(str(resources.files("tau_web") / "static"))
    return path if (path / "index.html").is_file() else None


class WebService:
    name = SERVICE_NAME

    def __init__(
        self,
        config: Config,
        *,
        settings: WebSettings | None = None,
        store: SessionStore | None = None,
        agent_factory: AgentFactory = build_agent,
    ) -> None:
        self.config = config
        self.settings = settings or WebSettings.from_config(config)
        self.store = store
        """The session store; ``None`` opens the configured one at start (tests pass theirs)."""
        self.agent_factory = agent_factory
        self.devices = DeviceRegistry(config.data_dir / "web")
        self.hub: Any = None
        self.runtime: Runtime | None = None
        self._server: _HubServer | None = None
        self._task: asyncio.Task[None] | None = None
        self._sweeper: asyncio.Task[None] | None = None
        self._unsubscribe_guard: Callable[[], None] | None = None
        self.port: int | None = None

    # -- the hub's parts -------------------------------------------------------------------------

    def guard(self) -> Any:
        """The guard to build agents with: the hub's guard service, else ``DISCOVER``."""
        service = self.hub.find_service("guard") if self.hub is not None else None
        return service if isinstance(service, Guard) else DISCOVER

    def capabilities(self) -> dict[str, Any]:
        pages = []
        if self.hub is not None:
            for name, page in OPTIONAL_PAGES.items():
                if self.hub.find_service(name) is not None:
                    pages.append(page)
            if any(isinstance(s, DeviceSource) for s in self.hub.started_services()):
                pages.append("devices")
        return {
            "backend": "hub",
            "protocol": PROTOCOL_VERSION,
            "language": self.config.ui.language,
            "pages": pages,
        }

    def status(self) -> dict[str, Any]:
        runtime = self.runtime.status() if self.runtime is not None else {}
        return {
            SERVICE_NAME: {
                "bind": self.settings.bind,
                "port": self.port,
                "devices": len(self.devices.list()),
                **runtime,
            }
        }

    # -- HubService ----------------------------------------------------------------------------

    async def start(self, hub: Any) -> None:
        self.hub = hub
        if self.store is None:
            self.store = open_session_store(self.config)
        self.runtime = Runtime(
            self.config,
            self.store,
            guard=self.guard,
            approval_timeout=self.settings.approval_timeout,
            turn_keep=self.settings.turn_keep,
            agent_factory=self.agent_factory,
        )
        access = None
        if self.settings.access_check:
            assert self.settings.access_team and self.settings.access_aud
            access = AccessVerifier(self.settings.access_team, self.settings.access_aud)
        app = create_app(
            settings=self.settings,
            devices=self.devices,
            runtime=self.runtime,
            capabilities=self.capabilities,
            static_dir=static_dir(),
            access=access,
        )
        sock = socket.socket(socket.AF_INET6 if ":" in self.settings.bind else socket.AF_INET)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.settings.bind, self.settings.port))
            sock.listen(128)
            sock.setblocking(False)
        except OSError:
            sock.close()
            raise
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(
            app, log_level="warning", access_log=False, lifespan="off", proxy_headers=False
        )
        self._server = _HubServer(config)
        self._task = asyncio.get_running_loop().create_task(
            self._server.serve(sockets=[sock]), name="tau-web-server"
        )
        for _ in range(200):
            if self._server.started or self._task.done():
                break
            await asyncio.sleep(0.02)
        if self._task.done():
            self._task.result()  # raises what stopped it
        guard = self.guard()
        subscribe = getattr(guard, "subscribe", None)
        if isinstance(guard, Guard) and callable(subscribe):
            self._unsubscribe_guard = subscribe(self._on_guard)
        self._sweeper = asyncio.get_running_loop().create_task(self._sweep(), name="tau-web-sweep")
        hub.add_status_source(self.status)
        logger.info("web: serving on %s:%s", self.settings.bind, self.port)

    def _on_guard(self, status: Any) -> None:
        if getattr(status, "state", None) == "locked" and self.runtime is not None:
            self.runtime.on_lock()

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_SECONDS)
            if self.runtime is not None:
                self.runtime.sweep()

    async def stop(self) -> None:
        if self._unsubscribe_guard is not None:
            self._unsubscribe_guard()
            self._unsubscribe_guard = None
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        if self.runtime is not None:
            await self.runtime.close()
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                logger.warning("web: the server did not stop in time")
                self._task.cancel()


def make_service(config: Config) -> HubService:
    """The ``tau.hub_services`` factory; a wrong ``[component.web]`` fails here, by name."""
    return WebService(config)
