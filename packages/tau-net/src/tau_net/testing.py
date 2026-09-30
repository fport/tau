"""Public test helpers: an offline spine, an offline universe and an offline network.

- :class:`FakeSpine` implements the spine of protocol v1 in memory: the public endpoints of §4
  (``GET /``, ``GET /.well-known/tau.json``, ``POST /net/inbox`` with every check, in order,
  except the Rate Limiting bindings of the real Worker) and
  the hub API of §5 (``/hub/health``, ``/hub/card``, ``/hub/updates`` with a real long poll,
  ``/hub/ack``), plus the cloud-mode ``/hub/state/<key>`` and ``/hub/files`` routes, which
  answer ``404 cloud_mode_off`` unless ``mode="cloud"``. Other routes (the ``/hub/sessions``
  API, ``/hub/brain``) can be added with :meth:`FakeSpine.route`. A ``FakeSpine`` is itself a
  :class:`~tau_net.spine.Transport` that only reaches its own address.
- :class:`FakeDoorbell` is an offline :class:`~tau_net.doorbell.Doorbell` (``GET /hub/ws``):
  tests ring it, drop it or refuse the next connects; one made by :meth:`FakeSpine.doorbell`
  rings whenever that spine queues an envelope, like the real Mailbox.
- :class:`FakeUniverse` implements a universe (``docs/reference/tau-universe.md`` §2) in
  memory: signed ``join``/``report``/``leave`` with every check in order (the card is fetched
  over its network), the mutual-link rule and the public snapshot. It records every request
  body, so tests can assert what a hub sent. With an ``identity`` it is also a network node
  (ADR 0013 §5): it serves its card, takes envelopes at ``POST /net/inbox`` and relays a
  visitor to a hub with :meth:`FakeUniverse.visit`.
- :class:`FakeNetwork` is a :class:`~tau_net.spine.Transport` that routes each request by host
  to one of several fake spines (and fake universes), so tests run taus that talk to each other
  with no socket. It refuses ``http`` to any host but ``localhost``/``127.0.0.1``, like a careful
  client must, and a host on those two speaks only ``http`` (a development spine has no TLS).
  A request whose path starts with ``/@handle`` goes to the fake at ``host/@handle`` when there
  is one: a :class:`FakeSpine` may have a handle address (``tau.example.com/@alice``, ADR 0013)
  and then serves its card, inbox and hub API under that path, as tau-host does.

Both are thread-safe: the hub calls the transport from worker threads.
"""

from __future__ import annotations

import hmac
import json
import re
import threading
import time
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from tau_net.doorbell import DoorbellClosed
from tau_net.encoding import (
    INSECURE_HOSTS,
    EncodingError,
    b64u_decode,
    base_url,
    host_of,
    is_valid_address,
    is_valid_host,
    split_address,
)
from tau_net.envelope import (
    MAX_ENVELOPE_BYTES,
    BadSignature,
    Envelope,
    EnvelopeError,
    Payload,
    build_envelope,
    open_box,
    parse_content,
    verify_signature,
)
from tau_net.identity import Identity
from tau_net.peers import CARD_PATH, CARD_TIMEOUT, MAX_CARD_BYTES
from tau_net.spine import STATE_KEY_PATTERN, TransportError
from tau_net.universe import MAX_REQUEST_BYTES, MalformedRequest, parse_request, verify_request

__all__ = [
    "DEFAULT_HUB_TOKEN",
    "FILE_NAMES",
    "SUB_FILE_PATTERN",
    "FakeDoorbell",
    "FakeNetwork",
    "FakeRequest",
    "FakeSpine",
    "FakeUniverse",
    "is_file_name",
]

DEFAULT_HUB_TOKEN = "test-hub-token"
FILE_NAMES = ("tau.toml", "persona/persona.md", "persona/user.md", "persona/net.md")
"""The fixed files a cloud-mode spine keeps (``/hub/files/<name>``)."""
SUBS_PREFIX = "persona/subs/"
SUB_FILE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.md")
"""A sub-tau file directly in ``persona/subs/`` (a definition or a public note), matched with
``fullmatch``; the spine keeps these next to :data:`FILE_NAMES`."""


def is_file_name(name: str) -> bool:
    """A name ``/hub/files/<name>`` accepts: a fixed file or ``persona/subs/<file>``."""
    if name in FILE_NAMES:
        return True
    return name.startswith(SUBS_PREFIX) and bool(
        SUB_FILE_PATTERN.fullmatch(name[len(SUBS_PREFIX) :])
    )


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


def route_key(url: str) -> tuple[str, str]:
    """``(fake address, path under it)`` of a URL: ``host/@handle`` and the rest of the path
    when the path starts with ``/@handle``, else the host and the whole path."""
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if path.startswith("/@"):
        handle, slash, rest = path[2:].partition("/")
        if handle:
            return f"{parts.netloc}/@{handle}", slash + rest or "/"
    return parts.netloc, path


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


class FakeDoorbell:
    """An offline :class:`~tau_net.doorbell.Doorbell`, thread-safe.

    :meth:`connect` succeeds (and queues the hello) unless :meth:`refuse` scripted an error;
    :meth:`wait` returns ``True`` for pending rings (several coalesce into one), raises
    :class:`~tau_net.doorbell.DoorbellClosed` after :meth:`drop`, and otherwise returns
    ``False`` after its timeout, or after ``max_wait`` seconds when that is shorter (so tests
    reach the safety fetch at once). Inspect :attr:`connects`, :attr:`closes` and :attr:`waits`
    (the timeouts asked for)."""

    def __init__(self, *, max_wait: float | None = None):
        self.max_wait = max_wait
        self.connects = 0
        self.closes = 0
        self.waits: list[float] = []
        self.connected = False
        self._pending = 0
        self._dropped = False
        self._refusals: list[BaseException] = []
        self._cond = threading.Condition()

    def __repr__(self) -> str:
        return f"FakeDoorbell(connected={self.connected}, connects={self.connects})"

    # -- scripting -------------------------------------------------------------------------------

    def refuse(self, *errors: BaseException) -> None:
        """The next :meth:`connect` calls raise these, in order (for example
        ``DoorbellUnsupported("426", 426)`` for a spine without the doorbell)."""
        with self._cond:
            self._refusals.extend(errors)

    def ring(self) -> None:
        """Announce mail, as the spine does after queuing an envelope."""
        with self._cond:
            if self.connected:
                self._pending += 1
                self._cond.notify_all()

    def drop(self) -> None:
        """Lose the connection: the current or next :meth:`wait` raises ``DoorbellClosed``."""
        with self._cond:
            if self.connected:
                self._dropped = True
                self._cond.notify_all()

    # -- the Doorbell protocol -------------------------------------------------------------------

    def connect(self) -> None:
        with self._cond:
            if self._refusals:
                raise self._refusals.pop(0)
            self.connects += 1
            self.connected, self._dropped, self._pending = True, False, 1  # the hello
            self._cond.notify_all()

    def wait(self, timeout: float) -> bool:
        with self._cond:
            self.waits.append(timeout)
            limit = timeout if self.max_wait is None else min(timeout, self.max_wait)
            self._cond.wait_for(
                lambda: self._pending > 0 or self._dropped or not self.connected, timeout=limit
            )
            if self._dropped or not self.connected:
                self.connected, self._dropped = False, False
                raise DoorbellClosed("the fake doorbell dropped")
            if self._pending:
                self._pending = 0
                return True
            return False

    def close(self) -> None:
        with self._cond:
            if self.connected:
                self.closes += 1
            self.connected, self._pending = False, 0
            self._cond.notify_all()


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
        self.doorbells: list[FakeDoorbell] = []
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
        return "http" if host_of(self.address) in INSECURE_HOSTS else "https"

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
            self._queued()
            return seq

    def doorbell(self, *, max_wait: float | None = None) -> FakeDoorbell:
        """A :class:`FakeDoorbell` this spine rings whenever it queues an envelope (what
        ``GET /hub/ws`` gives a real hub)."""
        bell = FakeDoorbell(max_wait=max_wait)
        with self._cond:
            self.doorbells.append(bell)
        return bell

    def _queued(self) -> None:
        """Wake long polls and ring doorbells; the caller holds the lock."""
        self._cond.notify_all()
        for bell in self.doorbells:
            bell.ring()

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
        where, _ = route_key(url)
        if where != self.address:
            raise TransportError(f"no route to {where}")
        return self.handle(method, url, headers, body)

    def handle(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> Response:
        """Answer one request (``url`` may be a full URL or a path with a query). A spine with a
        handle address serves everything under ``/@handle``."""
        parts = urllib.parse.urlsplit(url)
        path = parts.path or "/"
        prefix = self.address[len(split_address(self.address)[0]) :]
        if prefix:
            if not (path == prefix or path.startswith(prefix + "/")):
                return _error(404, "not_found")
            path = path[len(prefix) :] or "/"
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
        add(_Route("DELETE", files, self._cloud(self._file_delete)))
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
        media_type = request.headers.get("content-type", "").split(";", 1)[0]
        if media_type.strip().lower() != "application/json":
            return 415, _error(415, "unsupported_media_type")
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
            self._queued()
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
        """The fixed files in :data:`FILE_NAMES` order, then the sub-tau files by name."""
        with self._cond:
            fixed = [name for name in FILE_NAMES if name in self.files]
            subs = sorted(name for name in self.files if name not in FILE_NAMES)
            return 200, {
                "files": [
                    {
                        "name": name,
                        "size": len(self.files[name]["text"].encode()),
                        "updated_at": self.files[name]["updated_at"],
                    }
                    for name in fixed + subs
                ]
            }

    def _file_name(self, request: FakeRequest) -> str | None:
        name = urllib.parse.unquote(request.match.group("name")) if request.match else ""
        return name if is_file_name(name) else None

    def _file_delete(self, request: FakeRequest) -> tuple[int, Any]:
        name = self._file_name(request)
        if name is None:
            return 404, _error(404, "not_found")
        with self._cond:
            return 200, {"deleted": self.files.pop(name, None) is not None}

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


UNIVERSE_STALE_SECONDS = 300
UNIVERSE_RATE_PER_HOUR = 30
ONLINE_SECONDS = 2 * 3600
FORGET_SECONDS = 30 * 24 * 3600


def _plain(text: str) -> str:
    """``owner``/``about`` as a universe keeps them: control characters removed."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cc")


class FakeUniverse:
    """An in-memory universe for ``host`` (reference §2), reached through a
    :class:`FakeNetwork` (``network.add(FakeUniverse(...))``) or used alone as a transport.

    ``POST /api/join|report|leave`` make the checks of §2 in order (size, shape, ``universe``,
    ``ts``, path, the card fetched over :attr:`network`, signature, membership, rate). ``GET
    /api/universe`` is the snapshot and ``GET /api/taus/<address>`` one tau with its visible
    links as ``{"peer", "messages"}``. Inspect :attr:`taus`, :attr:`reports` (``address →
    {peer: messages}``), :attr:`requests` (``(method, path)``) and :meth:`bodies` / :meth:`payloads`
    (what was posted); script failures with :meth:`fail`; :meth:`cron` is the hourly clean-up.

    With ``identity`` the universe has its own network identity (ADR 0013 §5): ``GET
    /.well-known/tau.json`` is its card (:attr:`card`), ``POST /net/inbox`` takes signed
    envelopes addressed to it (checked like a spine checks them, kept in :attr:`inbox`), and
    :meth:`visit` sends a hub a ``visit`` for one of its sub-taus; :meth:`answers` opens what
    came back. ``handles`` maps an address to the handle ``GET /api/taus/<address>`` reports.
    """

    def __init__(
        self,
        host: str,
        *,
        clock: Callable[[], float] = time.time,
        network: FakeNetwork | None = None,
        allow_insecure_peers: bool = False,
        rate_per_hour: int = UNIVERSE_RATE_PER_HOUR,
        identity: Identity | None = None,
        name: str = "tau universe",
    ):
        if not is_valid_host(host):
            raise ValueError(f"not a host: {host!r}")
        self.address = host
        self.clock = clock
        self.network = network
        self.allow_insecure_peers = allow_insecure_peers
        self.rate_per_hour = rate_per_hour
        self.identity = identity
        self.name = name
        self.inbox: list[tuple[Payload, dict[str, str]]] = []
        self.handles: dict[str, str] = {}
        self.taus: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, dict[str, int]] = {}
        self.last_ts: dict[str, int] = {}
        self.accepted: dict[str, list[int]] = {}
        self.requests: list[tuple[str, str]] = []
        self.posted: list[tuple[str, bytes]] = []
        self.down = False
        self._lock = threading.RLock()
        self._failures: list[tuple[str, str, Response | BaseException]] = []

    def __repr__(self) -> str:
        return f"FakeUniverse({self.address!r}, taus={len(self.taus)})"

    @property
    def host(self) -> str:
        return self.address

    @property
    def scheme(self) -> str:
        return "http" if host_of(self.address) in INSECURE_HOSTS else "https"

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.address}"

    @property
    def card(self) -> dict[str, Any] | None:
        """The universe's own card, when it has an identity."""
        if self.identity is None:
            return None
        return {
            "v": 1,
            "address": self.address,
            "name": self.name,
            **self.identity.public_fields(self.name),
            "inbox": f"{self.url}/net/inbox",
            "software": "tau-universe/test",
        }

    # -- visitors (ADR 0013 §5) ----------------------------------------------------------------

    def visit(
        self,
        to: str,
        text: str,
        sub: str,
        *,
        thread: str | None = None,
        envelope_id: str | None = None,
        identity: Identity | None = None,
        box_key: str | None = None,
    ) -> Payload:
        """Relay a visitor's ``text`` for the sub-tau ``sub`` of the tau at ``to``: a signed
        ``visit`` posted to its inbox. ``identity`` signs instead of the universe's own (a
        forged or rotated key); ``box_key`` replaces the recipient's (fetched from its card).
        Raises ``TransportError`` or ``RuntimeError`` when the inbox does not queue it."""
        signer = identity or self.identity
        if signer is None or self.network is None:
            raise RuntimeError("the universe needs an identity and a network to visit")
        if box_key is None:
            status, _, body = self.network(
                "GET",
                base_url(to, allow_insecure=self.allow_insecure_peers) + CARD_PATH,
                {},
                None,
                5,
            )
            if status != 200:
                raise RuntimeError(f"no card at {to} ({status})")
            box_key = json.loads(bytes(body).decode("utf-8"))["box_key"]
        envelope, payload = build_envelope(
            signer,
            sender=self.address,
            recipient=to,
            recipient_box_key=box_key,
            kind="visit",
            content={"text": text, "sub": sub},
            envelope_id=envelope_id,
            thread=thread,
            ts=int(self.clock()),
        )
        inbox = base_url(to, allow_insecure=self.allow_insecure_peers) + "/net/inbox"
        headers = {"content-type": "application/json"}
        status, _, body = self.network("POST", inbox, headers, envelope.to_bytes(), 15)
        if status not in (200, 202):
            raise RuntimeError(f"the visit was not queued: {status} {bytes(body)!r}")
        return payload

    def answers(self) -> list[tuple[Payload, dict[str, str]]]:
        """What reached :attr:`inbox`: each envelope's header and its opened content."""
        with self._lock:
            return list(self.inbox)

    def _inbox(self, body: bytes) -> Response:
        """``POST /net/inbox`` of a universe with an identity: the spine's checks, in order
        (except the rate limits), then the box is opened with the universe's key."""
        if self.identity is None:
            return _error(404, "not_found")
        if len(body) > MAX_ENVELOPE_BYTES:
            return _error(413, "too_large")
        try:
            envelope = Envelope.from_json(json.loads(body.decode("utf-8")))
            payload = Payload.from_json(json.loads(envelope.payload_bytes.decode("utf-8")))
        except (UnicodeDecodeError, ValueError) as exc:
            detail = exc.reason if isinstance(exc, EnvelopeError) else "body is not JSON"
            return _error(400, "bad_request", detail)
        if payload.recipient != self.address:
            return _error(400, "wrong_recipient")
        if abs(int(self.clock()) - payload.ts) > STALE_SECONDS:
            return _error(400, "stale")
        card = self._card(payload.sender)
        if card is None:
            return _error(502, "sender_card_unavailable")
        try:
            verify_signature(card["sign_key"], envelope.payload_bytes, envelope.sig_bytes)
            content = parse_content(payload.kind, open_box(payload.box, self.identity, payload.aad))
        except BadSignature:
            return _error(403, "bad_signature")
        except EnvelopeError as exc:
            return _error(400, "bad_request", exc.reason)
        with self._lock:
            if any(p.sender == payload.sender and p.id == payload.id for p, _ in self.inbox):
                return _json(200, {"status": "duplicate", "id": payload.id})
            self.inbox.append((payload, content))
        return _json(202, {"status": "queued", "id": payload.id})

    # -- scripting and inspection --------------------------------------------------------------

    def fail(self, method: str, path: str, *answers: tuple[int, Any] | BaseException) -> None:
        """The next requests of ``method`` to ``path`` (a prefix) get these answers in order:
        ``(status, json payload)`` or an exception the network raises."""
        with self._lock:
            for answer in answers:
                if isinstance(answer, BaseException):
                    self._failures.append((method, path, answer))
                else:
                    status, payload = answer
                    self._failures.append((method, path, _json(status, payload)))

    def bodies(self, path: str | None = None) -> list[bytes]:
        """The raw ``POST`` bodies received (only those to ``path`` when given)."""
        with self._lock:
            return [body for p, body in self.posted if path is None or p == path]

    def payloads(self, kind: str | None = None) -> list[dict[str, Any]]:
        """The decoded payloads of the well-formed ``POST`` bodies (only ``kind`` when given)."""
        found = []
        for body in self.bodies():
            try:
                payload = parse_request(body).payload
            except MalformedRequest:
                continue
            if kind is None or payload.get("kind") == kind:
                found.append(payload)
        return found

    def links(self) -> list[dict[str, Any]]:
        """The visible links: ``a < b``, both joined and both reporting each other; ``messages``
        is the smaller count."""
        with self._lock:
            links = []
            for a in sorted(self.taus):
                for b, count in sorted(self.reports.get(a, {}).items()):
                    if a < b and b in self.taus and a in self.reports.get(b, {}):
                        messages = min(count, self.reports[b][a])
                        links.append({"a": a, "b": b, "messages": messages})
            return links

    def snapshot(self) -> dict[str, Any]:
        """``GET /api/universe``."""
        now = int(self.clock())
        with self._lock:
            taus = [self._public(entry, now) for entry in self.taus.values()]
            taus.sort(key=lambda entry: (entry["joined_at"], entry["address"]))
            links = self.links()
        return {
            "universe": self.address,
            "generated_at": now,
            "stats": {
                "taus": len(taus),
                "online": sum(1 for entry in taus if entry["online"]),
                "messages": sum(link["messages"] for link in links),
            },
            "taus": taus,
            "links": links,
        }

    def cron(self) -> None:
        """The hourly job: forget taus without a report for 30 days, prune rate-limit rows."""
        now = int(self.clock())
        with self._lock:
            for address, entry in list(self.taus.items()):
                if now - entry["last_seen"] > FORGET_SECONDS:
                    del self.taus[address]
                    self.reports.pop(address, None)
            for address, times in list(self.accepted.items()):
                kept = [t for t in times if now - t < 3600]
                if kept:
                    self.accepted[address] = kept
                else:
                    del self.accepted[address]

    # -- the transport -------------------------------------------------------------------------

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """Use the universe alone as a transport (it reaches only its own host)."""
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
        path = urllib.parse.urlsplit(url).path or "/"
        body = bytes(body or b"")
        with self._lock:
            self.requests.append((method, path))
            if method == "POST":
                self.posted.append((path, body))
            for i, (f_method, f_path, answer) in enumerate(self._failures):
                if f_method == method and path.startswith(f_path):
                    del self._failures[i]
                    if isinstance(answer, BaseException):
                        raise answer
                    return answer
        if method == "GET" and path in ("/", "/universe"):
            return 200, {"content-type": "text/html; charset=utf-8"}, b"<!doctype html>"
        if method == "GET" and path == CARD_PATH and self.card is not None:
            return _json(200, self.card)
        if method == "POST" and path == "/net/inbox":
            return self._inbox(body)
        if method == "GET" and path == "/api/universe":
            headers = {"cache-control": "public, max-age=60", "access-control-allow-origin": "*"}
            return _json(200, self.snapshot(), headers)
        if method == "GET" and path.startswith("/api/taus/"):
            return self._one(urllib.parse.unquote(path[len("/api/taus/") :]))
        if method == "POST" and path in ("/api/join", "/api/report", "/api/leave"):
            return self._post(path[len("/api/") :], body)
        return _error(404, "not_found")

    # -- reading -------------------------------------------------------------------------------

    def _public(self, entry: Mapping[str, Any], now: int) -> dict[str, Any]:
        return {
            "address": entry["address"],
            "name": entry["name"],
            "owner": entry["owner"],
            "about": entry["about"],
            "joined_at": entry["joined_at"],
            "last_seen": entry["last_seen"],
            "online": now - entry["last_seen"] <= ONLINE_SECONDS,
            "subs": [dict(sub) for sub in entry.get("subs", [])],
            **(
                {"handle": self.handles[entry["address"]]}
                if entry["address"] in self.handles
                else {}
            ),
        }

    def _one(self, address: str) -> Response:
        now = int(self.clock())
        with self._lock:
            entry = self.taus.get(address)
            if entry is None:
                return _error(404, "not_found")
            links = []
            for link in self.links():
                if address in (link["a"], link["b"]):
                    peer = link["b"] if link["a"] == address else link["a"]
                    links.append({"peer": peer, "messages": link["messages"]})
            return _json(200, {**self._public(entry, now), "links": links})

    # -- signed requests -----------------------------------------------------------------------

    def _card(self, address: str) -> dict[str, Any] | None:
        if self.network is None:
            return None
        url = base_url(address, allow_insecure=self.allow_insecure_peers) + CARD_PATH
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
            or card.get("address") != address
            or not _key32(card.get("sign_key"))
        ):
            return None
        return card

    def _post(self, route: str, body: bytes) -> Response:
        if len(body) > MAX_REQUEST_BYTES:
            return _error(413, "too_large")
        try:
            request = parse_request(body)
        except MalformedRequest as exc:
            return _error(400, "bad_request", exc.reason)
        payload = request.payload
        if payload["universe"] != self.address:
            return _error(400, "wrong_universe")
        address, ts, kind = payload["address"], payload["ts"], payload["kind"]
        now = int(self.clock())
        with self._lock:
            last = self.last_ts.get(address)
        if abs(now - ts) > UNIVERSE_STALE_SECONDS or (last is not None and ts <= last):
            return _error(400, "stale")
        if kind != route:
            return _error(400, "bad_request", "the path does not match the kind")
        card = self._card(address)
        if card is None:
            return _error(502, "card_unavailable")
        try:
            verify_request(card["sign_key"], request.payload_bytes, request.sig)
        except BadSignature:
            return _error(403, "bad_signature")
        with self._lock:
            if kind in ("report", "leave") and address not in self.taus:
                return _error(404, "not_joined")
            recent = [t for t in self.accepted.get(address, []) if now - t < 3600]
            if len(recent) >= self.rate_per_hour:
                return _error(429, "rate_limited")
            self.accepted[address] = [*recent, now]
            self.last_ts[address] = ts
            name = card.get("name") if isinstance(card.get("name"), str) else ""
            if kind == "join":
                previous = self.taus.get(address)
                self.taus[address] = {
                    "address": address,
                    "name": name[:NAME_LIMIT],
                    "sign_key": card["sign_key"],
                    "owner": _plain(payload["owner"]),
                    "about": _plain(payload["about"]),
                    "joined_at": previous["joined_at"] if previous else ts,
                    "last_seen": ts,
                    "subs": previous.get("subs", []) if previous else [],
                }
                url = f"https://{self.address}/universe#{address}"
                return _json(200, {"ok": True, "url": url})
            if kind == "report":
                entry = self.taus[address]
                entry["name"], entry["last_seen"] = name[:NAME_LIMIT], ts
                self.reports[address] = {
                    link["peer"]: link["messages"]
                    for link in payload["links"]
                    if link["peer"] in self.taus and link["peer"] != address
                }
                # A report replaces the public sub-taus; one without `subs` lists none.
                subs = {
                    sub["name"]: {
                        "name": sub["name"],
                        "about": _plain(sub["about"]),
                        "web": sub.get("web") is True,
                        "starters": [_plain(text) for text in sub.get("starters") or []],
                    }
                    for sub in payload.get("subs") or []
                }
                entry["subs"] = [subs[name] for name in sorted(subs)]
                visible = sum(1 for link in self.links() if address in (link["a"], link["b"]))
                return _json(200, {"ok": True, "visible_links": visible})
            del self.taus[address]
            self.reports.pop(address, None)
            return _json(200, {"ok": True})


class FakeNetwork:
    """A :class:`~tau_net.spine.Transport` that routes by host to fake spines and universes.

    ``FakeNetwork([alice, bob])`` or :meth:`add`; :attr:`requests` records ``(method, url)``;
    hosts in :attr:`down` (or hosts with ``down = True``) raise a network error.
    """

    def __init__(self, spines: Iterable[FakeSpine | FakeUniverse] = ()):
        self.spines: dict[str, FakeSpine | FakeUniverse] = {}
        self.requests: list[tuple[str, str]] = []
        self.down: set[str] = set()
        self._lock = threading.Lock()
        for spine in spines:
            self.add(spine)

    def __repr__(self) -> str:
        return f"FakeNetwork({sorted(self.spines)})"

    def add[H: (FakeSpine, FakeUniverse)](self, spine: H) -> H:
        """Route requests for the host's address to it (a :class:`FakeSpine` or a
        :class:`FakeUniverse`); it reaches other hosts through this network."""
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
        where, _ = route_key(url)
        spine = self.spines.get(where) or self.spines.get(host)
        if spine is None:
            raise TransportError(f"no route to {host}")
        if host in self.down or spine.down:
            raise TransportError(f"connection to {host} refused")
        if parts.scheme != spine.scheme:  # a development spine on localhost has no TLS
            raise TransportError(f"{host} does not speak {parts.scheme}")
        return spine.handle(method, url, headers, body)
