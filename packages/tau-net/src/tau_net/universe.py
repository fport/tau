"""The tau universe client: signed ``join``, ``report`` and ``leave`` requests (v1, ADR 0010).

A universe is an opt-in public directory of taus (``docs/reference/tau-universe.md``). A tau
talks to it with signed requests whose wire body has the shape of an envelope::

    {"payload": "<b64u of the payload bytes>", "sig": "<b64u Ed25519 signature>"}

- **Signature**: Ed25519 over ``b"tau-universe/1\\n" + payload_bytes`` with the tau's signing
  key. The prefix differs from envelopes (``tau-net/1``), so no signature is valid in both
  places.
- **Payload**: compact UTF-8 JSON, at most 64 KiB, with ``v`` (1), ``kind`` (``join``,
  ``report`` or ``leave``), ``universe`` (the universe's host, so a request cannot be replayed
  to another universe), ``address`` and ``ts`` (Unix seconds), plus ``owner`` (0–60
  characters) and ``about`` (0–200) for ``join``, and ``links`` (at most 500
  ``{"peer", "messages"}``) plus an optional ``subs`` (at most 20 public sub-taus,
  ``{"name", "about"}``, issue 150) for ``report``.

:class:`UniverseClient` builds, signs and posts them, reads the public snapshot and one tau's
entry, and maps the universe's error codes to :class:`UniverseError`. The scheme is the one of
the network protocol: ``https``, and ``http`` only for ``localhost``/``127.0.0.1`` when insecure
peers are allowed (``TAU_NET_ALLOW_INSECURE=1``). :func:`parse_request` holds the checks a
universe makes on a request body (:class:`tau_net.testing.FakeUniverse` uses it).
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tau_net.encoding import (
    EncodingError,
    b64u_decode,
    b64u_encode,
    base_url,
    is_valid_address,
    is_valid_sub_name,
    validate_address,
    validate_host,
)
from tau_net.envelope import BadSignature
from tau_net.identity import Identity
from tau_net.spine import Transport, UrllibTransport

__all__ = [
    "ABOUT_LIMIT",
    "DEFAULT_TIMEOUT",
    "DEFAULT_UNIVERSE",
    "MAX_LINKS",
    "MAX_PAYLOAD_BYTES",
    "MAX_REQUEST_BYTES",
    "MAX_SUBS",
    "OWNER_LIMIT",
    "STALE_RETRIES",
    "UNIVERSE_CONTEXT",
    "UNIVERSE_KINDS",
    "MalformedRequest",
    "SignedRequest",
    "UniverseClient",
    "UniverseError",
    "UniverseUnreachable",
    "build_request",
    "check_payload",
    "encode_payload",
    "listed_addresses",
    "make_payload",
    "parse_request",
    "select_links",
    "sign_request",
    "tau_links",
    "tau_subs",
    "verify_request",
]

UNIVERSE_CONTEXT = b"tau-universe/1\n"
"""The domain prefix of every universe signature."""
UNIVERSE_KINDS = ("join", "report", "leave")
DEFAULT_UNIVERSE = "tau.getporti.com"
MAX_REQUEST_BYTES = 65_536
"""The largest ``POST`` body a universe accepts."""
MAX_PAYLOAD_BYTES = 64 * 1024
OWNER_LIMIT = 60
ABOUT_LIMIT = 200
MAX_LINKS = 500
MAX_SUBS = 20
"""A report lists at most this many public sub-taus."""
DEFAULT_TIMEOUT = 15.0
STALE_RETRIES = 3
"""A client runs at most a few seconds ahead of its clock (join, report and a re-join within
one second), so a few retries cover a request that raced another process."""
USER_AGENT = "tau-net/0.1.0"
KEY_BYTES = 32

ERROR_TEXT = {
    "too_large": "the request is larger than the universe accepts",
    "bad_request": "the universe refused the request as malformed",
    "wrong_universe": "the universe does not answer to this host (check [component.net] universe)",
    "stale": "the universe already took a request from this tau with the same or a later time; "
    "wait a few seconds and try again (if it keeps failing, check this machine's clock)",
    "card_unavailable": "the universe could not fetch this tau's card "
    "(is it published? `tau net publish`)",
    "bad_signature": "the signature does not match the published card (run `tau net publish`)",
    "not_joined": "this tau is not in the universe (run `tau net universe join`)",
    "rate_limited": "too many requests to the universe this hour; try again later",
    "not_found": "not found",
}
"""One English phrase per error code of the universe (reference §2)."""


# -- errors ------------------------------------------------------------------------------------


class MalformedRequest(ValueError):
    """A request body or payload that breaks §1; ``reason`` is a short English phrase."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class UniverseError(Exception):
    """A universe that said no (``status`` ≥ 300) or did not answer (``status == 0``).

    ``code`` is the ``error`` field of the answer (``not_joined``, ``stale``, …) or
    ``http_<status>``; ``detail`` is its ``detail`` field.
    """

    def __init__(self, host: str, status: int, code: str, detail: str = ""):
        self.host = host
        self.status = status
        self.code = code
        self.detail = detail
        if status:
            text = ERROR_TEXT.get(code) or f"answered {status} {code}"
            message = f"universe {host}: {text}" + (f" ({detail})" if detail else "")
        else:
            message = f"universe {host} unreachable: {detail}"
        super().__init__(message)


class UniverseUnreachable(UniverseError):
    """No answer from the universe (network, DNS, TLS, timeout)."""

    def __init__(self, host: str, detail: str):
        super().__init__(host, 0, "unreachable", detail)


# -- payloads ----------------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_payload(data: Any) -> dict[str, Any]:
    """The field checks of §1 on a parsed payload; :class:`MalformedRequest` names the first
    bad field. Returns ``data`` unchanged."""
    if not isinstance(data, dict):
        raise MalformedRequest("payload is not a JSON object")
    if not _is_int(data.get("v")) or data.get("v") != 1:
        raise MalformedRequest("payload.v is not 1")
    kind = data.get("kind")
    if kind not in UNIVERSE_KINDS:
        raise MalformedRequest("payload.kind is unknown")
    if not isinstance(data.get("universe"), str) or not data["universe"]:
        raise MalformedRequest("payload.universe is not a host")
    if not is_valid_address(data.get("address")):
        raise MalformedRequest("payload.address is not an address")
    if not _is_int(data.get("ts")):
        raise MalformedRequest("payload.ts is not an integer")
    if kind == "join":
        for name, limit in (("owner", OWNER_LIMIT), ("about", ABOUT_LIMIT)):
            value = data.get(name)
            if not isinstance(value, str) or len(value) > limit:
                raise MalformedRequest(f"payload.{name} must be a string of 0-{limit} characters")
    elif kind == "report":
        links = data.get("links")
        if not isinstance(links, list) or len(links) > MAX_LINKS:
            raise MalformedRequest(f"payload.links must be a list of at most {MAX_LINKS} items")
        for link in links:
            if not isinstance(link, dict) or not is_valid_address(link.get("peer")):
                raise MalformedRequest("payload.links has an item without a peer address")
            messages = link.get("messages")
            if not _is_int(messages) or messages < 0:
                raise MalformedRequest("payload.links has an item without messages >= 0")
        _check_subs(data.get("subs"))
    return data


def _check_subs(subs: Any) -> None:
    """The optional ``subs`` of a report: at most :data:`MAX_SUBS` ``{"name", "about"}``."""
    if subs is None:
        return
    if not isinstance(subs, list) or len(subs) > MAX_SUBS:
        raise MalformedRequest(f"payload.subs must be a list of at most {MAX_SUBS} items")
    for sub in subs:
        if not isinstance(sub, dict) or not is_valid_sub_name(sub.get("name")):
            raise MalformedRequest("payload.subs has an item without a sub-tau name")
        about = sub.get("about")
        if not isinstance(about, str) or len(about) > ABOUT_LIMIT:
            raise MalformedRequest(
                f"payload.subs has an item whose about is not a string of 0-{ABOUT_LIMIT} "
                "characters"
            )


def make_payload(
    kind: str,
    *,
    universe: str,
    address: str,
    ts: int,
    owner: str = "",
    about: str = "",
    links: Iterable[Mapping[str, Any]] = (),
    subs: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The payload object of ``kind`` with the field order of §1, checked like a universe
    checks it (:class:`MalformedRequest` otherwise). A report carries ``subs`` only when
    there is at least one, so a tau without public sub-taus sends what it always sent."""
    payload: dict[str, Any] = {
        "v": 1,
        "kind": kind,
        "universe": universe,
        "address": address,
        "ts": int(ts),
    }
    if kind == "join":
        payload["owner"] = owner
        payload["about"] = about
    elif kind == "report":
        payload["links"] = [{"peer": link["peer"], "messages": link["messages"]} for link in links]
        listed = [{"name": sub["name"], "about": sub["about"]} for sub in subs]
        if listed:
            payload["subs"] = listed
    return check_payload(payload)


def encode_payload(payload: Mapping[str, Any]) -> bytes:
    """Compact UTF-8 JSON: the bytes that are signed and sent."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_request(identity: Identity, payload_bytes: bytes) -> bytes:
    """The signature of a universe request: over ``b"tau-universe/1\\n" + payload_bytes``."""
    return identity.sign(UNIVERSE_CONTEXT + payload_bytes)


def verify_request(sign_key: bytes | str, payload_bytes: bytes, signature: bytes) -> None:
    """:class:`~tau_net.envelope.BadSignature` unless ``signature`` signs
    ``b"tau-universe/1\\n" + payload_bytes`` with ``sign_key`` (raw 32 bytes or b64u)."""
    try:
        raw = b64u_decode(sign_key) if isinstance(sign_key, str) else bytes(sign_key)
        if len(raw) != KEY_BYTES:
            raise ValueError("sign key is not 32 bytes")
        Ed25519PublicKey.from_public_bytes(raw).verify(signature, UNIVERSE_CONTEXT + payload_bytes)
    except (InvalidSignature, EncodingError, ValueError):
        raise BadSignature("bad signature") from None


@dataclass(frozen=True)
class SignedRequest:
    """The wire body of a universe request."""

    payload: str
    sig: str

    def to_json(self) -> dict[str, str]:
        return {"payload": self.payload, "sig": self.sig}

    def to_bytes(self) -> bytes:
        return encode_payload(self.to_json())

    @property
    def payload_bytes(self) -> bytes:
        return b64u_decode(self.payload)

    @property
    def sig_bytes(self) -> bytes:
        return b64u_decode(self.sig)


def build_request(identity: Identity, payload: Mapping[str, Any]) -> SignedRequest:
    """Encode and sign ``payload`` (see :func:`make_payload`)."""
    payload_bytes = encode_payload(payload)
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        raise MalformedRequest(f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")
    return SignedRequest(
        payload=b64u_encode(payload_bytes),
        sig=b64u_encode(sign_request(identity, payload_bytes)),
    )


@dataclass(frozen=True)
class ParsedRequest:
    """A request body that passed the shape checks (its signature is not checked yet)."""

    payload: dict[str, Any]
    payload_bytes: bytes
    sig: bytes


def parse_request(body: bytes) -> ParsedRequest:
    """The wire body and payload checks of §2 (after the size check, before ``universe``):
    :class:`MalformedRequest` for anything a universe answers ``bad_request`` to."""
    try:
        data = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MalformedRequest("body is not UTF-8 JSON") from None
    if not isinstance(data, dict):
        raise MalformedRequest("body is not a JSON object")
    payload, sig = data.get("payload"), data.get("sig")
    if not isinstance(payload, str) or not isinstance(sig, str):
        raise MalformedRequest("body needs string payload and sig")
    try:
        payload_bytes, sig_bytes = b64u_decode(payload), b64u_decode(sig)
    except EncodingError:
        raise MalformedRequest("payload or sig is not base64url") from None
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        raise MalformedRequest(f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")
    try:
        parsed = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MalformedRequest("payload is not UTF-8 JSON") from None
    return ParsedRequest(check_payload(parsed), payload_bytes, sig_bytes)


# -- links -------------------------------------------------------------------------------------


def listed_addresses(snapshot: Mapping[str, Any]) -> set[str]:
    """The addresses of the taus in a public snapshot (``GET /api/universe``)."""
    taus = snapshot.get("taus") if isinstance(snapshot, Mapping) else None
    if not isinstance(taus, list):
        return set()
    return {
        entry["address"]
        for entry in taus
        if isinstance(entry, dict) and is_valid_address(entry.get("address"))
    }


def _count(value: Any) -> int:
    return value if _is_int(value) and value > 0 else 0


def select_links(
    contacts: Iterable[str],
    counts: Mapping[str, Any],
    listed: Iterable[str],
    *,
    own_address: str | None = None,
    limit: int = MAX_LINKS,
) -> list[dict[str, Any]]:
    """The ``links`` of a report: every accepted contact (``contacts``) that the universe lists
    (``listed``), with ``messages`` = ``in`` + ``out`` from the ``counts`` document. Unlisted
    contacts never appear. Ordered by messages (most first), then address; at most ``limit``."""
    listed = set(listed)
    links: list[dict[str, Any]] = []
    for peer in sorted(set(contacts)):
        if peer == own_address or peer not in listed:
            continue
        entry = counts.get(peer)
        entry = entry if isinstance(entry, Mapping) else {}
        links.append({"peer": peer, "messages": _count(entry.get("in")) + _count(entry.get("out"))})
    links.sort(key=lambda link: (-link["messages"], link["peer"]))
    return links[: max(0, limit)]


def tau_links(entry: Mapping[str, Any], address: str) -> list[tuple[str, int]]:
    """``(peer, messages)`` of the visible links in a ``GET /api/taus/<address>`` answer.

    Accepts ``{"peer", "messages"}`` items and the snapshot's ``{"a", "b", "messages"}`` form,
    at the top level or under ``tau``."""
    raw = entry.get("links")
    if raw is None and isinstance(entry.get("tau"), Mapping):
        raw = entry["tau"].get("links")
    links: list[tuple[str, int]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        peer = item.get("peer")
        if peer is None and address in (item.get("a"), item.get("b")):
            peer = item.get("b") if item.get("a") == address else item.get("a")
        if is_valid_address(peer) and peer != address:
            links.append((str(peer), _count(item.get("messages"))))
    return sorted(links, key=lambda link: (-link[1], link[0]))


def tau_subs(entry: Mapping[str, Any]) -> list[dict[str, str]]:
    """The public sub-taus (``{"name", "about"}``) in a ``GET /api/taus/<address>`` answer, at
    the top level or under ``tau``; ``[]`` from a universe that predates them."""
    raw = entry.get("subs")
    if raw is None and isinstance(entry.get("tau"), Mapping):
        raw = entry["tau"].get("subs")
    subs: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, Mapping) and is_valid_sub_name(item.get("name")):
            about = item.get("about")
            subs.append(
                {"name": str(item["name"]), "about": about if isinstance(about, str) else ""}
            )
    return subs


# -- the client --------------------------------------------------------------------------------


class UniverseClient:
    """One universe (``host``, e.g. ``tau.getporti.com``) over a
    :class:`~tau_net.spine.Transport`.

    Signed requests carry a ``ts`` that never repeats within this client: two requests in the
    same second get ``ts`` and ``ts + 1``, because a universe accepts only a ``ts`` greater than
    the last one it accepted from an address. Another process (the hub, ``tau net universe``)
    may have used these seconds already, so a ``stale`` answer is retried up to
    :data:`STALE_RETRIES` times, each time further ahead (``+2``, ``+4``, ``+8`` s), which covers
    a burst of requests from several processes in one second; a clock that is off by minutes
    still fails.
    """

    def __init__(
        self,
        host: str,
        *,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        allow_insecure: bool = False,
        clock: Callable[[], float] = time.time,
    ):
        self.host = validate_host(host)
        self.transport: Transport = transport or UrllibTransport()
        self.timeout = float(timeout)
        self.allow_insecure = allow_insecure
        self.clock = clock
        self.base = base_url(self.host, allow_insecure=allow_insecure)
        self._last_ts = 0

    def __repr__(self) -> str:
        return f"UniverseClient({self.host!r})"

    def url_for(self, address: str) -> str:
        """The universe page of ``address``."""
        return f"{self.base}/universe#{address}"

    # -- HTTP ----------------------------------------------------------------------------------

    def _exchange(
        self, method: str, path: str, body: bytes | None = None
    ) -> tuple[int, Any, bytes]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            status, _, answer = self.transport(
                method, self.base + path, headers, body, self.timeout
            )
        except OSError as exc:
            raise UniverseUnreachable(self.host, str(exc) or type(exc).__name__) from None
        answer = bytes(answer or b"")
        try:
            data = json.loads(answer.decode("utf-8")) if answer else None
        except (UnicodeDecodeError, ValueError):
            data = None
        return int(status), data, answer

    def _raise(self, status: int, data: Any, answer: bytes) -> None:
        if isinstance(data, dict) and data.get("error"):
            detail = data.get("detail")
            raise UniverseError(
                self.host, status, str(data["error"]), str(detail)[:200] if detail else ""
            )
        text = " ".join(answer.decode("utf-8", errors="replace").split())[:200]
        raise UniverseError(self.host, status, f"http_{status}", text)

    def _get(self, path: str) -> Any:
        status, data, answer = self._exchange("GET", path)
        if not 200 <= status < 300:
            self._raise(status, data, answer)
        if not isinstance(data, dict):
            raise UniverseError(self.host, status, "bad_json", "the answer is not a JSON object")
        return data

    def _next_ts(self) -> int:
        self._last_ts = max(int(self.clock()), self._last_ts + 1)
        return self._last_ts

    def _signed(self, identity: Identity, kind: str, address: str, **fields: Any) -> dict:
        """Build, sign and post one request, with the next ``ts`` again after ``stale``."""
        for attempt in range(1 + STALE_RETRIES):
            payload = make_payload(
                kind, universe=self.host, address=address, ts=self._next_ts(), **fields
            )
            body = build_request(identity, payload).to_bytes()
            status, data, answer = self._exchange("POST", f"/api/{kind}", body)
            if 200 <= status < 300:
                if not isinstance(data, dict):
                    raise UniverseError(self.host, status, "bad_json", "the answer is not JSON")
                return data
            stale = isinstance(data, dict) and data.get("error") == "stale"
            if not stale or attempt == STALE_RETRIES:
                self._raise(status, data, answer)
            self._last_ts += 2**attempt  # jump past what another process may have used
        raise AssertionError("unreachable")  # pragma: no cover

    # -- the protocol --------------------------------------------------------------------------

    def join(self, identity: Identity, address: str, *, owner: str = "", about: str = "") -> dict:
        """``POST /api/join``; the answer has ``url``, the tau's universe page."""
        return self._signed(identity, "join", address, owner=owner, about=about)

    def report(
        self,
        identity: Identity,
        address: str,
        links: Iterable[Mapping[str, Any]],
        *,
        subs: Iterable[Mapping[str, Any]] = (),
    ) -> dict:
        """``POST /api/report`` with ``links`` (at most 500, trimmed from the end until the
        body fits) and the public sub-taus ``subs`` (at most 20); the answer has
        ``visible_links``."""
        links = [dict(link) for link in links][:MAX_LINKS]
        subs = [dict(sub) for sub in subs][:MAX_SUBS]
        while links:
            payload = make_payload(
                "report",
                universe=self.host,
                address=address,
                ts=int(self.clock()),
                links=links,
                subs=subs,
            )
            if len(build_request(identity, payload).to_bytes()) <= MAX_REQUEST_BYTES:
                break
            links = links[: len(links) * 9 // 10]
        return self._signed(identity, "report", address, links=links, subs=subs)

    def leave(self, identity: Identity, address: str) -> dict:
        """``POST /api/leave``: the universe forgets the tau and its reported links."""
        return self._signed(identity, "leave", address)

    def snapshot(self) -> dict[str, Any]:
        """``GET /api/universe``: ``{universe, generated_at, stats, taus, links}``."""
        data = self._get("/api/universe")
        if not isinstance(data.get("taus"), list):
            raise UniverseError(self.host, 200, "bad_json", "the snapshot has no taus list")
        return data

    def tau(self, address: str) -> dict[str, Any] | None:
        """``GET /api/taus/<address>``: one tau with its visible links; ``None`` when the
        universe does not list it."""
        validate_address(address)
        path = "/api/taus/" + urllib.parse.quote(address, safe=".:-")
        status, data, answer = self._exchange("GET", path)
        if status == 404:
            return None
        if not 200 <= status < 300:
            self._raise(status, data, answer)
        if not isinstance(data, dict):
            raise UniverseError(self.host, status, "bad_json", "the answer is not a JSON object")
        return data
