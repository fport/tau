"""The spine client, the fake spine's checks (§4, §5) and card fetching (§4, §6.6)."""

from __future__ import annotations

import json
import logging
import threading
import time

import pytest
from tau_net.encoding import b64u_encode
from tau_net.envelope import build_envelope
from tau_net.identity import Identity
from tau_net.peers import CardError, DeliveryError, PeerClient, parse_card
from tau_net.spine import SpineClient, SpineError, SpineUnreachable, TransportError
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeNetwork, FakeSpine

TOKEN = DEFAULT_HUB_TOKEN


def client(spine: FakeSpine, token: str = TOKEN) -> SpineClient:
    return SpineClient(spine.url, token, transport=spine)


def published(address: str, network: FakeNetwork | None = None, **kw: object) -> tuple:
    spine = FakeSpine(address, **kw)  # type: ignore[arg-type]
    if network is not None:
        network.add(spine)
    identity = Identity.generate()
    spine.publish("A tau", identity.sign_key, identity.box_key)
    return spine, identity


# -- the client --------------------------------------------------------------------------------


def test_health_card_updates_and_ack() -> None:
    spine = FakeSpine("tau.example.com")
    spine_client = client(spine)
    health = spine_client.health()
    assert health["address"] == "tau.example.com" and health["mode"] == "local"
    assert health["card"] is False
    assert spine_client.card() is None
    identity = Identity.generate()
    card = spine_client.publish_card("Alice's tau", identity.sign_key, identity.box_key)
    assert card == {
        "v": 1,
        "address": "tau.example.com",
        "name": "Alice's tau",
        "sign_key": identity.sign_key,
        "box_key": identity.box_key,
        "inbox": "https://tau.example.com/net/inbox",
        "software": "tau-spine/0.1.0",
    }
    assert spine_client.card() == card
    assert spine_client.updates(after=0, timeout=0) == []
    assert spine_client.ack([1, 2]) == 0


def test_request_never_raises_for_a_status_and_call_does() -> None:
    spine = FakeSpine("tau.example.com")
    response = client(spine, "wrong").request("GET", "/hub/health")
    assert response.status == 401 and not response.ok
    assert response.json() == {"error": "unauthorized"}
    with pytest.raises(SpineError) as caught:
        client(spine, "wrong").health()
    assert (caught.value.status, caught.value.code) == (401, "unauthorized")
    no_secret = FakeSpine("tau.example.com", hub_token="")
    with pytest.raises(SpineError) as caught:
        client(no_secret).health()
    assert (caught.value.status, caught.value.code) == (503, "not_configured")


def test_the_token_never_shows(caplog: pytest.LogCaptureFixture) -> None:
    secret = "s3cr3t-hub-token-value"
    spine = FakeSpine("tau.example.com", hub_token=secret)
    spine_client = SpineClient(spine.url, secret, transport=spine)
    assert secret not in repr(spine_client)
    spine.fail("GET", "/hub/health", (500, {"error": "boom", "detail": f"echo {secret}"}))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(SpineError) as caught:
        spine_client.health()
    assert secret not in str(caught.value) and "<token>" in str(caught.value)

    def leaky(*args: object) -> tuple:
        raise TransportError(f"connection failed for Bearer {secret}")

    with pytest.raises(SpineUnreachable) as unreachable:
        SpineClient(spine.url, secret, transport=leaky).health()
    assert secret not in str(unreachable.value)
    assert secret not in caplog.text


def test_state_is_cloud_mode_only() -> None:
    local = client(FakeSpine("tau.example.com"))
    with pytest.raises(SpineError) as caught:
        local.state_get("net.contacts")
    assert (caught.value.status, caught.value.code) == (404, "cloud_mode_off")
    cloud = client(FakeSpine("tau.example.com", mode="cloud"))
    assert cloud.state_get("net.contacts", {}) == {}
    cloud.state_put("net.contacts", {"a": 1})
    assert cloud.state_get("net.contacts") == {"a": 1}
    assert cloud.state_delete("net.contacts") is True
    assert cloud.state_delete("net.contacts") is False
    with pytest.raises(ValueError):
        cloud.state_get("Bad Key")


def test_cloud_files_and_unimplemented_routes() -> None:
    spine = FakeSpine("tau.example.com", mode="cloud")
    spine_client = client(spine)
    assert spine_client.call("PUT", "/hub/files/persona/net.md", body="hello")["size"] == 5
    assert spine_client.request("GET", "/hub/files/persona/net.md").text == "hello"
    assert spine_client.request("GET", "/hub/files/secret.txt").status == 404
    assert spine_client.call("GET", "/hub/files")["files"][0]["name"] == "persona/net.md"
    assert spine_client.request("GET", "/hub/sessions").status == 501
    spine.route("GET", r"/hub/brain", lambda request: (200, {"ok": True}))
    assert spine_client.call("GET", "/hub/brain") == {"ok": True}
    local = client(FakeSpine("tau.example.com"))
    assert local.request("GET", "/hub/files").json() == {"error": "cloud_mode_off"}


def test_cloud_sub_tau_files_like_the_real_spine() -> None:
    spine = FakeSpine("tau.example.com", mode="cloud")
    spine_client = client(spine)
    for name in ("coach.public.md", "coach.md", "A1_b-c.d.md"):
        assert spine_client.call("PUT", f"/hub/files/persona/subs/{name}", body="x")["size"] == 1
    spine_client.call("PUT", "/hub/files/tau.toml", body="[ui]\n")
    assert [entry["name"] for entry in spine_client.call("GET", "/hub/files")["files"]] == [
        "tau.toml",
        "persona/subs/A1_b-c.d.md",
        "persona/subs/coach.md",
        "persona/subs/coach.public.md",
    ]
    assert spine_client.request("GET", "/hub/files/persona%2Fsubs%2Fcoach.md").text == "x"
    for odd in (
        "persona/subs/.hidden.md",
        "persona/subs/Bad%20Name.md",
        "persona/subs/x.txt",
        "persona/subs/drafts/x.md",
        "persona/subs/..%2Fuser.md",
        f"persona/subs/{'a' * 82}.md",
    ):
        assert spine_client.request("PUT", f"/hub/files/{odd}", body="x").status == 404, odd
        assert spine_client.request("DELETE", f"/hub/files/{odd}").status == 404, odd
    assert spine_client.call("DELETE", "/hub/files/persona/subs/coach.md") == {"deleted": True}
    assert spine_client.call("DELETE", "/hub/files/persona/subs/coach.md") == {"deleted": False}
    assert "persona/subs/coach.md" not in spine.files


def test_the_long_poll_waits_and_wakes_on_arrival() -> None:
    network = FakeNetwork()
    bob_spine = network.add(FakeSpine("bob.example"))
    alice_spine, alice = published("alice.example", network)
    bob = Identity.generate()
    bob_spine.publish("Bob's tau", bob.sign_key, bob.box_key)
    spine_client = SpineClient(bob_spine.url, TOKEN, transport=network)
    started = time.monotonic()
    assert spine_client.updates(timeout=1) == []
    assert time.monotonic() - started >= 0.9

    def later() -> None:
        time.sleep(0.2)
        envelope, _ = build_envelope(
            alice,
            sender="alice.example",
            recipient="bob.example",
            recipient_box_key=bob.box_key,
            kind="contact_request",
            content={"name": "Alice", "text": ""},
        )
        PeerClient(network).deliver("bob.example", envelope)

    threading.Thread(target=later).start()
    started = time.monotonic()
    updates = spine_client.updates(timeout=5)
    assert len(updates) == 1 and updates[0].seq == 1
    assert time.monotonic() - started < 3
    assert spine_client.updates(after=1) == []
    assert spine_client.ack([1]) == 1
    assert bob_spine.mailbox == []


# -- the inbox of the fake spine ---------------------------------------------------------------


JSON_HEADERS = {"Content-Type": "application/json"}


def inbox(network: FakeNetwork, body: bytes, headers: dict | None = None) -> tuple[int, dict]:
    sent = JSON_HEADERS if headers is None else headers
    status, _, data = network("POST", "https://bob.example/net/inbox", sent, body, 5)
    return status, json.loads(data)


def setup_pair(clock=time.time) -> tuple[FakeNetwork, Identity, Identity, FakeSpine]:
    network = FakeNetwork()
    bob_spine, bob = published("bob.example", network, clock=clock)
    _, alice = published("alice.example", network)
    return network, alice, bob, bob_spine


def envelope_bytes(alice: Identity, bob: Identity, **kw: object) -> bytes:
    params: dict = {
        "sender": "alice.example",
        "recipient": "bob.example",
        "recipient_box_key": bob.box_key,
        "kind": "message",
        "content": {"text": "hi"},
    }
    params.update(kw)
    envelope, _ = build_envelope(alice, **params)
    return envelope.to_bytes()


def test_inbox_accepts_then_reports_duplicates() -> None:
    network, alice, bob, bob_spine = setup_pair()
    body = envelope_bytes(alice, bob, envelope_id="dup-dup-dup-dup-dup")
    assert inbox(network, body) == (202, {"status": "queued", "id": "dup-dup-dup-dup-dup"})
    assert inbox(network, body) == (200, {"status": "duplicate", "id": "dup-dup-dup-dup-dup"})
    assert len(bob_spine.mailbox) == 1


def test_inbox_checks_in_order() -> None:
    network, alice, bob, bob_spine = setup_pair()
    for headers in ({}, {"Content-Type": "text/plain"}):
        status, data = inbox(network, envelope_bytes(alice, bob), headers)
        assert (status, data) == (415, {"error": "unsupported_media_type"})
    assert inbox(network, b"x" * 70_000, {})[0] == 415
    typed = {"content-type": "application/json; charset=utf-8"}
    assert inbox(network, envelope_bytes(alice, bob), typed)[0] == 202
    bob_spine.mailbox.clear()
    assert inbox(network, b"x" * 70_000)[0] == 413
    status, data = inbox(network, b'{"payload": "AAAA"}')
    assert status == 400 and data["error"] == "bad_request"
    status, data = inbox(network, envelope_bytes(alice, bob, recipient="carol.example"))
    assert (status, data) == (400, {"error": "wrong_recipient"})
    status, data = inbox(network, envelope_bytes(alice, bob, ts=int(time.time()) - 301))
    assert (status, data) == (400, {"error": "stale"})
    stranger = Identity.generate()
    status, data = inbox(network, envelope_bytes(stranger, bob, sender="nobody.example"))
    assert (status, data) == (502, {"error": "sender_card_unavailable"})
    status, data = inbox(network, envelope_bytes(stranger, bob))  # alice's card, wrong key
    assert (status, data) == (403, {"error": "bad_signature"})
    assert bob_spine.mailbox == []


def test_inbox_rate_limit_and_full_mailbox() -> None:
    network, alice, bob, bob_spine = setup_pair()
    for _ in range(60):
        assert inbox(network, envelope_bytes(alice, bob))[0] == 202
    assert inbox(network, envelope_bytes(alice, bob)) == (429, {"error": "rate_limited"})
    bob_spine.arrivals.clear()
    bob_spine.mailbox = bob_spine.mailbox * 17  # 1 020 undelivered
    assert inbox(network, envelope_bytes(alice, bob)) == (503, {"error": "mailbox_full"})


def test_card_endpoint_headers_and_root() -> None:
    spine, _ = published("tau.example.com")
    status, headers, body = spine.handle("GET", "/.well-known/tau.json", {})
    assert status == 200 and headers["access-control-allow-origin"] == "*"
    assert headers["cache-control"] == "public, max-age=300"
    assert spine.handle("GET", "/", {})[2] == b"tau spine tau.example.com"
    empty = FakeSpine("tau.example.com")
    assert empty.handle("GET", "/.well-known/tau.json", {})[0] == 404


def test_the_network_refuses_plain_http_and_unknown_hosts() -> None:
    network = FakeNetwork([FakeSpine("tau.example.com"), FakeSpine("127.0.0.1:8787")])
    with pytest.raises(TransportError, match="plain http"):
        network("GET", "http://tau.example.com/", {}, None, 1)
    with pytest.raises(TransportError, match="no route"):
        network("GET", "https://elsewhere.example/", {}, None, 1)
    assert network("GET", "http://127.0.0.1:8787/", {}, None, 1)[0] == 200
    network.spines["tau.example.com"].down = True
    with pytest.raises(TransportError, match="refused"):
        network("GET", "https://tau.example.com/", {}, None, 1)


# -- cards and delivery ------------------------------------------------------------------------


def test_fetch_card_checks() -> None:
    network = FakeNetwork()
    spine, identity = published("bob.example", network)
    peers = PeerClient(network)
    card = peers.fetch_card("bob.example")
    assert card.sign_key == identity.sign_key and card.box_key == identity.box_key
    with pytest.raises(CardError, match="HTTP 404"):
        spine.card = None
        peers.fetch_card("bob.example")
    with pytest.raises(CardError, match="no answer"):
        peers.fetch_card("nobody.example")
    good = {
        "v": 1,
        "address": "bob.example",
        "sign_key": identity.sign_key,
        "box_key": identity.box_key,
    }
    for change, reason in [
        ({"address": "eve.example"}, "address"),
        ({"v": 2}, "v1"),
        ({"sign_key": b64u_encode(b"short")}, "sign_key"),
        ({"box_key": 7}, "box_key"),
    ]:
        with pytest.raises(CardError, match=reason):
            parse_card("bob.example", json.dumps(good | change).encode())
    with pytest.raises(CardError, match="larger"):
        parse_card("bob.example", json.dumps(good | {"name": "x" * 9000}).encode())


def test_insecure_peers_only_on_localhost_when_allowed() -> None:
    network = FakeNetwork()
    published("127.0.0.1:8787", network)
    assert PeerClient(network, allow_insecure=True).fetch_card("127.0.0.1:8787")
    assert network.requests[-1][1].startswith("http://127.0.0.1:8787/")
    with pytest.raises(CardError):
        PeerClient(network).fetch_card("127.0.0.1:8787")  # https: nothing listens there
    assert network.requests[-1][1].startswith("https://")


def test_deliver_reports_errors() -> None:
    network, alice, bob, bob_spine = setup_pair()
    peers = PeerClient(network)
    envelope, _ = build_envelope(
        alice,
        sender="alice.example",
        recipient="bob.example",
        recipient_box_key=bob.box_key,
        kind="message",
        content={"text": "hi"},
    )
    assert peers.deliver("bob.example", envelope).status == "queued"
    assert peers.deliver("bob.example", envelope).status == "duplicate"
    bob_spine.fail("POST", "/net/inbox", (429, {"error": "rate_limited"}))
    with pytest.raises(DeliveryError) as caught:
        peers.deliver("bob.example", envelope)
    assert (caught.value.status, caught.value.code) == (429, "rate_limited")
    with pytest.raises(DeliveryError, match="unreachable"):
        peers.deliver("nobody.example", envelope)


def test_a_local_peer_without_insecure_gets_a_hint() -> None:
    from tau_net.peers import CardError

    def refuse(method, url, headers, body, timeout):
        raise ConnectionRefusedError("refused")

    with pytest.raises(CardError, match="TAU_NET_ALLOW_INSECURE=1"):
        PeerClient(refuse).fetch_card("127.0.0.1:8822")
    with pytest.raises(CardError) as info:
        PeerClient(refuse, allow_insecure=True).fetch_card("127.0.0.1:8822")
    assert "TAU_NET_ALLOW_INSECURE" not in str(info.value)
