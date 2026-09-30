"""Other taus: fetch a card, deliver an envelope (protocol v1, §4 and §6.6).

A card is fetched from ``<scheme>://<address>/.well-known/tau.json`` with a 5 s timeout and
must be at most 8 KiB, JSON with ``v == 1``, ``address`` equal to the address asked for and
32-byte ``sign_key`` and ``box_key``. The hub posts envelopes straight to
``<scheme>://<to>/net/inbox``, never through its own spine; ``202`` or a ``duplicate`` answer
counts as delivered, anything else is a :class:`DeliveryError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tau_net.encoding import INSECURE_HOSTS, EncodingError, b64u_decode, base_url, validate_address
from tau_net.envelope import Envelope
from tau_net.spine import Transport, UrllibTransport

__all__ = [
    "CARD_PATH",
    "CARD_TIMEOUT",
    "INBOX_PATH",
    "MAX_CARD_BYTES",
    "CardError",
    "Delivery",
    "DeliveryError",
    "PeerCard",
    "PeerClient",
    "parse_card",
]

CARD_PATH = "/.well-known/tau.json"
INBOX_PATH = "/net/inbox"
CARD_TIMEOUT = 5.0
SEND_TIMEOUT = 15.0
MAX_CARD_BYTES = 8 * 1024
MAX_NAME_CHARS = 80
USER_AGENT = "tau-net/0.1.0"


class CardError(Exception):
    """A card that cannot be fetched or does not pass the checks of §4."""

    def __init__(self, address: str, reason: str):
        self.address = address
        self.reason = reason
        super().__init__(f"card of {address} unavailable: {reason}")


class DeliveryError(Exception):
    """An envelope the recipient's spine did not accept. ``status`` 0 = no answer."""

    def __init__(self, address: str, status: int, code: str, detail: str = ""):
        self.address = address
        self.status = status
        self.code = code
        self.detail = detail
        where = f"{status} {code}" if status else code
        super().__init__(
            f"delivery to {address} failed: {where}" + (f" ({detail})" if detail else "")
        )


@dataclass(frozen=True)
class PeerCard:
    address: str
    name: str
    sign_key: str
    box_key: str
    inbox: str = ""
    software: str = ""

    @property
    def sign_key_bytes(self) -> bytes:
        return b64u_decode(self.sign_key)

    @property
    def box_key_bytes(self) -> bytes:
        return b64u_decode(self.box_key)


def _key(data: dict[str, Any], name: str, address: str) -> str:
    value = data.get(name)
    try:
        if isinstance(value, str) and len(b64u_decode(value)) == 32:
            return value
    except EncodingError:
        pass
    raise CardError(address, f"{name} is not a 32-byte base64url key")


def parse_card(address: str, body: bytes) -> PeerCard:
    """The checks of §4 on a fetched card body."""
    if len(body) > MAX_CARD_BYTES:
        raise CardError(address, f"larger than {MAX_CARD_BYTES} bytes")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise CardError(address, "not JSON") from None
    if not isinstance(data, dict):
        raise CardError(address, "not a JSON object")
    if data.get("v") != 1 or isinstance(data.get("v"), bool):
        raise CardError(address, "not a v1 card")
    if data.get("address") != address:
        raise CardError(address, "its address does not match")
    name = data.get("name")
    return PeerCard(
        address=address,
        name=name[:MAX_NAME_CHARS] if isinstance(name, str) else "",
        sign_key=_key(data, "sign_key", address),
        box_key=_key(data, "box_key", address),
        inbox=str(data.get("inbox") or ""),
        software=str(data.get("software") or ""),
    )


@dataclass(frozen=True)
class Delivery:
    """A delivered envelope: ``status`` is ``queued`` or ``duplicate``."""

    address: str
    id: str
    status: str


class PeerClient:
    """Cards and inboxes of other taus over a :class:`~tau_net.spine.Transport`."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        allow_insecure: bool = False,
        card_timeout: float = CARD_TIMEOUT,
        send_timeout: float = SEND_TIMEOUT,
    ):
        self.transport: Transport = transport or UrllibTransport()
        self.allow_insecure = allow_insecure
        self.card_timeout = card_timeout
        self.send_timeout = send_timeout

    def url(self, address: str, path: str) -> str:
        return base_url(address, allow_insecure=self.allow_insecure) + path

    def fetch_card(self, address: str) -> PeerCard:
        """Fetch and check the card of ``address``; :class:`CardError` on any failure."""
        validate_address(address)
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        try:
            status, _, body = self.transport(
                "GET", self.url(address, CARD_PATH), headers, None, self.card_timeout
            )
        except OSError as exc:
            reason = f"no answer ({type(exc).__name__})"
            host = address.rsplit(":", 1)[0] if ":" in address else address
            if host in INSECURE_HOSTS and not self.allow_insecure:
                reason += "; a local peer needs TAU_NET_ALLOW_INSECURE=1 for plain http"
            raise CardError(address, reason) from None
        if status != 200:
            raise CardError(address, f"HTTP {status}")
        return parse_card(address, bytes(body))

    def deliver(self, address: str, envelope: Envelope) -> Delivery:
        """``POST <scheme>://<address>/net/inbox``; :class:`DeliveryError` unless the spine
        queued it (202) or already had it (``duplicate``)."""
        validate_address(address)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            status, _, body = self.transport(
                "POST",
                self.url(address, INBOX_PATH),
                headers,
                envelope.to_bytes(),
                self.send_timeout,
            )
        except OSError as exc:
            raise DeliveryError(address, 0, "unreachable", type(exc).__name__) from None
        try:
            data = json.loads(bytes(body).decode("utf-8")) if body else None
        except (UnicodeDecodeError, ValueError):
            data = None
        data = data if isinstance(data, dict) else {}
        envelope_id = str(data.get("id") or "")
        if status == 202:
            return Delivery(address, envelope_id, "queued")
        if status == 200 and data.get("status") == "duplicate":
            return Delivery(address, envelope_id, "duplicate")
        code = str(data.get("error") or f"http_{status}")
        detail = str(data.get("detail") or "")[:200]
        raise DeliveryError(address, status, code, detail)
