"""Public test helpers: an offline spine and an offline network.

- :class:`FakeSpine` implements the spine of protocol v1 in memory: the public endpoints of §4
  (``GET /``, ``GET /.well-known/tau.json``, ``POST /net/inbox`` with every check, in order) and
  the hub API of §5 (``/hub/health``, ``/hub/card``, ``/hub/updates`` with a real long poll,
  ``/hub/ack``), plus the cloud-mode ``/hub/state/<key>`` and ``/hub/files`` routes, which
  answer ``404 cloud_mode_off`` unless ``mode="cloud"``. Other routes (the ``/hub/sessions``
  API, ``/hub/brain``) can be added with :meth:`FakeSpine.route`. A ``FakeSpine`` is itself a
  :class:`~tau_net.spine.Transport` that only reaches its own address.
- :class:`FakeNetwork` is a :class:`~tau_net.spine.Transport` that routes each request by host
  to one of several fake spines, so tests run two taus that talk to each other with no socket.
  It refuses ``http`` to any host but ``localhost``/``127.0.0.1``, like a careful client must,
  and a spine on those two hosts speaks only ``http`` (a development spine has no TLS).

Both are thread-safe: the hub calls the transport from worker threads.
"""

from __future__ import annotations

import hmac
import json
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from tau_net.encoding import (
    INSECURE_HOSTS,
    EncodingError,
    b64u_decode,
    base_url,
    is_valid_address,
)
from tau_net.envelope import (
    MAX_ENVELOPE_BYTES,
    BadSignature,
    Envelope,
    EnvelopeError,
    Payload,
    verify_signature,
)
from tau_net.peers import CARD_PATH, CARD_TIMEOUT, MAX_CARD_BYTES
from tau_net.spine import STATE_KEY_PATTERN, TransportError

__all__ = [
    "DEFAULT_HUB_TOKEN",
    "FILE_NAMES",
    "FakeNetwork",
    "FakeRequest",
    "FakeSpine",
]

DEFAULT_HUB_TOKEN = "test-hub-token"
FILE_NAMES = ("tau.toml", "persona/persona.md", "persona/user.md", "persona/net.md")
"""The files a cloud-mode spine keeps (``/hub/files/<name>``)."""
STALE_SECONDS = 300
PEER_CACHE_SECONDS = 3600
RATE_PER_HOUR = 60
MAILBOX_LIMIT = 1000
MAX_STATE_BYTES = 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
NAME_LIMIT = 80
VERSION = "0.1.0"

Response = tuple[int, dict[str, str], bytes]


@dataclass(frozen=True)
class FakeRequest:
    """One request as a route handler sees it."""

    method: str
    path: str
    query: dict[str, str]
    headers: Mapping[str, str]
    body: bytes
    match: re.Match[str] | None = None

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None


RouteHandler = Callable[[FakeRequest], tuple[int, Any]]
"""``request → (status, payload)``; a ``str`` or ``bytes`` payload is sent as text."""


def _json(status: int, payload: Any, headers: Mapping[str, str] | None = None) -> Response:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, {"content-type": "application/json", **(headers or {})}, body


def _error(status: int, code: str, detail: str | None = None) -> Response:
    payload: dict[str, Any] = {"error": code}
    if detail is not None:
        payload["detail"] = detail
    return _json(status, payload)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _key32(value: Any) -> bool:
    try:
        return isinstance(value, str) and len(b64u_decode(value)) == 32
    except EncodingError:
        return False


@dataclass
class _Mail:
    seq: int
    received_at: int
    envelope: dict[str, str]
    sender: str
    id: str


@dataclass
class _Route:
    method: str
    pattern: re.Pattern[str]
    handler: RouteHandler
    auth: bool = True


class FakeSpine:
    """An in-memory spine for ``address`` (see the module doc).

    ``hub_token=""`` behaves like a spine without the ``HUB_TOKEN`` secret (``503
    not_configured``); ``allow_insecure_peers`` is ``ALLOW_INSECURE_PEERS=1``; ``clock`` gives
    Unix seconds; ``max_wait`` caps a long poll (seconds) for impatient tests.
    Inspect :attr:`card`, :attr:`mailbox`, :attr:`seen`, :attr:`state`, :attr:`files`,
    :attr:`acked` and :attr:`requests`; script failures with :meth:`fail`; set :attr:`down` to
    make the network unable to reach it.
    """

    def __init__(
        self,
        address: str,
        *,
        hub_token: str = DEFAULT_HUB_TOKEN,
        mode: str = "local",
        allow_insecure_peers: bool = False,
        clock: Callable[[], float] = time.time,
        network: FakeNetwork | None = None,
        max_wait: float | None = None,
        software: str = f"tau-spine/{VERSION}",
    ):
        if not is_valid_address(address):
            raise ValueError(f"not a tau address: {address!r}")
        if mode not in ("local", "cloud"):
            raise ValueError("mode must be 'local' or 'cloud'")
        self.address = address
        self.hub_token = hub_token
        self.mode = mode
        self.allow_insecure_peers = allow_insecure_peers
        self.clock = clock
        self.network = network
        self.max_wait = max_wait
        self.software = software
        self.card: dict[str, Any] | None = None
        self.mailbox: list[_Mail] = []
        self.seen: dict[tuple[str, str], int] = {}
        self.arrivals: dict[str, list[int]] = {}
        self.state: dict[str, dict[str, Any]] = {}
        self.files: dict[str, dict[str, Any]] = {}
        self.acked: list[int] = []
        self.requests: list[tuple[str, str]] = []
        self.peer_cache: dict[str, tuple[dict[str, Any], int]] = {}
        self.down = False
        self._next_seq = 1
        self._cond = threading.Condition(threading.RLock())
        self._failures: list[tuple[str, str, Response]] = []
        self._routes: list[_Route] = []
        self._install_routes()

    def __repr__(self) -> str:
        return f"FakeSpine({self.address!r}, mode={self.mode!r})"

    # -- scripting and inspection --------------------------------------------------------------

    @property
    def scheme(self) -> str:
        return "http" if self.address.split(":")[0] in INSECURE_HOSTS else "https"

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.address}"

    def fail(self, method: str, path: str, *answers: tuple[int, Any] | BaseException) -> None:
        """The next requests of ``method`` to ``path`` (a prefix) get these answers in order:
        ``(status, json payload)`` or an exception the network raises (``ConnectionError``)."""
        for answer in answers:
            if isinstance(answer, BaseException):
                self._failures.append((method, path, answer))  # type: ignore[arg-type]
            else:
                status, payload = answer
                self._failures.append((method, path, _json(status, payload)))

    def route(self, method: str, pattern: str, handler: RouteHandler, *, auth: bool = True) -> None:
        """Add (in front of the built-in ones) a route: ``pattern`` is a regex matched against
        the whole path; ``auth`` requires the hub token like every ``/hub/*`` route."""
        self._routes.insert(0, _Route(method, re.compile(pattern), handler, auth))

    def pending(self) -> list[dict[str, Any]]:
        """The undelivered mailbox as ``GET /hub/updates`` would return it."""
        with self._cond:
            return [self._update(mail) for mail in self.mailbox]

    def enqueue(self, envelope: Mapping[str, Any]) -> int:
        """Put a raw envelope into the mailbox *without* the inbox checks (a spine that lies
        or was compromised), so tests reach the hub's own checks; returns its ``seq``."""
        with self._cond:
            seq = self._next_seq
            self._next_seq += 1
            self.mailbox.append(_Mail(seq, int(self.clock()), dict(envelope), "?", "?"))
            self._cond.notify_all()
            return seq

    def publish(self, name: str, sign_key: str, box_key: str) -> dict[str, Any]:
        """Set the card directly (what ``PUT /hub/card`` does)."""
        with self._cond:
            self.card = {
                "v": 1,
                "address": self.address,
                "name": name,
                "sign_key": sign_key,
                "box_key": box_key,
                "inbox": f"{self.url}/net/inbox",
                "software": self.software,
            }
            return dict(self.card)

    # -- the transport -------------------------------------------------------------------------

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """Use the spine alone as a transport (it reaches only its own address)."""
        host = urllib.parse.urlsplit(url).netloc
        if host != self.address:
            raise TransportError(f"no route to {host}")
        return self.handle(method, url, headers, body)

    def handle(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> Response:
        """Answer one request (``url`` may be a full URL or a path with a query)."""
        parts = urllib.parse.urlsplit(url)
        path = parts.path or "/"
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parts.query).items()}
        with self._cond:
            self.requests.append((method, path))
            for i, (f_method, f_path, answer) in enumerate(self._failures):
                if f_method == method and path.startswith(f_path):
                    del self._failures[i]
                    if isinstance(answer, BaseException):
                        raise answer
                    return answer
        lowered = {str(k).lower(): str(v) for k, v in headers.items()}
        request = FakeRequest(method, path, query, lowered, body or b"")
        for route in self._routes:
            match = route.pattern.fullmatch(path)
            if match is None or route.method != method:
                continue
            if route.auth:
                denied = self._authorize(lowered)
                if denied is not None:
                    return denied
            request = FakeRequest(method, path, query, lowered, body or b"", match)
            status, payload = route.handler(request)
            if isinstance(payload, tuple):  # a full response from a built-in route
                return payload  # type: ignore[return-value]
            if isinstance(payload, bytes | str):
                data = payload.encode("utf-8") if isinstance(payload, str) else payload
                return status, {"content-type": "text/plain; charset=utf-8"}, data
            return _json(status, payload)
        if path.startswith("/hub/"):
            denied = self._authorize(lowered)
            if denied is not None:
                return denied
        return _error(404, "not_found")

    def _authorize(self, headers: Mapping[str, str]) -> Response | None:
        if not self.hub_token:
            return _error(503, "not_configured")
        given = headers.get("authorization", "")
        expected = f"Bearer {self.hub_token}"
        if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
            return _error(401, "unauthorized")
        return None

    # -- routes --------------------------------------------------------------------------------

    def _install_routes(self) -> None:
        add = self._routes.append
        add(_Route("GET", re.compile(r"/"), self._root, auth=False))
        add(_Route("GET", re.compile(r"/\.well-known/tau\.json"), self._card, auth=False))
        add(_Route("POST", re.compile(r"/net/inbox"), self._inbox, auth=False))
        add(_Route("GET", re.compile(r"/hub/health"), self._health))
        add(_Route("PUT", re.compile(r"/hub/card"), self._put_card))
        add(_Route("GET", re.compile(r"/hub/updates"), self._updates))
        add(_Route("POST", re.compile(r"/hub/ack"), self._ack))
        state = re.compile(r"/hub/state/(?P<key>[^/]+)")
        add(_Route("GET", state, self._cloud(self._state_get)))
        add(_Route("PUT", state, self._cloud(self._state_put)))
        add(_Route("DELETE", state, self._cloud(self._state_delete)))
        add(_Route("GET", re.compile(r"/hub/files"), self._cloud(self._files_list)))
        files = re.compile(r"/hub/files/(?P<name>.+)")
        add(_Route("GET", files, self._cloud(self._file_get)))
        add(_Route("PUT", files, self._cloud(self._file_put)))
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            add(_Route(method, re.compile(r"/hub/(sessions|brain)(/.*)?"), self._cloud(None)))

    def _cloud(self, handler: RouteHandler | None) -> RouteHandler:
        def guarded(request: FakeRequest) -> tuple[int, Any]:
            if self.mode != "cloud":
                return 404, _error(404, "cloud_mode_off")
            if handler is None:
                return 501, _error(501, "not_implemented", "add it with FakeSpine.route()")
            return handler(request)

        return guarded

    def _root(self, request: FakeRequest) -> tuple[int, Any]:
        return 200, f"tau spine {self.address}"

    def _card(self, request: FakeRequest) -> tuple[int, Any]:
        with self._cond:
            card = dict(self.card) if self.card else None
        if card is None:
            return 404, _error(404, "no_card")
        headers = {"access-control-allow-origin": "*", "cache-control": "public, max-age=300"}
        return 200, _json(200, card, headers)

    def _health(self, request: FakeRequest) -> tuple[int, Any]:
        with self._cond:
            return 200, {
                "ok": True,
                "address": self.address,
                "mode": self.mode,
                "card": self.card is not None,
                "mailbox": len(self.mailbox),
                "version": VERSION,
            }

    def _put_card(self, request: FakeRequest) -> tuple[int, Any]:
        try:
            data = request.json()
        except ValueError:
            return 400, _error(400, "bad_request", "body is not JSON")
        if not isinstance(data, dict):
            return 400, _error(400, "bad_request", "body is not an object")
        name = data.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= NAME_LIMIT:
            return 400, _error(400, "bad_request", "name must be 1-80 characters")
        for key in ("sign_key", "box_key"):
            if not _key32(data.get(key)):
                return 400, _error(400, "bad_request", f"{key} must be 32 bytes of base64url")
        return 200, self.publish(name, data["sign_key"], data["box_key"])

    def _update(self, mail: _Mail) -> dict[str, Any]:
        return {"seq": mail.seq, "received_at": mail.received_at, "envelope": dict(mail.envelope)}

    def _updates(self, request: FakeRequest) -> tuple[int, Any]:
        try:
            after = int(request.query.get("after", "0"))
            timeout = int(request.query.get("timeout", "0"))
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            return 400, _error(400, "bad_request", "after, timeout and limit are integers")
        if not 0 <= timeout <= 25 or not 1 <= limit <= 100 or after < 0:
            return 400, _error(400, "bad_request", "timeout 0..25, limit 1..100")
        wait = float(timeout) if self.max_wait is None else min(float(timeout), self.max_wait)

        def ready() -> list[_Mail]:
            return [mail for mail in self.mailbox if mail.seq > after]

        with self._cond:
            if not ready() and wait > 0:
                self._cond.wait_for(lambda: bool(ready()), timeout=wait)
            return 200, {"updates": [self._update(mail) for mail in ready()[:limit]]}

    def _ack(self, request: FakeRequest) -> tuple[int, Any]:
        try:
            data = request.json()
        except ValueError:
            data = None
        seqs = data.get("seqs") if isinstance(data, dict) else None
        if not isinstance(seqs, list) or not all(_is_int(seq) for seq in seqs):
            return 400, _error(400, "bad_request", "seqs must be a list of integers")
        with self._cond:
            before = len(self.mailbox)
            self.mailbox = [mail for mail in self.mailbox if mail.seq not in set(seqs)]
            self.acked.extend(seqs)
            return 200, {"deleted": before - len(self.mailbox)}

    # -- the inbox (§4) ------------------------------------------------------------------------

    def _sender_card(self, sender: str, now: int) -> dict[str, Any] | None:
        with self._cond:
            cached = self.peer_cache.get(sender)
            if cached is not None and now - cached[1] < PEER_CACHE_SECONDS:
                return cached[0]
        if self.network is None:
            return None
        url = base_url(sender, allow_insecure=self.allow_insecure_peers) + CARD_PATH
        try:
            status, _, body = self.network(
                "GET", url, {"accept": "application/json"}, None, CARD_TIMEOUT
            )
        except OSError:
            return None
        if status != 200 or len(body) > MAX_CARD_BYTES:
            return None
        try:
            card = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if (
            not isinstance(card, dict)
            or card.get("v") != 1
            or card.get("address") != sender
            or not _key32(card.get("sign_key"))
        ):
            return None
        with self._cond:
            self.peer_cache[sender] = (card, now)
        return card

    def _inbox(self, request: FakeRequest) -> tuple[int, Any]:
        body = request.body
        if len(body) > MAX_ENVELOPE_BYTES:
            return 413, _error(413, "too_large")
        try:
            raw = json.loads(body.decode("utf-8"))
            envelope = Envelope.from_json(raw)
            payload_bytes = envelope.payload_bytes
            payload = Payload.from_json(json.loads(payload_bytes.decode("utf-8")))
        except (UnicodeDecodeError, ValueError) as exc:
            detail = exc.reason if isinstance(exc, EnvelopeError) else "body is not JSON"
            return 400, _error(400, "bad_request", detail)
        if payload.recipient != self.address:
            return 400, _error(400, "wrong_recipient")
        now = int(self.clock())
        if abs(now - payload.ts) > STALE_SECONDS:
            return 400, _error(400, "stale")
        card = self._sender_card(payload.sender, now)
        if card is None:
            return 502, _error(502, "sender_card_unavailable")
        try:
            verify_signature(card["sign_key"], payload_bytes, envelope.sig_bytes)
        except BadSignature:
            return 403, _error(403, "bad_signature")
        key = (payload.sender, payload.id)
        with self._cond:
            if key in self.seen:
                return 200, {"status": "duplicate", "id": payload.id}
            recent = [t for t in self.arrivals.get(payload.sender, []) if now - t < 3600]
            if len(recent) >= RATE_PER_HOUR:
                return 429, _error(429, "rate_limited")
            if len(self.mailbox) >= MAILBOX_LIMIT:
                return 503, _error(503, "mailbox_full")
            self.seen[key] = payload.ts
            self.arrivals[payload.sender] = [*recent, now]
            self.mailbox.append(
                _Mail(self._next_seq, now, envelope.to_json(), payload.sender, payload.id)
            )
            self._next_seq += 1
            self._cond.notify_all()
        return 202, {"status": "queued", "id": payload.id}

    # -- cloud mode: state and files -----------------------------------------------------------

    def _state_key(self, request: FakeRequest) -> str | None:
        key = request.match.group("key") if request.match else ""
        return key if STATE_KEY_PATTERN.fullmatch(key) else None

    def _state_get(self, request: FakeRequest) -> tuple[int, Any]:
        key = self._state_key(request)
        if key is None:
            return 400, _error(400, "bad_request", "invalid key")
        with self._cond:
            entry = self.state.get(key)
            if entry is None:
                return 404, _error(404, "not_found")
            return 200, {"key": key, "value": entry["value"], "updated_at": entry["updated_at"]}

    def _state_put(self, request: FakeRequest) -> tuple[int, Any]:
        key = self._state_key(request)
        if key is None:
            return 400, _error(400, "bad_request", "invalid key")
        if len(request.body) > MAX_STATE_BYTES:
            return 413, _error(413, "too_large")
        try:
            data = request.json()
        except ValueError:
            return 400, _error(400, "bad_request", "body is not JSON")
        if not isinstance(data, dict) or "value" not in data:
            return 400, _error(400, "bad_request", "body needs a value")
        now = int(self.clock())
        with self._cond:
            self.state[key] = {"value": data["value"], "updated_at": now}
        return 200, {"key": key, "updated_at": now}

    def _state_delete(self, request: FakeRequest) -> tuple[int, Any]:
        key = self._state_key(request)
        if key is None:
            return 400, _error(400, "bad_request", "invalid key")
        with self._cond:
            return 200, {"deleted": self.state.pop(key, None) is not None}

    def _files_list(self, request: FakeRequest) -> tuple[int, Any]:
        with self._cond:
            return 200, {
                "files": [
                    {
                        "name": name,
                        "size": len(entry["text"].encode()),
                        "updated_at": entry["updated_at"],
                    }
                    for name, entry in sorted(self.files.items())
                ]
            }

    def _file_name(self, request: FakeRequest) -> str | None:
        name = urllib.parse.unquote(request.match.group("name")) if request.match else ""
        return name if name in FILE_NAMES else None

    def _file_get(self, request: FakeRequest) -> tuple[int, Any]:
        name = self._file_name(request)
        with self._cond:
            if name is None or name not in self.files:
                return 404, _error(404, "not_found")
            return 200, self.files[name]["text"]

    def _file_put(self, request: FakeRequest) -> tuple[int, Any]:
        name = self._file_name(request)
        if name is None:
            return 404, _error(404, "not_found")
        if len(request.body) > MAX_FILE_BYTES:
            return 413, _error(413, "too_large")
        try:
            text = request.body.decode("utf-8")
        except UnicodeDecodeError:
            return 400, _error(400, "bad_request", "body is not UTF-8")
        now = int(self.clock())
        with self._cond:
            self.files[name] = {"text": text, "updated_at": now}
        return 200, {"name": name, "size": len(request.body), "updated_at": now}


class FakeNetwork:
    """A :class:`~tau_net.spine.Transport` that routes by host to fake spines.

    ``FakeNetwork([alice, bob])`` or :meth:`add`; :attr:`requests` records ``(method, url)``;
    hosts in :attr:`down` (or spines with ``down = True``) raise a network error.
    """

    def __init__(self, spines: Iterable[FakeSpine] = ()):
        self.spines: dict[str, FakeSpine] = {}
        self.requests: list[tuple[str, str]] = []
        self.down: set[str] = set()
        self._lock = threading.Lock()
        for spine in spines:
            self.add(spine)

    def __repr__(self) -> str:
        return f"FakeNetwork({sorted(self.spines)})"

    def add(self, spine: FakeSpine) -> FakeSpine:
        spine.network = self
        self.spines[spine.address] = spine
        return spine

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc
        with self._lock:
            self.requests.append((method, url))
        if parts.scheme == "http" and parts.hostname not in INSECURE_HOSTS:
            raise TransportError(f"plain http to {host} refused")
        if parts.scheme not in ("http", "https"):
            raise TransportError(f"unsupported scheme {parts.scheme!r}")
        spine = self.spines.get(host)
        if spine is None:
            raise TransportError(f"no route to {host}")
        if host in self.down or spine.down:
            raise TransportError(f"connection to {host} refused")
        if parts.scheme != spine.scheme:  # a development spine on localhost has no TLS
            raise TransportError(f"{host} does not speak {parts.scheme}")
        return spine.handle(method, url, headers, body)
