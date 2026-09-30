"""Test vectors for the protocol's TypeScript half (``cloud/shared/net``, issue 158).

Writes ``cloud/shared/net/vectors.json`` from tau-net itself, so the TypeScript the Workers run
and the Python the hubs run stay byte-compatible. vitest in ``cloud/shared`` checks that
TypeScript

- derives the same public keys, identity JSON and ``TAU_NET_IDENTITY`` value from the seeds;
- agrees with tau-net on base64url, addresses, targets and the scheme rule;
- verifies and opens every envelope, and rebuilds each one byte for byte from its inputs;
- refuses the tampered envelopes the way tau-net does;
- verifies every universe request and signs the same bytes from the same fields.

tau-net draws the ephemeral key and the nonce of a box at random. For the envelopes below the
script pins both for the length of one ``build_envelope`` call (``pinned_randomness``), so the
output is deterministic and the file can be compared with a fresh run. Kinds and fields that
this tau-net may not know yet (``visit``, the universe ``claim``) are built from its
primitives (``seal``, ``sign_payload``, ``build_request``) instead of its validating builders.
The addresses are plain hosts only: ``host/@handle`` addresses are tested on the TypeScript
side, and in ``cloud/shared/net/ts-vectors.json``.

Every key here is a **test-only** key, derived from a fixed label and published in this
repository: never use one for a real tau.

Run from the repository root::

    uv run python packages/tau-net/scripts/make_ts_vectors.py           # write the file
    uv run python packages/tau-net/scripts/make_ts_vectors.py --check   # exit 1 when stale

``packages/tau-net/tests/test_ts_vectors.py`` fails when the file is stale, and checks the
vectors TypeScript wrote (``ts-vectors.json``, ``bun run vectors`` in ``cloud/shared``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from tau_net import envelope as envelope_module
from tau_net.encoding import (
    AddressError,
    EncodingError,
    b64u_decode,
    b64u_encode,
    base_url,
    is_valid_address,
    parse_address,
    parse_target,
)
from tau_net.envelope import (
    SIGNATURE_CONTEXT,
    BadSignature,
    Box,
    BoxError,
    Envelope,
    Payload,
    aad_for,
    build_envelope,
    open_box,
    open_verified,
    seal,
    sign_payload,
)
from tau_net.identity import Identity
from tau_net.universe import UNIVERSE_CONTEXT, build_request, make_payload

REPO = Path(__file__).resolve().parents[3]
VECTORS_PATH = REPO / "cloud" / "shared" / "net" / "vectors.json"
TS_VECTORS_PATH = REPO / "cloud" / "shared" / "net" / "ts-vectors.json"

TS = 1_790_000_000
UNIVERSE = "universe.example.com"


def fixed_bytes(label: str, length: int = 32) -> bytes:
    """Fixed test-only bytes for ``label``: never a real key."""
    return hashlib.sha256(f"tau-net ts vectors (test only): {label}".encode()).digest()[:length]


@dataclass(frozen=True)
class Tau:
    label: str
    address: str
    identity: Identity


def taus() -> dict[str, Tau]:
    return {
        # The seeds of the test vector in docs/reference/tau-network.md §3.
        "alice": Tau(
            "alice", "alice.example.com", Identity(bytes(range(32)), bytes(range(32, 64)))
        ),
        "bob": Tau(
            "bob", "bob.example.com", Identity(fixed_bytes("bob sign"), fixed_bytes("bob box"))
        ),
        "dev": Tau(
            "dev", "127.0.0.1:8787", Identity(fixed_bytes("dev sign"), fixed_bytes("dev box"))
        ),
        "universe": Tau(
            "universe",
            UNIVERSE,
            Identity(fixed_bytes("universe sign"), fixed_bytes("universe box")),
        ),
    }


@contextmanager
def pinned_randomness(ephemeral_secret: bytes, nonce: bytes) -> Iterator[None]:
    """Make tau-net's ``seal`` use this ephemeral X25519 key and nonce instead of fresh ones."""

    class PinnedX25519PrivateKey:
        @staticmethod
        def generate() -> X25519PrivateKey:
            return X25519PrivateKey.from_private_bytes(ephemeral_secret)

    def urandom(length: int) -> bytes:
        if length != len(nonce):
            raise RuntimeError(
                f"seal asked for {length} random bytes, not a {len(nonce)}-byte nonce"
            )
        return nonce

    with (
        mock.patch.object(envelope_module, "X25519PrivateKey", PinnedX25519PrivateKey),
        mock.patch.object(envelope_module, "os", types.SimpleNamespace(urandom=urandom)),
    ):
        yield


def _check_pinned(box: Box, ephemeral_secret: bytes, nonce: bytes) -> None:
    epk = X25519PrivateKey.from_private_bytes(ephemeral_secret).public_key().public_bytes_raw()
    if box.epk != b64u_encode(epk) or box.nonce != b64u_encode(nonce):
        raise RuntimeError("tau-net no longer draws its randomness where pinned_randomness pins it")


# -- identities, encoding, addresses -----------------------------------------------------------


def identity_vectors(all_taus: dict[str, Tau]) -> dict[str, Any]:
    return {
        tau.label: {
            "address": tau.address,
            "identity": tau.identity.to_json(),
            "env_value": tau.identity.to_env_value(),
            "sign_key": tau.identity.sign_key,
            "box_key": tau.identity.box_key,
        }
        for tau in all_taus.values()
    }


def _decoded(text: str) -> str | None:
    try:
        return b64u_decode(text).hex()
    except EncodingError:
        return None


def b64u_vectors() -> dict[str, Any]:
    samples = [b"", b"\x00", b"\xfb\xff", b"\xfb\xff\xbf", b"tau", b"tau-net/1\n", bytes(range(40))]
    decode_inputs = [
        "", "AA", "AA==", "AAA", "AAA=", "AAAA", "-_8", "-_8=", "_w", "_w==", "A", "AB=", "AAAA=",
        "-_8==", "+/8", "-_8 ", "a\nb", "AA===", "=", "A=A=",
    ]  # fmt: skip
    return {
        "encode": [{"hex": data.hex(), "b64u": b64u_encode(data)} for data in samples],
        "decode": [{"text": text, "hex": _decoded(text)} for text in decode_inputs],
    }


def _target(text: str) -> dict[str, Any] | None:
    try:
        address, sub = parse_target(text)
    except AddressError:
        return None
    return {"address": address, "sub": sub}


def _parsed(text: str) -> str | None:
    try:
        return parse_address(text)
    except AddressError:
        return None


def address_vectors() -> dict[str, Any]:
    """tau-net's verdicts on plain addresses; ``host/@handle`` ones are tested in TypeScript."""
    candidates = [
        "tau.example.com", "tau-spine.alice.workers.dev", "127.0.0.1:8787", "localhost", "a",
        "a.com:8080", "a.com:12345", "x" * 63 + ".com", "Tau.example.com", "-a.com", "a-.com",
        "a..com", "a.com:", "a.com:123456", "a_b.com", "tau.example.com.", "x" * 64 + ".com",
        "a.com/", "https://a.com", "a.com\n", "", " a.com", "a.com/coach", "tau.example.com:80:80",
    ]  # fmt: skip
    typed = [
        "tau.example.com", " HTTPS://Tau.Example.com/ ", "http://127.0.0.1:8787", "https://a.com//",
        "not an address", "tau.example.com/x", "",
    ]  # fmt: skip
    targets = [
        "tau.example.com", "tau.example.com/coach", "Tau.Example.com/Coach",
        "https://tau.example.com/coach/", "tau.example.com/c", "tau.example.com/coach/x",
        "tau.example.com/1coach", "127.0.0.1:8787/study-buddy", "tau.example.com/ coach ",
    ]  # fmt: skip
    urls = [
        ("tau.example.com", False), ("tau.example.com", True), ("127.0.0.1:8787", True),
        ("127.0.0.1:8787", False), ("localhost", True), ("localhost:8788", True),
        ("127.0.0.2:8787", True), ("localhost.example.com", True),
    ]  # fmt: skip
    return {
        "valid": [{"address": a, "valid": is_valid_address(a)} for a in candidates],
        "parse_address": [{"text": text, "address": _parsed(text)} for text in typed],
        "parse_target": [{"text": text, "target": _target(text)} for text in targets],
        "base_url": [
            {"address": a, "allow_insecure": insecure, "url": base_url(a, allow_insecure=insecure)}
            for a, insecure in urls
        ],
    }


# -- envelopes ---------------------------------------------------------------------------------


def envelope_case(
    name: str,
    sender: Tau,
    recipient: Tau,
    *,
    kind: str,
    content: dict[str, Any],
    envelope_id: str,
    thread: str | None = None,
    reply_to: str | None = None,
    hops: int = 0,
    note: str,
    primitives: bool = False,
) -> dict[str, Any]:
    """An envelope built by tau-net with pinned randomness: by ``build_envelope``, or with
    ``primitives`` from ``seal`` and ``sign_payload`` (a kind this tau-net may not know yet)."""
    ephemeral_secret, nonce = fixed_bytes(f"{name} ephemeral"), fixed_bytes(f"{name} nonce", 12)
    common = {"kind": kind, "envelope_id": envelope_id, "reply_to": reply_to, "hops": hops}
    with pinned_randomness(ephemeral_secret, nonce):
        if primitives:
            aad = aad_for(envelope_id, kind, sender.address, recipient.address)
            box = seal(content, recipient.identity.box_key, aad)
            payload = Payload(
                id=envelope_id,
                kind=kind,
                sender=sender.address,
                recipient=recipient.address,
                ts=TS,
                thread=thread or envelope_id,
                reply_to=reply_to,
                hops=hops,
                box=box,
            )
            payload_bytes = payload.to_bytes()
            wire = Envelope(
                payload=b64u_encode(payload_bytes),
                sig=b64u_encode(sign_payload(sender.identity, payload_bytes)),
            )
        else:
            wire, payload = build_envelope(
                sender.identity,
                sender=sender.address,
                recipient=recipient.address,
                recipient_box_key=recipient.identity.box_key,
                content=content,
                thread=thread,
                ts=TS,
                **common,
            )
    _check_pinned(payload.box, ephemeral_secret, nonce)
    if open_box(payload.box, recipient.identity, payload.aad) != content:
        raise RuntimeError(f"{name}: the box does not open to its content")
    return {
        "name": name,
        "note": note,
        "built_with": "primitives" if primitives else "build_envelope",
        "sender": sender.label,
        "recipient": recipient.label,
        "input": {
            "from": sender.address,
            "to": recipient.address,
            "kind": kind,
            "content": content,
            "id": envelope_id,
            "thread": thread,
            "reply_to": reply_to,
            "hops": hops,
            "ts": TS,
            "ephemeral_secret": b64u_encode(ephemeral_secret),
            "nonce": b64u_encode(nonce),
        },
        "payload": payload.to_json(),
        "envelope": wire.to_json(),
    }


TRICKY_TEXT = (
    'Quotes " and \\ backslash, newline \n tab \t, controls \x01 \x1f \x7f, separators '
    "   , html <b>&amp;</b> 'single', slash / and emoji 🌟🇹🇷, "
    "Türkçe: çğıöşü İĞÜŞÖÇ, zero width ‍, BOM ﻿ mid-text."
)


def envelope_vectors(t: dict[str, Tau]) -> list[dict[str, Any]]:
    alice, bob, dev, universe = t["alice"], t["bob"], t["dev"], t["universe"]
    first = "01J0000000000000000000REQ1"
    return [
        envelope_case(
            "contact_request",
            alice,
            bob,
            kind="contact_request",
            content={"name": "Alice's tau", "text": "Merhaba Bob! Tanışalım mı? 🌿"},
            envelope_id=first,
            note="a new conversation: thread defaults to the envelope's own id",
        ),
        envelope_case(
            "contact_accept",
            bob,
            alice,
            kind="contact_accept",
            content={"name": "Bob's tau"},
            envelope_id="01J0000000000000000000ACC1",
            thread=first,
            reply_to=first,
            hops=1,
            note="an answer: same thread, reply_to, hops + 1",
        ),
        envelope_case(
            "message_tricky_text",
            alice,
            bob,
            kind="message",
            content={"text": TRICKY_TEXT},
            envelope_id="01J0000000000000000000MSG1",
            note="JSON escapes and non-ASCII text must encode to the same bytes in both halves",
        ),
        envelope_case(
            "message_for_sub",
            alice,
            bob,
            kind="message",
            content={"text": "Can your coach look at my 10k plan?", "sub": "coach"},
            envelope_id="01J0000000000000000000SUB1",
            note="even hops: sub names one of the receiver's sub-taus",
        ),
        envelope_case(
            "message_from_sub",
            bob,
            alice,
            kind="message",
            content={"text": "Sure: three easy runs a week to start.", "sub": "coach"},
            envelope_id="01J0000000000000000000SUB2",
            thread="01J0000000000000000000SUB1",
            reply_to="01J0000000000000000000SUB1",
            hops=1,
            note="odd hops: sub names the sender's sub-tau that answered",
        ),
        envelope_case(
            "message_unknown_keys",
            bob,
            alice,
            kind="message",
            content={"text": "Hello", "sub": None, "mood": "curious"},
            envelope_id="01J0000000000000000000UNK1",
            note="sub null means none, and receivers ignore keys they do not know",
        ),
        envelope_case(
            "message_dev_address",
            dev,
            bob,
            kind="message",
            content={"text": "From a development spine on 127.0.0.1:8787."},
            envelope_id="01J0000000000000000000DEV1",
            note="an address with a port",
        ),
        envelope_case(
            "visit",
            universe,
            bob,
            kind="visit",
            content={"text": "Hi! Can you help me plan a 10k?", "sub": "coach"},
            envelope_id="01J0000000000000000000VIS1",
            thread="visitor-thread-000000000001",
            note="ADR 0013 §5: a universe relays a visitor's text to a hub-run web sub-tau",
            primitives=True,
        ),
    ]


def _flip_last_byte(text: str) -> str:
    data = bytearray(b64u_decode(text))
    data[-1] ^= 0x01
    return b64u_encode(bytes(data))


def bad_envelope_vectors(t: dict[str, Tau], good: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Envelopes that must not verify (``bad_signature``) or not open (``box``)."""
    alice, bob = t["alice"], t["bob"]
    base = next(case for case in good if case["name"] == "message_tricky_text")
    wire = base["envelope"]
    payload_bytes = b64u_decode(wire["payload"])

    tampered = json.loads(payload_bytes)
    tampered["ts"] += 1
    tampered_bytes = json.dumps(tampered, separators=(",", ":"), ensure_ascii=False).encode()

    moved = dict(json.loads(payload_bytes), id="01J0000000000000000MOVED1")
    moved["thread"] = moved["id"]
    moved_bytes = json.dumps(moved, separators=(",", ":"), ensure_ascii=False).encode()

    cases = [
        {
            "name": "flipped_signature",
            "envelope": {"payload": wire["payload"], "sig": _flip_last_byte(wire["sig"])},
            "sign_key": alice.identity.sign_key,
            "expect": "bad_signature",
        },
        {
            "name": "other_sign_key",
            "envelope": wire,
            "sign_key": bob.identity.sign_key,
            "expect": "bad_signature",
        },
        {
            "name": "tampered_payload",
            "envelope": {"payload": b64u_encode(tampered_bytes), "sig": wire["sig"]},
            "sign_key": alice.identity.sign_key,
            "expect": "bad_signature",
        },
        {
            "name": "universe_signature",
            "envelope": {
                "payload": wire["payload"],
                "sig": b64u_encode(alice.identity.sign(UNIVERSE_CONTEXT + payload_bytes)),
            },
            "sign_key": alice.identity.sign_key,
            "expect": "bad_signature",
        },
        {
            "name": "box_moved_to_another_header",
            "envelope": {
                "payload": b64u_encode(moved_bytes),
                "sig": b64u_encode(sign_payload(alice.identity, moved_bytes)),
            },
            "sign_key": alice.identity.sign_key,
            "open_with": "bob",
            "expect": "box",
        },
        {
            "name": "opened_by_the_wrong_tau",
            "envelope": wire,
            "sign_key": alice.identity.sign_key,
            "open_with": "alice",
            "expect": "box",
        },
    ]
    for case in cases:  # tau-net itself must refuse each one the same way
        _expect_refused(case, t)
    return cases


def _expect_refused(case: dict[str, Any], t: dict[str, Tau]) -> None:
    envelope = Envelope.from_json(case["envelope"])
    try:
        payload = open_verified(envelope, case["sign_key"])
    except BadSignature:
        if case["expect"] == "bad_signature":
            return
        raise
    if case["expect"] != "box":
        raise RuntimeError(f"{case['name']}: tau-net verified an envelope it must refuse")
    try:
        open_box(payload.box, t[case["open_with"]].identity, payload.aad)
    except BoxError:
        return
    raise RuntimeError(f"{case['name']}: tau-net opened a box it must refuse")


def reference_vector(t: dict[str, Tau]) -> dict[str, Any]:
    """The test vector of docs/reference/tau-network.md §3, signed again by tau-net."""
    payload = Payload(
        id="01J0000000000000000000TEST",
        kind="message",
        sender="alice.example",
        recipient="bob.example",
        ts=TS,
        thread="01J0000000000000000000TEST",
        reply_to=None,
        hops=0,
        box=Box(epk="AAAA", nonce="AAAAAAAAAAAAAAAA", ct="AAAA"),
    )
    payload_bytes = payload.to_bytes()
    alice = t["alice"].identity
    return {
        "sign_seed": b64u_encode(alice.sign_seed),
        "box_seed": b64u_encode(alice.box_seed),
        "sign_key": alice.sign_key,
        "box_key": alice.box_key,
        "payload_json": payload_bytes.decode("utf-8"),
        "payload": b64u_encode(payload_bytes),
        "sig": b64u_encode(sign_payload(alice, payload_bytes)),
    }


# -- universe requests -------------------------------------------------------------------------


def universe_vectors(t: dict[str, Tau]) -> list[dict[str, Any]]:
    alice = t["alice"]
    common = {"universe": UNIVERSE, "address": alice.address, "ts": TS}
    fields: list[tuple[str, str, dict[str, Any]]] = [
        ("join", "join", {"owner": "Alice", "about": "Builds small robots. Türkçe de konuşur 🌿"}),
        (
            "report",
            "report",
            {
                "links": [
                    {"peer": "bob.example.com", "messages": 14},
                    {"peer": "127.0.0.1:8787", "messages": 0},
                ],
                "subs": [
                    {"name": "coach", "about": "A patient running coach."},
                    {"name": "study-buddy", "about": ""},
                ],
            },
        ),
        ("report_without_subs", "report", {"links": []}),
        ("leave", "leave", {}),
    ]
    cases = []
    for name, kind, extra in fields:
        payload = make_payload(kind, **common, **extra)
        request = build_request(alice.identity, payload)
        cases.append(
            {
                "name": name,
                "built_with": "make_payload",
                "signer": alice.label,
                "input": {"kind": kind, **common, **extra},
                "payload": payload,
                "request": request.to_json(),
            }
        )
    # ADR 0013 §6: a claim, whose payload this tau-net's make_payload may not know yet.
    claim = {"v": 1, "kind": "claim", **common, "nonce": "cLaImNoNcE-0123456789ab"}
    cases.append(
        {
            "name": "claim",
            "built_with": "build_request",
            "signer": alice.label,
            "input": {"kind": "claim", **common, "nonce": claim["nonce"]},
            "payload": claim,
            "request": build_request(alice.identity, claim).to_json(),
        }
    )
    return cases


def domain_separation(t: dict[str, Tau]) -> dict[str, Any]:
    """One payload signed in both domains: each signature verifies only in its own."""
    alice = t["alice"].identity
    payload_bytes = b'{"v":1,"kind":"leave","universe":"universe.example.com"}'
    return {
        "sign_key": alice.sign_key,
        "payload": b64u_encode(payload_bytes),
        "envelope_sig": b64u_encode(alice.sign(SIGNATURE_CONTEXT + payload_bytes)),
        "universe_sig": b64u_encode(alice.sign(UNIVERSE_CONTEXT + payload_bytes)),
    }


# -- the file ----------------------------------------------------------------------------------


def make_vectors() -> dict[str, Any]:
    t = taus()
    envelopes = envelope_vectors(t)
    return {
        "about": (
            "Test vectors from tau-net for cloud/shared/net (issue 158). Generated by "
            "packages/tau-net/scripts/make_ts_vectors.py; do not edit. Every key is test-only."
        ),
        "identities": identity_vectors(t),
        "b64u": b64u_vectors(),
        "addresses": address_vectors(),
        "reference": reference_vector(t),
        "envelopes": envelopes,
        "bad_envelopes": bad_envelope_vectors(t, envelopes),
        "universe": universe_vectors(t),
        "domain_separation": domain_separation(t),
    }


def render(vectors: dict[str, Any]) -> str:
    return json.dumps(vectors, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the file is stale")
    args = parser.parse_args(argv)
    vectors = make_vectors()
    if args.check:  # the content counts, not the formatting
        try:
            current = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = None
        if current != vectors:
            print(f"{VECTORS_PATH.relative_to(REPO)} is stale: run this script", file=sys.stderr)
            return 1
        print(f"{VECTORS_PATH.relative_to(REPO)} is up to date")
        return 0
    text = render(vectors)
    VECTORS_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {VECTORS_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
