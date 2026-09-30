"""The brain container's health endpoint (``GET /health`` on ``0.0.0.0:8080``).

The spine drives the container through its Durable Object: it waits for this port, then
``GET /hub/brain`` and the keep-awake cron call ``/health`` here. The answer is::

    {"ok": true, "version": "<tau-cloud version>", "hub": <the hub's /status, or null>}

``hub`` is the JSON of the hub's local control API (``GET /status`` on 127.0.0.1) while the
hub answers, else ``null`` (starting, stopping). The server is the standard library's
``ThreadingHTTPServer`` in a daemon thread; it answers nothing but ``GET /health``.
"""

from __future__ import annotations

import json
import logging
import socketserver
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "HOST_ENV",
    "PORT_ENV",
    "HealthServer",
    "hub_status_reader",
]

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
"""The port the spine's ``TauBrain`` container class talks to (``defaultPort``)."""
PORT_ENV = "TAU_CLOUD_HEALTH_PORT"
HOST_ENV = "TAU_CLOUD_HEALTH_HOST"
"""Overrides the bind address, e.g. ``127.0.0.1`` when trying ``tau cloud run`` locally."""
STATUS_TIMEOUT = 2.0
MAX_STATUS_BYTES = 1024 * 1024

HubStatus = Callable[[], dict[str, Any] | None]


def hub_status_reader(port: int, *, timeout: float = STATUS_TIMEOUT) -> HubStatus:
    """A function returning the hub's ``GET http://127.0.0.1:<port>/status`` JSON, or
    ``None`` while the hub does not answer."""
    url = f"http://127.0.0.1:{port}/status"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def read() -> dict[str, Any] | None:
        try:
            with opener.open(url, timeout=timeout) as response:
                data = json.loads(response.read(MAX_STATUS_BYTES).decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            return None
        return data if isinstance(data, dict) else None

    return read


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks the host name up (a reverse DNS query); not needed.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class HealthServer:
    """``GET /health`` on ``host:port`` (``port=0`` binds an ephemeral port; :attr:`port`
    holds the bound one after :meth:`start`)."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        *,
        host: str = DEFAULT_HOST,
        version: str,
        hub_status: HubStatus | None = None,
    ):
        self.host = host
        self.port = port
        self.version = version
        self.hub_status = hub_status or (lambda: None)
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def __repr__(self) -> str:
        return f"HealthServer({self.host}:{self.port})"

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host == DEFAULT_HOST else self.host
        return f"http://{host}:{self.port}/health"

    def payload(self) -> dict[str, Any]:
        try:
            hub = self.hub_status()
        except Exception:
            logger.exception("reading the hub status failed")
            hub = None
        return {"ok": True, "version": self.version, "hub": hub}

    def start(self) -> None:
        """Bind and serve in a daemon thread. Raises ``OSError`` when the port is taken."""
        if self._server is not None:
            return
        server = _Server((self.host, self.port), _handler(self))
        self._server = server
        self.port = server.server_port
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="tau-cloud-health",
            daemon=True,
        )
        self._thread.start()
        logger.info("health endpoint listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


def _handler(health: HealthServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "tau-cloud"
        sys_version = ""
        timeout = 10

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] == "/health":
                self._send(200, health.payload())
            else:
                self._send(404, {"error": "not_found"})

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("health %s: %s", self.address_string(), format % args)

    return Handler
