"""Envelopes: signed by the sender, sealed to the recipient (protocol v1, §3).

On the wire an envelope is ``{"payload": b64u(payload bytes), "sig": b64u(signature)}``. The
payload bytes are compact UTF-8 JSON with the header fields (``v``, ``id``, ``kind``, ``from``,
``to``, ``ts``, ``thread``, ``reply_to``, ``hops``) and the sealed ``box``.

- **Signature**: Ed25519 over ``b"tau-net/1\\n" + payload_bytes``. :func:`open_verified` checks
  it against the exact bytes decoded from ``payload`` and parses JSON only after that check;
  :func:`peek_sender` reads the unverified ``from`` only to find the key to verify with.
- **Box**: a fresh X25519 key pair per envelope, ``HKDF-SHA256(shared, salt=epk ||
  recipient_box_key, info=b"tau-net/1 box")`` and ChaCha20-Poly1305 with the associated data
  ``tau-net/1|{id}|{kind}|{from}|{to}``, so a box cannot be moved to another header.

The kinds are ``contact_request``, ``contact_accept``, ``message`` and ``visit`` (ADR 0013
§5): a universe relays an anonymous visitor of a public sub-tau's page as a ``visit`` sealed to
the hub that runs the sub-tau, with the content ``{"text", "sub"}``.

Every failure raises a subclass of :class:`EnvelopeError` whose ``reason`` is a short fixed
English phrase for logs.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from tau_net.encoding import (
    EncodingError,
    b64u_decode,
    b64u_encode,
    is_valid_address,
    is_valid_id,
    is_valid_sub_name,
)
from tau_net.identity import Identity

__all__ = [
    "BOX_INFO",
    "KINDS",
    "MAX_ENVELOPE_BYTES",
    "MAX_MESSAGE_CHARS",
    "MAX_VISIT_CHARS",
    "SIGNATURE_CONTEXT",
    "BadSignature",
    "Box",
    "BoxError",
    "Envelope",
    "EnvelopeError",
    "EnvelopeTooLarge",
    "MalformedEnvelope",
    "Payload",
    "aad_for",
    "build_envelope",
    "new_id",
    "open_box",
    "open_verified",
    "parse_content",
    "peek_sender",
    "seal",
    "sign_payload",
    "verify_signature",
]

SIGNATURE_CONTEXT = b"tau-net/1\n"
BOX_INFO = b"tau-net/1 box"
KINDS = ("contact_request", "contact_accept", "message", "visit")
MAX_ENVELOPE_BYTES = 65_536
"""The largest ``POST /net/inbox`` body a spine accepts."""
MAX_MESSAGE_CHARS = 8_000
"""The longest ``message`` text."""
MAX_VISIT_CHARS = MAX_MESSAGE_CHARS
"""The longest ``visit`` text: the same as a ``message`` (a universe takes less from a
visitor)."""
NONCE_BYTES = 12
KEY_BYTES = 32


class EnvelopeError(ValueError):
    """An envelope that cannot be built, verified or opened. ``reason`` is for logs."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class MalformedEnvelope(EnvelopeError):
    """Not an envelope of protocol v1: wrong shape, types or values."""


class BadSignature(EnvelopeError):
    """The signature does not verify with the key it was checked against."""


class BoxError(EnvelopeError):
    """The box does not open with this identity and header, or its content is malformed."""


class EnvelopeTooLarge(EnvelopeError):
    """The envelope would exceed :data:`MAX_ENVELOPE_BYTES`."""


def new_id() -> str:
    """A fresh envelope id (24 base64url characters)."""
    return secrets.token_urlsafe(18)


def _compact(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def aad_for(envelope_id: str, kind: str, sender: str, recipient: str) -> bytes:
    """The associated data that binds a box to its header."""
    return f"tau-net/1|{envelope_id}|{kind}|{sender}|{recipient}".encode()


# -- the typed pieces --------------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    epk: str
    nonce: str
    ct: str

    def to_json(self) -> dict[str, str]:
        return {"epk": self.epk, "nonce": self.nonce, "ct": self.ct}

    @classmethod
    def from_json(cls, data: Any) -> Box:
        if not isinstance(data, dict):
            raise MalformedEnvelope("box is not an object")
        values = []
        for name in ("epk", "nonce", "ct"):
            value = data.get(name)
            if not isinstance(value, str):
                raise MalformedEnvelope(f"box.{name} is not a string")
            try:
                b64u_decode(value)
            except EncodingError:
                raise MalformedEnvelope(f"box.{name} is not base64url") from None
            values.append(value)
        return cls(*values)


@dataclass(frozen=True)
class Payload:
    """The signed header of an envelope. ``sender``/``recipient`` are ``from``/``to``."""

    id: str
    kind: str
    sender: str
    recipient: str
    ts: int
    thread: str
    reply_to: str | None
    hops: int
    box: Box
    v: int = 1

    def to_json(self) -> dict[str, Any]:
        """The payload object with the field order of the protocol."""
        return {
            "v": self.v,
            "id": self.id,
            "kind": self.kind,
            "from": self.sender,
            "to": self.recipient,
            "ts": self.ts,
            "thread": self.thread,
            "reply_to": self.reply_to,
            "hops": self.hops,
            "box": self.box.to_json(),
        }

    def to_bytes(self) -> bytes:
        return _compact(self.to_json())

    @property
    def aad(self) -> bytes:
        return aad_for(self.id, self.kind, self.sender, self.recipient)

    @classmethod
    def from_json(cls, data: Any) -> Payload:
        """Validate every field of §3; :class:`MalformedEnvelope` names the first bad one."""
        if not isinstance(data, dict):
            raise MalformedEnvelope("payload is not a JSON object")
        missing = [
            name
            for name in ("v", "id", "kind", "from", "to", "ts", "thread", "reply_to", "hops", "box")
            if name not in data
        ]
        if missing:
            raise MalformedEnvelope(f"payload misses {', '.join(missing)}")
        v = data["v"]
        if not _is_int(v) or v != 1:
            raise MalformedEnvelope("payload.v is not 1")
        if not is_valid_id(data["id"]):
            raise MalformedEnvelope("payload.id is not a valid id")
        if data["kind"] not in KINDS:
            raise MalformedEnvelope("payload.kind is unknown")
        for name in ("from", "to"):
            if not is_valid_address(data[name]):
                raise MalformedEnvelope(f"payload.{name} is not an address")
        if not _is_int(data["ts"]):
            raise MalformedEnvelope("payload.ts is not an integer")
        if not is_valid_id(data["thread"]):
            raise MalformedEnvelope("payload.thread is not a valid id")
        reply_to = data["reply_to"]
        if reply_to is not None and not is_valid_id(reply_to):
            raise MalformedEnvelope("payload.reply_to is neither null nor a valid id")
        hops = data["hops"]
        if not _is_int(hops) or hops < 0:
            raise MalformedEnvelope("payload.hops is not a non-negative integer")
        return cls(
            id=data["id"],
            kind=data["kind"],
            sender=data["from"],
            recipient=data["to"],
            ts=data["ts"],
            thread=data["thread"],
            reply_to=reply_to,
            hops=hops,
            box=Box.from_json(data["box"]),
        )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Envelope:
    """The wire form: base64url payload bytes and signature."""

    payload: str
    sig: str

    def to_json(self) -> dict[str, str]:
        return {"payload": self.payload, "sig": self.sig}

    def to_bytes(self) -> bytes:
        return _compact(self.to_json())

    @classmethod
    def from_json(cls, data: Any) -> Envelope:
        if not isinstance(data, dict):
            raise MalformedEnvelope("envelope is not a JSON object")
        payload, sig = data.get("payload"), data.get("sig")
        if not isinstance(payload, str) or not isinstance(sig, str):
            raise MalformedEnvelope("envelope needs string payload and sig")
        for name, value in (("payload", payload), ("sig", sig)):
            try:
                b64u_decode(value)
            except EncodingError:
                raise MalformedEnvelope(f"envelope.{name} is not base64url") from None
        return cls(payload, sig)

    @property
    def payload_bytes(self) -> bytes:
        return b64u_decode(self.payload)

    @property
    def sig_bytes(self) -> bytes:
        return b64u_decode(self.sig)


# -- signing -----------------------------------------------------------------------------------


def sign_payload(identity: Identity, payload_bytes: bytes) -> bytes:
    return identity.sign(SIGNATURE_CONTEXT + payload_bytes)


def verify_signature(sign_key: bytes | str, payload_bytes: bytes, signature: bytes) -> None:
    """:class:`BadSignature` unless ``signature`` is the Ed25519 signature of
    ``b"tau-net/1\\n" + payload_bytes`` by ``sign_key`` (raw 32 bytes or b64u)."""
    try:
        raw = b64u_decode(sign_key) if isinstance(sign_key, str) else bytes(sign_key)
        if len(raw) != KEY_BYTES:
            raise ValueError("sign key is not 32 bytes")
        Ed25519PublicKey.from_public_bytes(raw).verify(signature, SIGNATURE_CONTEXT + payload_bytes)
    except (InvalidSignature, EncodingError, ValueError):
        raise BadSignature("bad signature") from None


def peek_sender(envelope: Envelope) -> str:
    """The claimed ``from`` of an unverified envelope, only to pick the key to verify with.

    Nothing else from an unverified payload is used; :func:`open_verified` parses it again
    from the verified bytes.
    """
    try:
        data = json.loads(envelope.payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MalformedEnvelope("payload is not UTF-8 JSON") from None
    sender = data.get("from") if isinstance(data, dict) else None
    if not is_valid_address(sender):
        raise MalformedEnvelope("payload.from is not an address")
    return str(sender)


def open_verified(envelope: Envelope, sign_key: bytes | str) -> Payload:
    """Verify the signature over the exact payload bytes, then parse and validate them."""
    payload_bytes = envelope.payload_bytes
    verify_signature(sign_key, payload_bytes, envelope.sig_bytes)
    try:
        data = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MalformedEnvelope("payload is not UTF-8 JSON") from None
    return Payload.from_json(data)


# -- sealing -----------------------------------------------------------------------------------


def _box_key(shared: bytes, epk: bytes, recipient_box_key: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=epk + recipient_box_key,
        info=BOX_INFO,
    ).derive(shared)


def seal(content: dict[str, Any], recipient_box_key: bytes | str, aad: bytes) -> Box:
    """Seal ``content`` (JSON) to ``recipient_box_key`` with a fresh ephemeral key."""
    try:
        recipient = (
            b64u_decode(recipient_box_key)
            if isinstance(recipient_box_key, str)
            else bytes(recipient_box_key)
        )
        if len(recipient) != KEY_BYTES:
            raise ValueError("box key is not 32 bytes")
        esk = X25519PrivateKey.generate()
        epk = esk.public_key().public_bytes_raw()
        shared = esk.exchange(X25519PublicKey.from_public_bytes(recipient))
    except (EncodingError, ValueError):
        raise BoxError("recipient box key is invalid") from None
    key = _box_key(shared, epk, recipient)
    nonce = os.urandom(NONCE_BYTES)
    ct = ChaCha20Poly1305(key).encrypt(nonce, _compact(content), aad)
    return Box(epk=b64u_encode(epk), nonce=b64u_encode(nonce), ct=b64u_encode(ct))


def open_box(box: Box, identity: Identity, aad: bytes) -> dict[str, Any]:
    """Open ``box`` with this identity's box key; :class:`BoxError` on any failure."""
    try:
        epk = b64u_decode(box.epk)
        nonce = b64u_decode(box.nonce)
        ct = b64u_decode(box.ct)
        if len(epk) != KEY_BYTES or len(nonce) != NONCE_BYTES:
            raise ValueError("wrong key or nonce length")
        shared = identity.box_private_key.exchange(X25519PublicKey.from_public_bytes(epk))
        key = _box_key(shared, epk, identity.box_key_bytes)
        plaintext = ChaCha20Poly1305(key).decrypt(nonce, ct, aad)
    except (EncodingError, ValueError, InvalidTag):
        raise BoxError("box does not open") from None
    try:
        content = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BoxError("box content is not UTF-8 JSON") from None
    if not isinstance(content, dict):
        raise BoxError("box content is not an object")
    return content


def parse_content(kind: str, content: dict[str, Any]) -> dict[str, str]:
    """The sealed plaintext of ``kind`` with the right types, else :class:`BoxError`.

    ``contact_request`` → ``{"name", "text"}``, ``contact_accept`` → ``{"name"}``,
    ``message`` → ``{"text"}`` (at most :data:`MAX_MESSAGE_CHARS`) plus ``"sub"`` when the
    message carries a sub-tau name (issue 150; absent or ``null`` means none), ``visit`` →
    ``{"text", "sub"}`` (at most :data:`MAX_VISIT_CHARS`; ``sub`` is required). Other keys are
    ignored, which is what lets a hub that predates a field read a message that has it.
    """
    fields = {
        "contact_request": ("name", "text"),
        "contact_accept": ("name",),
        "message": ("text",),
        "visit": ("text", "sub"),
    }.get(kind)
    if fields is None:
        raise BoxError(f"unknown kind {kind!r}")
    parsed: dict[str, str] = {}
    for name in fields:
        value = content.get(name)
        if not isinstance(value, str):
            raise BoxError(f"{kind} content needs a string {name!r}")
        parsed[name] = value
    if kind == "message" and len(parsed["text"]) > MAX_MESSAGE_CHARS:
        raise BoxError(f"message text is longer than {MAX_MESSAGE_CHARS} characters")
    if kind == "message" and content.get("sub") is not None:
        sub = content["sub"]
        if not is_valid_sub_name(sub):
            raise BoxError("message sub is not a sub-tau name")
        parsed["sub"] = sub
    if kind == "visit":
        if not is_valid_sub_name(parsed["sub"]):
            raise BoxError("visit sub is not a sub-tau name")
        if len(parsed["text"]) > MAX_VISIT_CHARS:
            raise BoxError(f"visit text is longer than {MAX_VISIT_CHARS} characters")
    return parsed


# -- building ----------------------------------------------------------------------------------


def build_envelope(
    identity: Identity,
    *,
    sender: str,
    recipient: str,
    recipient_box_key: bytes | str,
    kind: str,
    content: dict[str, Any],
    envelope_id: str | None = None,
    thread: str | None = None,
    reply_to: str | None = None,
    hops: int = 0,
    ts: int | None = None,
) -> tuple[Envelope, Payload]:
    """Seal ``content``, sign the payload and return the wire envelope with its header.

    A new conversation (``thread=None``) uses the envelope's own id as its thread.
    :class:`EnvelopeTooLarge` when the result would not fit a spine's inbox.
    """
    if kind not in KINDS:
        raise MalformedEnvelope(f"unknown kind {kind!r}")
    parse_content(kind, content)  # the same checks the recipient makes
    envelope_id = envelope_id or new_id()
    box = seal(content, recipient_box_key, aad_for(envelope_id, kind, sender, recipient))
    payload = Payload(
        id=envelope_id,
        kind=kind,
        sender=sender,
        recipient=recipient,
        ts=int(time.time()) if ts is None else int(ts),
        thread=thread or envelope_id,
        reply_to=reply_to,
        hops=hops,
        box=box,
    )
    Payload.from_json(payload.to_json())  # the recipient's validation, before anything is sent
    payload_bytes = payload.to_bytes()
    envelope = Envelope(
        payload=b64u_encode(payload_bytes), sig=b64u_encode(sign_payload(identity, payload_bytes))
    )
    if len(envelope.to_bytes()) > MAX_ENVELOPE_BYTES:
        raise EnvelopeTooLarge(f"envelope is larger than {MAX_ENVELOPE_BYTES} bytes")
    return envelope, payload
