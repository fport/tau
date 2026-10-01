"""The HTTP side of the web service: the turn protocol's routes and the built app.

Every request passes the door, in this order:

1. ``Host`` must be loopback, the bind address or one of ``[component.web] hostnames``
   (no DNS rebinding);
2. with the Access check on, a valid ``Cf-Access-Jwt-Assertion``;
3. any request that is not ``GET``/``HEAD`` must carry ``Origin`` with the same host (no other
   site can post to ``127.0.0.1``);
4. every ``/api`` route but ``/api/pair`` needs a paired device's key in the ``tau_device``
   cookie (``HttpOnly; SameSite=Strict``).

The app's own files (the bundle of ``apps/web``) are public: they hold no data. Routes are
those of ``docs/reference/turn-protocol.md`` under ``/api``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send
from tau_core.turn_protocol import encode

from tau_web.access import HEADER as ACCESS_HEADER
from tau_web.access import AccessVerifier
from tau_web.devices import Device, DeviceError, DeviceRegistry
from tau_web.settings import WebSettings
from tau_web.turns import Runtime, Turn, TurnError

logger = logging.getLogger(__name__)

COOKIE = "tau_device"
COOKIE_MAX_AGE = 400 * 24 * 3600
NDJSON = "application/x-ndjson"
MAX_BODY = 1_000_000

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-src 'self' about:",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "object-src 'none'",
    ]
)
SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}

PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>tau</title></head>
<body style="background:#050505;color:#f3eee6;font-family:system-ui;padding:2rem">
<h1>tau</h1><p>The web app is not built into this tau-web yet. The API is running.</p>
</body></html>"""


def _host(value: str | None) -> str:
    """The host of a ``Host`` header or an origin's netloc, lower case, without the port."""
    host = (value or "").strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1] if "]" in host else host
    return host.rsplit(":", 1)[0] if ":" in host else host


class Door:
    """The checks in front of every request (see the module docstring)."""

    def __init__(
        self,
        settings: WebSettings,
        devices: DeviceRegistry,
        access: AccessVerifier | None = None,
    ) -> None:
        self.settings = settings
        self.devices = devices
        self.access = access
        self.hosts = settings.allowed_hosts()

    def host_ok(self, headers: dict[str, str]) -> bool:
        return _host(headers.get("host")) in self.hosts

    def origin_ok(self, request: Request) -> bool:
        if request.method in ("GET", "HEAD"):
            return True
        origin = request.headers.get("origin")
        if not origin:
            return False
        return _host(urlsplit(origin).netloc) == _host(request.headers.get("host"))

    def device(self, request: Request) -> Device | None:
        device = self.devices.verify(request.cookies.get(COOKIE))
        if device is not None:
            try:
                self.devices.touch(device)
            except (OSError, DeviceError):
                logger.warning("web: could not record when device %s was seen", device.id)
        return device


class DoorMiddleware:
    """Host and Access checks for every HTTP request, before any route runs."""

    def __init__(self, app: ASGIApp, door: Door) -> None:
        self.app = app
        self.door = door

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if not self.door.host_ok(headers):
            await JSONResponse({"error": "unknown host"}, status_code=421)(scope, receive, send)
            return
        access = self.door.access
        if access is not None and not await access.verify(headers.get(ACCESS_HEADER)):
            await JSONResponse({"error": "Access token missing or invalid"}, status_code=403)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": message}, status_code=status, headers={"cache-control": "no-store"}
    )


async def _json_body(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_BODY:
        raise TurnError(413, "The request is too large.")
    try:
        data = json.loads(body or b"{}")
    except ValueError as exc:
        raise TurnError(400, "The body is not JSON.") from exc
    if not isinstance(data, dict):
        raise TurnError(400, "The body must be a JSON object.")
    return data


def _secure(request: Request) -> bool:
    if request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https":
        return True
    return _host(request.headers.get("host")) not in ("127.0.0.1", "localhost", "[::1]")


async def _ndjson(turn: Turn, after: int) -> AsyncIterator[str]:
    async for event in turn.read(after):
        yield encode(event)


def _stream(turn: Turn, after: int = -1) -> StreamingResponse:
    return StreamingResponse(
        _ndjson(turn, after),
        media_type=NDJSON,
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


def create_app(
    *,
    settings: WebSettings,
    devices: DeviceRegistry,
    runtime: Runtime,
    capabilities: Callable[[], dict[str, Any]],
    static_dir: Path | None = None,
    access: AccessVerifier | None = None,
) -> ASGIApp:
    door = Door(settings, devices, access)

    def api(handler: Callable[..., Any], *, device: bool = True) -> Callable[[Request], Any]:
        async def endpoint(request: Request) -> Response:
            if not door.origin_ok(request):
                return _error(403, "cross-site request refused")
            found = None
            if device:
                found = door.device(request)
                if found is None:
                    return _error(401, "pair this browser first: tau web device add <name>")
            try:
                return await handler(request, found)
            except TurnError as exc:
                return _error(exc.status, str(exc))
            except DeviceError as exc:
                return _error(400, str(exc))
            except ValueError as exc:  # an invalid session id from the store
                return _error(400, str(exc))

        return endpoint

    async def pair(request: Request, _: Device | None) -> Response:
        data = await _json_body(request)
        found, key = devices.pair(str(data.get("code") or ""))
        response = JSONResponse({"device": found.public()}, headers={"cache-control": "no-store"})
        response.set_cookie(
            COOKIE,
            key,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="strict",
            secure=_secure(request),
            path="/",
        )
        return response

    async def get_capabilities(request: Request, found: Device | None) -> Response:
        assert found is not None
        return JSONResponse({**capabilities(), "device": found.public()})

    async def list_sessions(request: Request, _: Device | None) -> Response:
        return JSONResponse(
            {"sessions": runtime.list_sessions()}, headers={"cache-control": "no-store"}
        )

    async def get_session(request: Request, _: Device | None) -> Response:
        return JSONResponse(runtime.history(request.path_params["session"]))

    async def post_turn(request: Request, found: Device | None) -> Response:
        assert found is not None
        data = await _json_body(request)
        session = data.get("session")
        if session is not None and not isinstance(session, str):
            raise TurnError(400, "session must be a session id")
        turn = await runtime.start(session, data.get("text"), found.id)
        return _stream(turn)

    async def get_turn(request: Request, _: Device | None) -> Response:
        try:
            after = int(request.query_params.get("after", "-1"))
        except ValueError as exc:
            raise TurnError(400, "after must be a number") from exc
        return _stream(runtime.turn(request.path_params["turn"]), after)

    async def cancel_turn(request: Request, _: Device | None) -> Response:
        runtime.cancel(request.path_params["turn"])
        return Response(status_code=204)

    async def decide(request: Request, _: Device | None) -> Response:
        data = await _json_body(request)
        runtime.decide(request.path_params["request"], str(data.get("decision") or ""))
        return Response(status_code=204)

    async def page(request: Request) -> Response:
        if request.url.path.startswith("/api/"):
            return _error(404, "no such route")
        if static_dir is None or not (static_dir / "index.html").is_file():
            return HTMLResponse(PLACEHOLDER, headers=SECURITY_HEADERS)
        root = static_dir.resolve()
        wanted = (root / request.url.path.lstrip("/")).resolve()
        if wanted.is_relative_to(root) and wanted.is_file():
            return FileResponse(wanted, headers=SECURITY_HEADERS)
        return FileResponse(
            root / "index.html", headers={**SECURITY_HEADERS, "cache-control": "no-cache"}
        )

    routes = [
        Route("/api/pair", api(pair, device=False), methods=["POST"]),
        Route("/api/capabilities", api(get_capabilities), methods=["GET"]),
        Route("/api/sessions", api(list_sessions), methods=["GET"]),
        Route("/api/sessions/{session}", api(get_session), methods=["GET"]),
        Route("/api/turns", api(post_turn), methods=["POST"]),
        Route("/api/turns/{turn}", api(get_turn), methods=["GET"]),
        Route("/api/turns/{turn}/cancel", api(cancel_turn), methods=["POST"]),
        Route("/api/approvals/{request}", api(decide), methods=["POST"]),
        Route("/{path:path}", page, methods=["GET", "HEAD"]),
    ]
    return DoorMiddleware(Starlette(routes=routes), door)
