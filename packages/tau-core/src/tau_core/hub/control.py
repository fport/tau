"""The hub's local control API: JSON over HTTP on 127.0.0.1 only.

The tau app, hooks and other local processes read the hub's health and status here. The server is
the standard library's ``ThreadingHTTPServer`` in a background thread; it binds to 127.0.0.1
(never a public interface) and rejects requests whose ``Host`` header is not a loopback name,
so a web page cannot reach it through DNS rebinding.

Handlers run in the server's threads, not on the hub's event loop. A handler that needs the loop
uses ``asyncio.run_coroutine_threadsafe(coro, hub.loop)``. Later issues add routes additively
(``routes=`` or :meth:`ControlApi.add_route`) and extend ``/status`` through
``Hub.add_status_source``.

Routes are protected by default (ADR 0008): only ``GET /health`` and ``GET /status`` are open.
The token in ``hub_dir/control.token`` never travels: a client signs each protected request
with it (``X-Tau-Nonce`` plus ``X-Tau-Auth``, :func:`request_auth`) and the hub signs its answer
(``X-Tau-Proof``, :func:`response_proof`, a separate HMAC domain). The HTTP handler refuses a
protected request with 403 before dispatch when the token file is missing, empty or not this
hub's, when the nonce or ``X-Tau-Auth`` is missing or wrong, when an ``Origin`` header is
present, or when a body-carrying request is not ``application/json``. A process that binds the
port while the hub is down (a stale token file after a crash) therefore learns nothing it can
sign with, and a client refuses its unproven answers. :meth:`ControlApi.handle` itself does not
check, so unit tests route requests without a token.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import socketserver
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

from tau_core.hub.state import write_text_atomic

if TYPE_CHECKING:
    from tau_core.hub.daemon import Hub

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "[::1]"})
MAX_BODY_BYTES = 1024 * 1024
TOKEN_FILE = "control.token"
"""The control token, ``hub_dir/control.token`` (0600, in a 0700 ``hub_dir``)."""
OPEN_PATHS = frozenset({"/health", "/status"})
"""The only paths served without the token."""
MAX_NONCE_LENGTH = 128
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
NONCE_HEADER = "X-Tau-Nonce"
AUTH_HEADER = "X-Tau-Auth"
PROOF_HEADER = "X-Tau-Proof"


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


def _mac(token: str, domain: bytes, fields: tuple[str, ...], tail: bytes | None = None) -> str:
    message = b"|".join((domain, *(value.encode("utf-8") for value in fields)))
    if tail is not None:
        message += b"|" + tail
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def request_auth(token: str, nonce: str, method: str, path: str) -> str:
    """``hex(HMAC-SHA256(token, "req" | nonce | method | path))``, the ``X-Tau-Auth`` of a
    protected request; ``method`` is upper case and ``path`` has no query string."""
    return _mac(token, b"req", (nonce, method.upper(), path))


def response_proof(token: str, nonce: str, method: str, path: str, status: int, body: bytes) -> str:
    """``hex(HMAC-SHA256(token, "resp" | nonce | method | path | status | body))``, the
    ``X-Tau-Proof`` of a protected answer; ``path`` has no query string. The ``resp`` domain
    keeps a request's ``X-Tau-Auth`` from ever passing as a proof."""
    return _mac(token, b"resp", (nonce, method.upper(), path, str(status)), body)


def auth_headers(token: str, method: str, path: str, *, nonce: str | None = None) -> dict[str, str]:
    """``X-Tau-Nonce`` (fresh unless given) and ``X-Tau-Auth`` for one protected request."""
    nonce = secrets.token_hex(16) if nonce is None else nonce
    return {NONCE_HEADER: nonce, AUTH_HEADER: request_auth(token, nonce, method, path)}


def read_token(path: Path) -> str | None:
    """The token in ``path``, ``None`` when the file is missing, unreadable or empty."""
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token or None


def _is_json(content_type: str | None) -> bool:
    return (content_type or "").split(";", 1)[0].strip().lower() == "application/json"


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
            url = urlsplit(self.path)
            nonce = self.headers.get(NONCE_HEADER)
            if nonce is not None and not 0 < len(nonce) <= MAX_NONCE_LENGTH:
                self._send(400, {"error": "bad nonce"})
                return
            token: str | None = None
            if not api.is_open(method, url.path):
                token = api.authorize(method, url.path, self.headers)
                if token is None:
                    self._send(403, {"error": "forbidden"})
                    return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(413, {"error": "request body too large"})
                return
            body = self.rfile.read(length) if length else b""
            request = ControlRequest(
                method=method,
                path=url.path,
                query=parse_qs(url.query),
                headers={k.lower(): v for k, v in self.headers.items()},
                body=body,
            )
            status, payload = api.handle(request)
            proof = None
            if token is not None and nonce is not None:
                proof = (token, nonce, method, url.path)
            self._send(status, payload, proof)

        def _send(
            self, status: int, payload: Any, proof: tuple[str, str, str, str] | None = None
        ) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if proof is not None:
                token, nonce, method, path = proof
                self.send_header(
                    PROOF_HEADER, response_proof(token, nonce, method, path, status, data)
                )
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
    ``hub_dir`` is where the control token lives; ``start(hub)`` takes the hub's when it is not
    given. Without a token every protected route answers 403.
    """

    name = "control-api"

    def __init__(
        self,
        port: int,
        status_provider: Callable[[], dict[str, Any]],
        routes: dict[tuple[str, str], Handler] | None = None,
        *,
        hub_dir: Path | None = None,
    ):
        self.port = port
        self.status_provider = status_provider
        self.hub_dir = Path(hub_dir) if hub_dir is not None else None
        self.routes: dict[tuple[str, str], Handler] = {}
        self.open_routes: set[tuple[str, str]] = set()
        self.add_route("GET", "/health", self._health, open=True)
        self.add_route("GET", "/status", self._status, open=True)
        for (method, path), handler in (routes or {}).items():
            self.add_route(method, path, handler)
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._started = time.monotonic()
        self._token: str | None = None

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def add_route(self, method: str, path: str, handler: Handler, *, open: bool = False) -> None:
        """Register ``handler`` for ``method path``. Routes are additive only: a ``(method,
        path)`` that exists raises ``ValueError``, so a ``tau.hub_services`` component can
        neither replace ``GET /health`` / ``GET /status`` (which ``tau hub status``, ``tau
        doctor`` and the tau app trust) nor another component's route. A route is protected
        (signed requests, no ``Origin``, JSON bodies, response proof) unless ``open`` is set;
        only ``/health`` and ``/status`` are open in tau-core."""
        key = (method.upper(), path)
        if key in self.routes:
            raise ValueError(
                f"control api route {key[0]} {path} is already registered; routes cannot be "
                "replaced"
            )
        self.routes[key] = handler
        if open:
            self.open_routes.add(key)

    def is_open(self, method: str, path: str) -> bool:
        """Is ``method path`` served without the token? Unknown paths are protected."""
        return (method.upper(), path) in self.open_routes

    # -- the control token ----------------------------------------------------------------

    @property
    def token_path(self) -> Path | None:
        return self.hub_dir / TOKEN_FILE if self.hub_dir is not None else None

    def write_token(self) -> str:
        """Write a fresh token to ``hub_dir/control.token`` (0600; ``hub_dir`` chmod 0700).

        ``start(hub)`` calls it while the hub lock is held, so a second hub that lost the lock
        never touches the live token. The file is created exclusively and renamed into place.
        """
        path = self.token_path
        if path is None:
            raise ValueError("the control api has no hub_dir for its token")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        token = secrets.token_urlsafe(32)
        write_text_atomic(path, token, mode=0o600)
        self._token = token
        return token

    def remove_token(self) -> None:
        """Delete the token file, but only while it still holds this hub's token."""
        token, self._token = self._token, None
        path = self.token_path
        if token is None or path is None:
            return
        if read_token(path) == token:
            with suppress(FileNotFoundError):
                path.unlink()

    def authorize(self, method: str, path: str, headers: Mapping[str, str]) -> str | None:
        """The token when a protected request may pass, else ``None`` (the caller answers 403).

        Refused: no token of this hub in the token file, a missing ``X-Tau-Nonce``, a missing
        or wrong ``X-Tau-Auth`` (:func:`request_auth` over this method and path), any
        ``Origin`` header, a body-carrying request that is not ``application/json``. The raw
        token is never accepted in a header."""
        token = self._token
        token_path = self.token_path
        if token is None or token_path is None or read_token(token_path) != token:
            return None
        if headers.get("Origin") is not None:
            return None
        nonce = headers.get(NONCE_HEADER)
        if not nonce or len(nonce) > MAX_NONCE_LENGTH:
            return None
        given = headers.get(AUTH_HEADER) or ""
        expected = request_auth(token, nonce, method, path)
        if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
            return None
        if method.upper() in BODY_METHODS and not _is_json(headers.get("Content-Type")):
            return None
        return token

    # -- HubService -----------------------------------------------------------------------

    async def start(self, hub: Hub) -> None:
        if self.hub_dir is None and hub is not None:
            self.hub_dir = hub.files.dir
        if self.hub_dir is not None:
            self.write_token()  # before the port opens, so a client never finds it without one
        try:
            self.serve()
        except BaseException:
            self.remove_token()
            raise

    async def stop(self) -> None:
        await asyncio.to_thread(self.shutdown)
        self.remove_token()

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
