"""The tau universe protocol (ADR 0010, docs/reference/tau-universe.md §1–§2): signed
requests, their checks, link selection, the ``[component.net]`` universe settings and the
client against a :class:`tau_net.testing.FakeUniverse`. Offline: every host is a fake."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from net_helpers import ALICE, BOB, UNIVERSE, published, universe_tau
from tau_net.config import NetConfigError, NetSettings
from tau_net.envelope import BadSignature, sign_payload, verify_signature
from tau_net.identity import Identity
from tau_net.testing import FakeNetwork, FakeUniverse
from tau_net.universe import (
    DEFAULT_UNIVERSE,
    MAX_LINKS,
    UNIVERSE_CONTEXT,
    MalformedRequest,
    UniverseClient,
    UniverseError,
    build_request,
    encode_payload,
    make_payload,
    parse_request,
    select_links,
    tau_links,
    verify_request,
)

CAROL = "carol.example"
DAVE = "dave.example"


# -- signed requests ---------------------------------------------------------------------------


def test_signature_prefix_and_payload_shape() -> None:
    identity = Identity.generate()
    payload = make_payload(
        "join", universe=UNIVERSE, address=ALICE, ts=1_790_000_000, owner="Alice", about="Hi"
    )
    assert list(payload) == ["v", "kind", "universe", "address", "ts", "owner", "about"]
    request = build_request(identity, payload)
    payload_bytes = request.payload_bytes
    assert payload_bytes == encode_payload(payload)
    assert payload_bytes.startswith(b'{"v":1,"kind":"join","universe":"universe.example"')
    assert UNIVERSE_CONTEXT == b"tau-universe/1\n"
    public = Ed25519PublicKey.from_public_bytes(identity.sign_key_bytes)
    public.verify(request.sig_bytes, b"tau-universe/1\n" + payload_bytes)  # raises if wrong
    verify_request(identity.sign_key, payload_bytes, request.sig_bytes)
    # the prefixes keep the two protocols apart: neither signature is valid in the other place
    with pytest.raises(BadSignature):
        verify_signature(identity.sign_key, payload_bytes, request.sig_bytes)
    envelope_sig = sign_payload(identity, payload_bytes)
    with pytest.raises(BadSignature):
        verify_request(identity.sign_key, payload_bytes, envelope_sig)
    with pytest.raises(BadSignature):
        verify_request(Identity.generate().sign_key, payload_bytes, request.sig_bytes)
    # the wire body parses back to the same payload
    parsed = parse_request(request.to_bytes())
    assert parsed.payload == payload and parsed.payload_bytes == payload_bytes

    report = make_payload(
        "report", universe=UNIVERSE, address=ALICE, ts=1, links=[{"peer": BOB, "messages": 3}]
    )
    assert list(report) == ["v", "kind", "universe", "address", "ts", "links"]
    assert report["links"] == [{"peer": BOB, "messages": 3}]
    leave = make_payload("leave", universe=UNIVERSE, address=ALICE, ts=1)
    assert list(leave) == ["v", "kind", "universe", "address", "ts"]


@pytest.mark.parametrize(
    ("kind", "fields", "reason"),
    [
        ("join", {"owner": "x" * 61}, "payload.owner"),
        ("join", {"about": "x" * 201}, "payload.about"),
        ("report", {"links": [{"peer": BOB, "messages": 1}] * (MAX_LINKS + 1)}, "payload.links"),
        ("report", {"links": [{"peer": "Not An Address", "messages": 1}]}, "peer"),
        ("report", {"links": [{"peer": BOB, "messages": -1}]}, "messages"),
        ("report", {"links": [{"peer": BOB, "messages": True}]}, "messages"),
        ("hello", {}, "payload.kind"),
    ],
)
def test_payload_checks(kind: str, fields: dict, reason: str) -> None:
    with pytest.raises(MalformedRequest, match=reason):
        make_payload(kind, universe=UNIVERSE, address=ALICE, ts=1, **fields)


def test_parse_request_refuses_malformed_bodies() -> None:
    identity = Identity.generate()
    good = build_request(identity, make_payload("leave", universe=UNIVERSE, address=ALICE, ts=1))
    for body, reason in [
        (b"not json", "not UTF-8 JSON"),
        (b"[]", "not a JSON object"),
        (b'{"payload": 1, "sig": "x"}', "string payload and sig"),
        (b'{"payload": "***", "sig": "x"}', "base64url"),
        (json.dumps({"payload": good.payload[:-4], "sig": good.sig}).encode(), "payload"),
    ]:
        with pytest.raises(MalformedRequest, match=reason):
            parse_request(body)
    bad_address = dict(json.loads(good.payload_bytes), address="-bad-")
    with pytest.raises(MalformedRequest, match="payload.address"):
        parse_request(build_request(identity, bad_address).to_bytes())


def test_select_links_keeps_listed_accepted_contacts_only() -> None:
    counts = {BOB: {"in": 2, "out": 3}, CAROL: {"in": 9, "out": 9}, DAVE: {"in": "x"}}
    links = select_links([BOB, CAROL, DAVE, ALICE], counts, {BOB, DAVE, ALICE}, own_address=ALICE)
    assert links == [{"peer": BOB, "messages": 5}, {"peer": DAVE, "messages": 0}]
    assert select_links([BOB], counts, set()) == []
    entry = {"links": [{"a": ALICE, "b": BOB, "messages": 4}, {"peer": CAROL, "messages": 7}]}
    assert tau_links(entry, ALICE) == [(CAROL, 7), (BOB, 4)]
    assert tau_links({"tau": {"links": [{"a": BOB, "b": ALICE, "messages": 1}]}}, ALICE) == [
        (BOB, 1)
    ]


# -- settings ------------------------------------------------------------------


def test_universe_settings_are_validated() -> None:
    settings = NetSettings.from_mapping({})
    assert settings.universe == DEFAULT_UNIVERSE == "tau.getporti.com"
    assert settings.universe_links is True and settings.universe_report_minutes == 60
    assert NetSettings.from_mapping({"universe": ""}).universe == ""
    assert NetSettings.from_mapping({"universe": "https://Tau.Example.com/"}).universe == (
        "tau.example.com"
    )
    for bad in (
        {"universe": "not a host"},
        {"universe": 7},
        {"universe_links": "yes"},
        {"universe_report_minutes": 4},
        {"universe_report_minutes": 1441},
        {"universe_report_minutes": True},
    ):
        with pytest.raises(NetConfigError):
            NetSettings.from_mapping(bad)


def test_personal_values_are_not_tau_toml_settings(caplog) -> None:
    caplog.set_level(logging.WARNING)
    settings = NetSettings.from_mapping({"universe_join": True, "universe_owner": "Alice"})
    assert not hasattr(settings, "universe_join") and not hasattr(settings, "universe_owner")
    assert "ignores unknown keys: universe_join, universe_owner" in caplog.text


# -- the client against a FakeUniverse ---------------------------------------------------------


def test_join_report_leave(tmp_path: Path, network: FakeNetwork, universe: FakeUniverse) -> None:
    tau = universe_tau(tmp_path, network, ALICE)
    published(tau)
    now = int(time.time())
    client = UniverseClient(UNIVERSE, transport=network, clock=lambda: now)
    answer = client.join(tau.identity, ALICE, owner="Alice", about="Plans hikes.")
    assert answer == {"ok": True, "url": f"https://{UNIVERSE}/universe#{ALICE}"}
    assert client.report(tau.identity, ALICE, []) == {"ok": True, "visible_links": 0}
    entry = client.tau(ALICE)
    assert entry["name"] == "Alice's tau" and entry["owner"] == "Alice"
    assert entry["links"] == []
    snapshot = client.snapshot()
    assert [t["address"] for t in snapshot["taus"]] == [ALICE]
    assert snapshot["stats"] == {"taus": 1, "online": 1, "messages": 0}
    # one second, two requests: the ts still goes up
    assert [p["ts"] for p in universe.payloads()] == [now, now + 1]
    assert client.leave(tau.identity, ALICE) == {"ok": True}
    assert client.tau(ALICE) is None and universe.taus == {}
    with pytest.raises(UniverseError) as info:
        client.report(tau.identity, ALICE, [])
    assert (info.value.status, info.value.code) == (404, "not_joined")
    assert "run `tau net universe join`" in str(info.value)


def test_universe_error_codes(tmp_path: Path, network: FakeNetwork, universe: FakeUniverse) -> None:
    tau = universe_tau(tmp_path, network, ALICE)
    client = UniverseClient(UNIVERSE, transport=network)

    def code(call: Callable[[], Any]) -> str:
        with pytest.raises(UniverseError) as info:
            call()
        return info.value.code

    assert code(lambda: client.join(tau.identity, ALICE)) == "card_unavailable"  # no card yet
    published(tau)
    stranger = Identity.generate()
    assert code(lambda: client.join(stranger, ALICE)) == "bad_signature"
    assert code(lambda: client.leave(tau.identity, ALICE)) == "not_joined"
    other = network.add(FakeUniverse("other.example"))
    wrong = UniverseClient("other.example", transport=network)
    wrong.host = UNIVERSE  # signs for UNIVERSE, posts to other.example
    assert code(lambda: wrong.join(tau.identity, ALICE)) == "wrong_universe"
    assert other.taus == {}
    old = UniverseClient(UNIVERSE, transport=network, clock=lambda: time.time() - 400)
    assert code(lambda: old.join(tau.identity, ALICE)) == "stale"
    limited = network.add(FakeUniverse("limited.example", rate_per_hour=2))
    few = UniverseClient("limited.example", transport=network)
    few.join(tau.identity, ALICE)
    few.report(tau.identity, ALICE, [])
    assert code(lambda: few.report(tau.identity, ALICE, [])) == "rate_limited"
    assert len(limited.bodies("/api/report")) == 2
    network.down.add(UNIVERSE)
    assert code(client.snapshot) == "unreachable"
    network.down.clear()
    universe.fail("GET", "/api/universe", (500, {"error": "boom", "detail": "D1 is down"}))
    with pytest.raises(UniverseError, match="answered 500 boom"):
        client.snapshot()


def test_a_stale_answer_is_retried_once_with_a_newer_ts(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    tau = universe_tau(tmp_path, network, ALICE)
    published(tau)
    now = int(time.time())
    client = UniverseClient(UNIVERSE, transport=network, clock=lambda: now)
    universe.fail("POST", "/api/join", (400, {"error": "stale"}))
    assert client.join(tau.identity, ALICE)["ok"] is True
    assert [p["ts"] for p in universe.payloads("join")] == [now, now + 1]


def test_scheme_rule(network: FakeNetwork) -> None:
    assert UniverseClient(UNIVERSE).base == f"https://{UNIVERSE}"
    assert UniverseClient("localhost:8788").base == "https://localhost:8788"
    assert UniverseClient("localhost:8788", allow_insecure=True).base == "http://localhost:8788"
    assert UniverseClient("tau.example.com", allow_insecure=True).base == "https://tau.example.com"
    local = network.add(FakeUniverse("localhost:8788"))
    assert local.scheme == "http"
    assert UniverseClient("localhost:8788", transport=network, allow_insecure=True).snapshot()
    with pytest.raises(UniverseError, match="unreachable"):
        UniverseClient("localhost:8788", transport=network).snapshot()


def test_too_large_bodies_are_refused(network: FakeNetwork, universe: FakeUniverse) -> None:
    status, _, body = universe.handle("POST", "/api/join", {}, b"x" * 65_537)
    assert (status, json.loads(body)) == (413, {"error": "too_large"})
    status, _, body = universe.handle("POST", "/api/report", {}, b"{}")
    assert status == 400 and json.loads(body)["error"] == "bad_request"
