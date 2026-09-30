"""Protocol v1 building blocks: base64url, addresses, identity files, envelopes (§1–§3)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from tau_net.encoding import (
    AddressError,
    EncodingError,
    b64u_decode,
    b64u_encode,
    base_url,
    insecure_allowed,
    is_valid_address,
    parse_address,
)
from tau_net.envelope import (
    MAX_MESSAGE_CHARS,
    BadSignature,
    Box,
    BoxError,
    Envelope,
    EnvelopeTooLarge,
    MalformedEnvelope,
    Payload,
    aad_for,
    build_envelope,
    open_box,
    open_verified,
    parse_content,
    peek_sender,
    seal,
    sign_payload,
    verify_signature,
)
from tau_net.identity import (
    IDENTITY_ENV,
    Identity,
    IdentityError,
    IdentityExists,
    create_identity,
    identity_path,
    load_identity,
    load_or_none,
)

# -- the test vector of §3 ---------------------------------------------------------------------

VECTOR_SIGN_SEED = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
VECTOR_BOX_SEED = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8"
VECTOR_SIGN_KEY = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
VECTOR_BOX_KEY = "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ"
VECTOR_PAYLOAD = (
    "eyJ2IjoxLCJpZCI6IjAxSjAwMDAwMDAwMDAwMDAwMDAwMDBURVNUIiwia2luZCI6Im1lc3NhZ2UiLCJmcm9tIjoiYW"
    "xpY2UuZXhhbXBsZSIsInRvIjoiYm9iLmV4YW1wbGUiLCJ0cyI6MTc5MDAwMDAwMCwidGhyZWFkIjoiMDFKMDAwMDAw"
    "MDAwMDAwMDAwMDAwMFRFU1QiLCJyZXBseV90byI6bnVsbCwiaG9wcyI6MCwiYm94Ijp7ImVwayI6IkFBQUEiLCJub2"
    "5jZSI6IkFBQUFBQUFBQUFBQUFBQUEiLCJjdCI6IkFBQUEifX0"
)
VECTOR_SIG = (
    "i5FlOZ4PsX_WU1zPYN7jG7nFGns4HZl2Il6w5l6C74AB04RR73X0v3L-TOHYODQwgQ-GrzBAOpavFfVlDx1kBQ"
)
VECTOR_JSON = (
    '{"v":1,"id":"01J0000000000000000000TEST","kind":"message","from":"alice.example",'
    '"to":"bob.example","ts":1790000000,"thread":"01J0000000000000000000TEST","reply_to":null,'
    '"hops":0,"box":{"epk":"AAAA","nonce":"AAAAAAAAAAAAAAAA","ct":"AAAA"}}'
)


def vector_identity() -> Identity:
    return Identity(b64u_decode(VECTOR_SIGN_SEED), b64u_decode(VECTOR_BOX_SEED))


def test_the_vector_keys_match() -> None:
    identity = vector_identity()
    assert b64u_decode(VECTOR_SIGN_SEED) == bytes(range(32))
    assert b64u_decode(VECTOR_BOX_SEED) == bytes(range(32, 64))
    assert identity.sign_key == VECTOR_SIGN_KEY
    assert identity.box_key == VECTOR_BOX_KEY


def test_the_vector_payload_and_signature_are_reproduced() -> None:
    payload = Payload(
        id="01J0000000000000000000TEST",
        kind="message",
        sender="alice.example",
        recipient="bob.example",
        ts=1790000000,
        thread="01J0000000000000000000TEST",
        reply_to=None,
        hops=0,
        box=Box(epk="AAAA", nonce="AAAAAAAAAAAAAAAA", ct="AAAA"),
    )
    assert payload.to_bytes().decode() == VECTOR_JSON
    assert b64u_encode(payload.to_bytes()) == VECTOR_PAYLOAD
    assert b64u_decode(VECTOR_PAYLOAD).decode() == VECTOR_JSON
    signature = sign_payload(vector_identity(), payload.to_bytes())
    assert b64u_encode(signature) == VECTOR_SIG


def test_the_vector_verifies_and_parses_after_verification() -> None:
    envelope = Envelope(VECTOR_PAYLOAD, VECTOR_SIG)
    assert peek_sender(envelope) == "alice.example"
    payload = open_verified(envelope, VECTOR_SIGN_KEY)
    assert payload.id == "01J0000000000000000000TEST"
    assert (payload.sender, payload.recipient, payload.hops) == ("alice.example", "bob.example", 0)
    with pytest.raises(BadSignature):
        open_verified(envelope, VECTOR_BOX_KEY)  # a different key
    tampered = b64u_encode(b64u_decode(VECTOR_PAYLOAD).replace(b'"hops":0', b'"hops":1'))
    with pytest.raises(BadSignature):
        open_verified(Envelope(tampered, VECTOR_SIG), VECTOR_SIGN_KEY)


# -- base64url and addresses -------------------------------------------------------------------


def test_b64u_has_no_padding_and_decodes_with_or_without_it() -> None:
    assert b64u_encode(b"\xfb\xff") == "-_8"
    assert b64u_decode("-_8") == b"\xfb\xff"
    assert b64u_decode("-_8=") == b"\xfb\xff"
    assert b64u_decode("") == b""
    for bad in ("+/8", "-_8 ", "A", "AB=", "AAAA=", "-_8==", "a\nb"):
        with pytest.raises(EncodingError):
            b64u_decode(bad)


@pytest.mark.parametrize(
    "address",
    ["tau.example.com", "tau-spine.alice.workers.dev", "127.0.0.1:8787", "localhost", "a"],
)
def test_valid_addresses(address: str) -> None:
    assert is_valid_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "Tau.example.com",
        "tau.example.com\n",
        "-tau.example.com",
        "tau-.example.com",
        "tau..example.com",
        "tau.example.com/",
        "https://tau.example.com",
        "tau.example.com:123456",
        "tau_example.com",
        "",
        None,
        "a" * 64 + ".com",
    ],
)
def test_invalid_addresses(address: object) -> None:
    assert not is_valid_address(address)


def test_parse_address_forgives_what_people_type() -> None:
    assert parse_address("  HTTPS://Tau.Example.com/ ") == "tau.example.com"
    assert parse_address("http://127.0.0.1:8787") == "127.0.0.1:8787"
    with pytest.raises(AddressError):
        parse_address("tau example")


def test_the_scheme_is_https_except_for_local_development() -> None:
    assert base_url("tau.example.com") == "https://tau.example.com"
    assert base_url("127.0.0.1:8787") == "https://127.0.0.1:8787"
    assert base_url("127.0.0.1:8787", allow_insecure=True) == "http://127.0.0.1:8787"
    assert base_url("localhost:8787", allow_insecure=True) == "http://localhost:8787"
    assert base_url("tau.example.com", allow_insecure=True) == "https://tau.example.com"
    assert base_url("10.0.0.1", allow_insecure=True) == "https://10.0.0.1"
    assert insecure_allowed({"TAU_NET_ALLOW_INSECURE": "1"})
    assert not insecure_allowed({"TAU_NET_ALLOW_INSECURE": "true"})
    assert not insecure_allowed({})


# -- identity ----------------------------------------------------------------------------------


def test_create_identity_writes_private_modes_and_never_overwrites(tmp_path: Path) -> None:
    path = identity_path(tmp_path / "data")
    identity = create_identity(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    data = json.loads(path.read_text())
    assert data["v"] == 1 and set(data) == {"v", "sign_seed", "box_seed"}
    before = path.read_bytes()
    with pytest.raises(IdentityExists):
        create_identity(path)
    assert path.read_bytes() == before
    loaded = load_identity(path)
    assert loaded.sign_key == identity.sign_key and loaded.box_key == identity.box_key
    assert loaded.source == f"file:{path}"


def test_identity_env_replaces_the_file(tmp_path: Path) -> None:
    path = identity_path(tmp_path)
    on_disk = create_identity(path)
    other = Identity.generate()
    loaded = load_identity(path, {IDENTITY_ENV: other.to_env_value()})
    assert loaded.source == "env"
    assert loaded.sign_key == other.sign_key != on_disk.sign_key
    with pytest.raises(IdentityError, match=IDENTITY_ENV):
        load_identity(path, {IDENTITY_ENV: "not-json"})


def test_missing_and_broken_identities(tmp_path: Path) -> None:
    path = identity_path(tmp_path)
    assert load_or_none(path) is None
    path.parent.mkdir(parents=True)
    path.write_text('{"v": 1, "sign_seed": "AAAA", "box_seed": "AAAA"}')
    with pytest.raises(IdentityError, match="32 bytes"):
        load_identity(path)
    path.write_text("nope")
    with pytest.raises(IdentityError, match="not JSON"):
        load_identity(path)


def test_seeds_never_appear_in_repr() -> None:
    identity = vector_identity()
    text = repr(identity)
    assert VECTOR_SIGN_SEED not in text and "sign_seed" not in text
    assert str(bytes(range(32))) not in text


# -- sealing and envelopes ---------------------------------------------------------------------


def test_seal_and_open_round_trip() -> None:
    bob = Identity.generate()
    aad = aad_for("x" * 20, "message", "alice.example", "bob.example")
    box = seal({"text": "Merhaba, çok güzel ✓"}, bob.box_key, aad)
    assert open_box(box, bob, aad) == {"text": "Merhaba, çok güzel ✓"}
    with pytest.raises(BoxError):
        open_box(box, Identity.generate(), aad)  # someone else


@pytest.mark.parametrize("field", ["id", "kind", "from", "to"])
def test_a_box_cannot_move_to_another_header(field: str) -> None:
    bob = Identity.generate()
    header = {"id": "x" * 20, "kind": "message", "from": "alice.example", "to": "bob.example"}
    box = seal({"text": "hi"}, bob.box_key, aad_for(*header.values()))
    changed = dict(header)
    changed[field] = {"id": "y" * 20, "kind": "contact_request"}.get(field, "eve.example")
    with pytest.raises(BoxError):
        open_box(box, bob, aad_for(*changed.values()))


@pytest.mark.parametrize("part", ["epk", "nonce", "ct"])
def test_tampering_with_the_box_fails(part: str) -> None:
    bob = Identity.generate()
    aad = aad_for("x" * 20, "message", "alice.example", "bob.example")
    box = seal({"text": "hi"}, bob.box_key, aad)
    raw = bytearray(b64u_decode(getattr(box, part)))
    raw[0] ^= 1
    fields = box.to_json() | {part: b64u_encode(bytes(raw))}
    with pytest.raises(BoxError):
        open_box(Box(**fields), bob, aad)


def build(alice: Identity, bob: Identity, **kw: object) -> tuple[Envelope, Payload]:
    params: dict = {
        "sender": "alice.example",
        "recipient": "bob.example",
        "recipient_box_key": bob.box_key,
        "kind": "message",
        "content": {"text": "When are you free?"},
    }
    params.update(kw)
    return build_envelope(alice, **params)


def test_build_verify_and_open_an_envelope() -> None:
    alice, bob = Identity.generate(), Identity.generate()
    envelope, payload = build(alice, bob)
    assert payload.thread == payload.id and payload.reply_to is None and payload.hops == 0
    parsed = open_verified(Envelope.from_json(envelope.to_json()), alice.sign_key)
    assert parsed == payload
    content = parse_content(parsed.kind, open_box(parsed.box, bob, parsed.aad))
    assert content == {"text": "When are you free?"}


@pytest.mark.parametrize("field", ["v", "id", "kind", "to", "ts", "thread", "reply_to", "hops"])
def test_tampering_with_any_payload_field_breaks_the_signature(field: str) -> None:
    alice, bob = Identity.generate(), Identity.generate()
    envelope, payload = build(alice, bob)
    data = payload.to_json()
    data[field] = {
        "v": 2,
        "id": "z" * 20,
        "kind": "contact_request",
        "to": "eve.example",
        "ts": payload.ts + 1,
        "thread": "t" * 20,
        "reply_to": "r" * 20,
        "hops": 1,
    }[field]
    forged = Envelope(b64u_encode(json.dumps(data).encode()), envelope.sig)
    with pytest.raises(BadSignature):
        open_verified(forged, alice.sign_key)


def test_a_signature_is_bound_to_its_context() -> None:
    alice = Identity.generate()
    data = b'{"v":1}'
    bare = alice.sign(data)  # no "tau-net/1\n" prefix
    with pytest.raises(BadSignature):
        verify_signature(alice.sign_key, data, bare)
    verify_signature(alice.sign_key, data, sign_payload(alice, data))


def test_malformed_envelopes_are_named() -> None:
    with pytest.raises(MalformedEnvelope, match="string payload"):
        Envelope.from_json({"payload": 1, "sig": "AAAA"})
    with pytest.raises(MalformedEnvelope, match="base64url"):
        Envelope.from_json({"payload": "+++", "sig": "AAAA"})
    alice, bob = Identity.generate(), Identity.generate()
    _, payload = build(alice, bob)
    for field, value, reason in [
        ("hops", -1, "hops"),
        ("hops", True, "hops"),
        ("kind", "gossip", "kind"),
        ("from", "Alice", "from"),
        ("id", "short", "id"),
        ("reply_to", "short", "reply_to"),
        ("ts", "now", "ts"),
    ]:
        with pytest.raises(MalformedEnvelope, match=reason):
            Payload.from_json(payload.to_json() | {field: value})
    with pytest.raises(MalformedEnvelope, match="misses box"):
        Payload.from_json({k: v for k, v in payload.to_json().items() if k != "box"})


def test_content_rules_per_kind() -> None:
    assert parse_content("contact_request", {"name": "A", "text": ""}) == {"name": "A", "text": ""}
    assert parse_content("contact_accept", {"name": "A", "extra": 1}) == {"name": "A"}
    with pytest.raises(BoxError):
        parse_content("contact_request", {"name": "A"})
    with pytest.raises(BoxError):
        parse_content("message", {"text": 3})
    with pytest.raises(BoxError, match="8000"):
        parse_content("message", {"text": "x" * (MAX_MESSAGE_CHARS + 1)})
    parse_content("message", {"text": "x" * MAX_MESSAGE_CHARS})


def test_an_envelope_that_would_not_fit_the_inbox_is_refused() -> None:
    alice, bob = Identity.generate(), Identity.generate()
    build(alice, bob, content={"text": "ç" * MAX_MESSAGE_CHARS})  # 16 000 bytes fit
    with pytest.raises(EnvelopeTooLarge):
        build(alice, bob, content={"text": "\x01" * MAX_MESSAGE_CHARS})  # \u0001 escapes do not
