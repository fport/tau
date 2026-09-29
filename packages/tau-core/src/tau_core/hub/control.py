"""The hub's local control API: JSON over HTTP on 127.0.0.1 only.

TauBar, hooks and other local processes read the hub's health and status here. The server is
the standard library's ``ThreadingHTTPServer`` in a background thread; it binds to 127.0.0.1
(never a public interface) and rejects requests whose ``Host`` header is not a loopback name,
so a web page cannot reach it through DNS rebinding.

Handlers run in the server's threads, not on the hub's event loop. A handler that needs the loop
uses ``asyncio.run_coroutine_threadsafe(coro, hub.loop)``. Later issues add routes additively
(``routes=`` or :meth:`ControlApi.add_route`) and extend ``/status`` through
``Hub.add_status_source``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socketserver
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

if TYPE_CHECKING:
    from tau_core.hub.daemon import Hub

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "[::1]"})
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ControlRequest:
    """One request as a handler sees it."""

    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> Any:
        """The body parsed as JSON (``None`` for an empty body); raises ``ValueError``."""
        return json.loads(self.body) if self.body else None


Handler = Callable[[ControlRequest], tuple[int, Any]]
"""``request → (HTTP status, JSON-serializable payload)``."""


def _host_allowed(host: str | None) -> bool:
    if not host:
        return True  # HTTP/1.0 clients may omit Host; the socket is loopback-only anyway
    host = host.strip().lower()
    if host.startswith("["):
        name = host.split("]", 1)[0] + "]"
    else:
        name = host.rsplit(":", 1)[0]
    return name in LOOPBACK_NAMES


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the host name (a reverse DNS lookup that can stall on
        # macOS); the loopback address needs none of that.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def _handler_class(api: ControlApi) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "tau-hub"
        sys_version = ""
        timeout = 10

        def _dispatch(self, method: str) -> None:
            if not _host_allowed(self.headers.get("Host")):
                self._send(403, {"error": "local access only"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(413, {"error": "request body too large"})
                return
            body = self.rfile.read(length) if length else b""
            url = urlsplit(self.path)
            request = ControlRequest(
                method=method,
                path=url.path,
                query=parse_qs(url.query),
                headers={k.lower(): v for k, v in self.headers.items()},
                body=body,
            )
            status, payload = api.handle(request)
            self._send(status, payload)

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("control api %s: %s", self.address_string(), format % args)

    return RequestHandler


class ControlApi:
    """A :class:`~tau_core.hub.daemon.HubService` serving ``/health`` and ``/status``.

    ``port=0`` binds an ephemeral port; :attr:`port` holds the bound port after start.
    """

    name = "control-api"

    def __init__(
        self,
        port: int,
        status_provider: Callable[[], dict[str, Any]],
        routes: dict[tuple[str, str], Handler] | None = None,
    ):
        self.port = port
        self.status_provider = status_provider
        self.routes: dict[tuple[str, str], Handler] = {
            ("GET", "/health"): self._health,
            ("GET", "/status"): self._status,
        }
        if routes:
            self.routes.update(routes)
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._started = time.monotonic()

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def add_route(self, method: str, path: str, handler: Handler) -> None:
        self.routes[(method.upper(), path)] = handler

    # -- HubService -----------------------------------------------------------------------

    async def start(self, hub: Hub) -> None:
        self.serve()

    async def stop(self) -> None:
        await asyncio.to_thread(self.shutdown)

    # -- plain methods (usable without a hub) ---------------------------------------------

    def serve(self) -> None:
        """Bind 127.0.0.1:``port`` and serve in a background thread. Raises ``OSError``."""
        if self._server is not None:
            return
        server = _Server((HOST, self.port), _handler_class(self))
        self._server = server
        self.port = server.server_port
        self._started = time.monotonic()
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="tau-hub-control-api",
            daemon=True,
        )
        self._thread.start()
        logger.info("control api listening on %s", self.url)

    def shutdown(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def handle(self, request: ControlRequest) -> tuple[int, Any]:
        """Route one request; unknown path → 404, known path with another method → 405."""
        handler = self.routes.get((request.method, request.path))
        if handler is None:
            if any(path == request.path for _, path in self.routes):
                return 405, {"error": "method not allowed"}
            return 404, {"error": "not found"}
        try:
            return handler(request)
        except Exception:
            logger.exception("control api handler failed: %s %s", request.method, request.path)
            return 500, {"error": "internal error; details are in the log"}

    def _health(self, request: ControlRequest) -> tuple[int, Any]:
        uptime = round(time.monotonic() - self._started, 1)
        return 200, {"ok": True, "pid": os.getpid(), "uptime_s": uptime}

    def _status(self, request: ControlRequest) -> tuple[int, Any]:
        return 200, self.status_provider()
