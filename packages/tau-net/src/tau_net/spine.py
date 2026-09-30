"""A client for a spine's hub API (protocol v1, §5), shared by tau-net and tau-cloud.

- :class:`Transport` is the one seam for HTTP: ``(method, url, headers, body, timeout) ->
  (status, headers, body)``. It returns every HTTP status as a value and raises only when no
  answer arrived (``OSError``; :class:`TransportError` from :class:`UrllibTransport`).
  :class:`tau_net.testing.FakeNetwork` is the offline stand-in.
- :class:`UrllibTransport` is the standard library over the network: no proxy for loopback
  hosts, redirects are never followed (a redirect would carry the bearer token elsewhere) and
  answers are capped in size.
- :class:`SpineClient` adds the base URL and ``Authorization: Bearer <token>``;
  :meth:`SpineClient.doorbell` builds the WebSocket doorbell of ``GET /hub/ws``
  (:mod:`tau_net.doorbell`).
  :meth:`SpineClient.request` never raises for an HTTP status (it returns a
  :class:`SpineResponse`); :meth:`SpineClient.call` raises :class:`SpineError` for a non-2xx
  answer and returns the parsed JSON. Both raise :class:`SpineUnreachable` (a
  :class:`SpineError` with ``status == 0``) when the transport failed.

The token never appears in a repr, a log line or an exception message: exception texts are
built from the status, the spine's ``error`` code and its ``detail``, with the token masked.
"""

from __future__ import annotations

import http.client
import json as jsonlib
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from tau_net.doorbell import WebSocketDoorbell

__all__ = [
    "DEFAULT_TIMEOUT",
    "MAX_POLL_TIMEOUT",
    "STATE_KEY_PATTERN",
    "SpineClient",
    "SpineError",
    "SpineResponse",
    "SpineUnreachable",
    "Transport",
    "TransportError",
    "Update",
    "UrllibTransport",
]

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_POLL_TIMEOUT = 25
"""The longest ``GET /hub/updates`` wait a spine grants."""
STATE_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")
USER_AGENT = "tau-net/0.1.0"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class Transport(Protocol):
    """One HTTP exchange. ``headers`` of the answer may use any case; callers look them up
    case-insensitively. Raises ``OSError`` only when there is no answer at all."""

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]: ...


class TransportError(ConnectionError):
    """No HTTP answer: DNS, connection, TLS, timeout, or an answer larger than allowed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None  # urllib then raises HTTPError with the 3xx, returned as a status


class UrllibTransport:
    """:class:`Transport` over ``urllib`` (no extra dependency)."""

    def __init__(self, *, max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES):
        self.max_response_bytes = max_response_bytes
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._proxied = urllib.request.build_opener(_NoRedirect())

    def __repr__(self) -> str:
        return f"UrllibTransport(max_response_bytes={self.max_response_bytes})"

    def _read(self, response: Any) -> bytes:
        data = response.read(self.max_response_bytes + 1)
        if len(data) > self.max_response_bytes:
            raise TransportError(f"answer larger than {self.max_response_bytes} bytes")
        return data

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        parts = urllib.parse.urlsplit(url)
        where = f"{method} {parts.scheme}://{parts.netloc}{parts.path}"
        if parts.scheme not in ("http", "https"):
            raise TransportError(f"{where}: unsupported scheme")
        opener = self._direct if parts.hostname in LOOPBACK_HOSTS else self._proxied
        request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, _lower(response.headers.items()), self._read(response)
        except urllib.error.HTTPError as exc:
            try:
                data = self._read(exc)
            except (OSError, http.client.HTTPException):
                data = b""
            return exc.code, _lower((exc.headers or {}).items()), data
        except TransportError:
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise TransportError(f"{where}: {type(exc).__name__}: {reason}") from None


def _lower(items: Any) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in items}


# -- responses and errors ----------------------------------------------------------------------


class SpineError(Exception):
    """A spine that said no (``status`` ≥ 300) or did not answer (``status == 0``).

    ``code`` is the ``error`` field of the answer (``unauthorized``, ``cloud_mode_off``, …) or
    ``http_<status>``; ``detail`` is its ``detail`` field or the start of the body.
    """

    def __init__(self, status: int, code: str, detail: str = ""):
        self.status = status
        self.code = code
        self.detail = detail
        text = f"spine answered {status} {code}" if status else f"spine unreachable: {detail}"
        if status and detail:
            text += f": {detail}"
        super().__init__(text)


class SpineUnreachable(SpineError):
    """No answer from the spine (network, DNS, TLS, timeout)."""

    def __init__(self, detail: str):
        super().__init__(0, "unreachable", detail)


@dataclass(frozen=True)
class SpineResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None

    def json(self) -> Any:
        """The body parsed as JSON (``None`` for an empty body); ``ValueError`` otherwise."""
        if not self.body:
            return None
        return jsonlib.loads(self.body.decode("utf-8"))

    def error(self) -> tuple[str, str]:
        """``(code, detail)`` from an error answer, with fallbacks for non-JSON bodies."""
        try:
            data = self.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            code = data.get("error")
            detail = data.get("detail")
            return (
                str(code) if code else f"http_{self.status}",
                str(detail) if detail is not None else "",
            )
        return f"http_{self.status}", " ".join(self.text.split())[:200]


@dataclass(frozen=True)
class Update:
    """One entry of ``GET /hub/updates``."""

    seq: int
    received_at: int
    envelope: dict[str, Any]


# -- the client --------------------------------------------------------------------------------


class SpineClient:
    """The hub API of one spine, authenticated with the hub token."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        parts = urllib.parse.urlsplit((url or "").strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("spine URL must be an http(s) URL such as https://tau.example.com")
        self.url = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"
        self._token = token or ""
        self.transport: Transport = transport or UrllibTransport()
        self.timeout = float(timeout)

    def __repr__(self) -> str:
        return f"SpineClient(url={self.url!r}, token=<hidden>)"

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.url).netloc

    def _mask(self, text: str) -> str:
        return text.replace(self._token, "<token>") if self._token else text

    # -- raw requests --------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        body: bytes | str | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        content_type: str | None = None,
    ) -> SpineResponse:
        """One request to ``path`` (starting with ``/``). ``json`` is sent as JSON; ``body``
        as UTF-8 text (``str``) or octets (``bytes``). Never raises for an HTTP status;
        :class:`SpineUnreachable` when no answer came."""
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        url = self.url + path
        if params:
            query = {k: v for k, v in params.items() if v is not None}
            if query:
                url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data: bytes | None = None
        if json is not None:
            data = jsonlib.dumps(json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body is not None:
            if isinstance(body, str):
                data = body.encode("utf-8")
                headers["Content-Type"] = "text/plain; charset=utf-8"
            else:
                data = bytes(body)
                headers["Content-Type"] = "application/octet-stream"
        if content_type:
            headers["Content-Type"] = content_type
        wait = self.timeout if timeout is None else float(timeout)
        try:
            status, answer_headers, answer = self.transport(method, url, headers, data, wait)
        except OSError as exc:
            raise SpineUnreachable(self._mask(str(exc) or type(exc).__name__)) from None
        return SpineResponse(int(status), dict(answer_headers or {}), bytes(answer or b""))

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        """:meth:`request`, then the parsed JSON of a 2xx answer; :class:`SpineError` else."""
        response = self.request(method, path, **kwargs)
        if not response.ok:
            code, detail = response.error()
            raise SpineError(response.status, self._mask(code), self._mask(detail))
        try:
            return response.json()
        except ValueError:
            raise SpineError(response.status, "bad_json", "the answer is not JSON") from None

    # -- both modes ----------------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """``GET /hub/health``: ``{"ok", "address", "mode", "card", "mailbox", "version"}``."""
        data = self.call("GET", "/hub/health")
        if not isinstance(data, dict):
            raise SpineError(200, "bad_json", "health is not an object")
        return data

    def card(self) -> dict[str, Any] | None:
        """The spine's public card (``GET /.well-known/tau.json``); ``None`` before one was
        published."""
        response = self.request("GET", "/.well-known/tau.json")
        if response.status == 404:
            return None
        if not response.ok:
            code, detail = response.error()
            raise SpineError(response.status, code, detail)
        try:
            data = response.json()
        except ValueError:
            raise SpineError(response.status, "bad_json", "the card is not JSON") from None
        if not isinstance(data, dict):
            raise SpineError(response.status, "bad_json", "the card is not an object")
        return data

    def publish_card(self, name: str, sign_key: str, box_key: str) -> dict[str, Any]:
        """``PUT /hub/card``; returns the full card as the spine serves it."""
        return self.call(
            "PUT", "/hub/card", json={"name": name, "sign_key": sign_key, "box_key": box_key}
        )

    def updates(self, after: int = 0, timeout: int = 0, limit: int = 50) -> list[Update]:
        """``GET /hub/updates``: envelopes with ``seq > after``, waiting up to ``timeout``
        seconds (0..25) when none is queued."""
        wait = max(0, min(int(timeout), MAX_POLL_TIMEOUT))
        data = self.call(
            "GET",
            "/hub/updates",
            params={"after": int(after), "timeout": wait, "limit": max(1, min(int(limit), 100))},
            timeout=wait + self.timeout,
        )
        raw = data.get("updates") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raise SpineError(200, "bad_json", "updates is not a list")
        updates: list[Update] = []
        for item in raw:
            seq = item.get("seq") if isinstance(item, dict) else None
            if not isinstance(seq, int) or isinstance(seq, bool):
                logger.warning("net: the spine sent an update without a seq; ignored")
                continue
            received = item.get("received_at")
            envelope = item.get("envelope")
            updates.append(
                Update(
                    seq=seq,
                    received_at=received if isinstance(received, int) else 0,
                    # a malformed envelope is still handed on: the hub drops and acknowledges it
                    envelope=envelope if isinstance(envelope, dict) else {},
                )
            )
        return sorted(updates, key=lambda update: update.seq)

    def ack(self, seqs: Sequence[int]) -> int:
        """``POST /hub/ack``; the number of envelopes the spine deleted."""
        data = self.call("POST", "/hub/ack", json={"seqs": [int(seq) for seq in seqs]})
        deleted = data.get("deleted") if isinstance(data, dict) else None
        return deleted if isinstance(deleted, int) else 0

    def doorbell(self) -> WebSocketDoorbell:
        """A (not yet connected) :class:`~tau_net.doorbell.WebSocketDoorbell` for this spine's
        ``GET /hub/ws``. It connects directly, without the transport or a proxy."""
        from tau_net.doorbell import WebSocketDoorbell

        return WebSocketDoorbell(self.url, self._token)

    # -- cloud mode: state ---------------------------------------------------------------------

    @staticmethod
    def _state_path(key: str) -> str:
        if not isinstance(key, str) or not STATE_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid state key: {key!r}")
        return f"/hub/state/{key}"

    def state_get(self, key: str, default: Any = None) -> Any:
        """The value stored under ``key``, ``default`` when there is none. A spine outside
        cloud mode raises :class:`SpineError` (``cloud_mode_off``)."""
        response = self.request("GET", self._state_path(key))
        if response.status == 404:
            code, detail = response.error()
            if code == "cloud_mode_off":
                raise SpineError(404, code, detail)
            return default
        if not response.ok:
            code, detail = response.error()
            raise SpineError(response.status, code, detail)
        try:
            data = response.json()
        except ValueError:
            raise SpineError(response.status, "bad_json", "state is not JSON") from None
        if not isinstance(data, dict) or "value" not in data:
            raise SpineError(response.status, "bad_json", "state has no value")
        return data["value"]

    def state_put(self, key: str, value: Any) -> str | None:
        """Store ``value`` under ``key``; returns the spine's ``updated_at``."""
        data = self.call("PUT", self._state_path(key), json={"value": value})
        return data.get("updated_at") if isinstance(data, dict) else None

    def state_delete(self, key: str) -> bool:
        """Delete ``key``; ``True`` when something was deleted."""
        data = self.call("DELETE", self._state_path(key))
        return bool(data.get("deleted")) if isinstance(data, dict) else False
