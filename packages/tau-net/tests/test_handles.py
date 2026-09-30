"""Handle addresses (ADR 0013 §3, issue 155): ``host[:port]/@handle`` next to ``host[:port]``.

A hosted tau lives under a path of its host (``tau.example.com/@alice``). Its card and inbox
are under that path, a sub-tau of it is ``tau.example.com/@alice/coach``, and everything a hub
does with a plain address works with the longer one: contacts, card fetches, sending, the CLI.
The fake network routes ``/@handle`` paths to a fake spine with a handle address, which stands
in for tau-host here."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from net_helpers import BOB, Tau, connect, make_tau, poll
from tau_net.cli import net
from tau_net.config import NetConfigError, NetSettings
from tau_net.encoding import (
    ADDRESS_PATTERN,
    AddressError,
    base_url,
    handle_of,
    host_of,
    is_valid_address,
    is_valid_handle,
    is_valid_host,
    parse_address,
    parse_host,
    parse_target,
    split_address,
)
from tau_net.envelope import Envelope, open_box, open_verified, parse_content, peek_sender
from tau_net.peers import PeerClient
from tau_net.spine_kit import SpineKitError, spine_host
from tau_net.testing import FakeNetwork, FakeSpine, FakeUniverse, route_key
from tau_net.universe import UniverseClient

ALICE_HOSTED = "tau.example.com/@alice"
"""A hosted tau: the tau-host at tau.example.com serves it under /@alice."""


# -- the grammar -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "tau.example.com/@alice",
        "tau.example.com/@a",
        "tau.example.com/@alice-bob",
        "tau.example.com/@0day",
        "tau.example.com/@" + "a" * 39,
        "127.0.0.1:8787/@alice",
        "localhost/@x1",
    ],
)
def test_handle_addresses_are_addresses(address: str) -> None:
    assert is_valid_address(address)
    assert not is_valid_host(address)
    assert ADDRESS_PATTERN.fullmatch(address)


@pytest.mark.parametrize(
    "address",
    [
        "tau.example.com/@",
        "tau.example.com/@Alice",
        "tau.example.com/@-alice",
        "tau.example.com/@alice-",
        "tau.example.com/@" + "a" * 40,
        "tau.example.com/@alice/coach",
        "tau.example.com/@alice/",
        "tau.example.com/alice",
        "tau.example.com//@alice",
        "tau.example.com/@al_ice",
        "tau.example.com/@alice\n",
        "/@alice",
        "@alice",
    ],
)
def test_bad_handle_addresses(address: str) -> None:
    assert not is_valid_address(address)


def test_handles_follow_the_github_login_rules_in_lower_case() -> None:
    assert is_valid_handle("alice") and is_valid_handle("a") and is_valid_handle("a-b-c")
    assert is_valid_handle("a" * 39) and not is_valid_handle("a" * 40)
    for bad in ("", "-a", "a-", "A", "a_b", "a.b", "@a", None, 7):
        assert not is_valid_handle(bad)


def test_split_host_and_handle() -> None:
    assert split_address("tau.example.com/@alice") == ("tau.example.com", "alice")
    assert split_address("127.0.0.1:8787/@alice") == ("127.0.0.1:8787", "alice")
    assert split_address("tau.example.com") == ("tau.example.com", None)
    assert handle_of("tau.example.com/@alice") == "alice" and handle_of("bob.example") is None
    assert host_of("127.0.0.1:8787/@alice") == "127.0.0.1"
    assert host_of("tau.example.com/@alice") == "tau.example.com"
    with pytest.raises(AddressError):
        split_address("tau.example.com/@Alice")


def test_card_and_inbox_urls_extend_the_address() -> None:
    assert base_url(ALICE_HOSTED) == "https://tau.example.com/@alice"
    assert base_url("127.0.0.1:8787/@alice", allow_insecure=True) == "http://127.0.0.1:8787/@alice"
    assert base_url("10.0.0.1/@alice", allow_insecure=True) == "https://10.0.0.1/@alice"


def test_people_may_type_handles_loosely() -> None:
    assert parse_address(" https://Tau.Example.com/@Alice/ ") == ALICE_HOSTED
    with pytest.raises(AddressError):
        parse_address("tau.example.com/@alice/coach")
    assert parse_host("HTTPS://Tau.Example.com/") == "tau.example.com"
    with pytest.raises(AddressError):
        parse_host(ALICE_HOSTED)


def test_targets_with_handles_read_one_way_only() -> None:
    assert parse_target(ALICE_HOSTED) == (ALICE_HOSTED, None)
    assert parse_target("tau.example.com/@alice/coach") == (ALICE_HOSTED, "coach")
    assert parse_target("https://Tau.Example.com/@Alice/Coach/") == (ALICE_HOSTED, "coach")
    assert parse_target("127.0.0.1:8787/@alice/coach") == ("127.0.0.1:8787/@alice", "coach")
    assert parse_target("tau.example.com/coach") == ("tau.example.com", "coach")
    for bad in (
        "tau.example.com/@",
        "tau.example.com/@alice/coach/x",
        "tau.example.com/@a/b/c",
        "tau.example.com/coach/@alice",
        "tau.example.com/@alice/@bob",
        "tau.example.com/@alice/Co ach",
        "tau.example.com/@al ice",
    ):
        with pytest.raises(AddressError):
            parse_target(bad)


def test_the_universe_and_a_spine_are_plain_hosts() -> None:
    with pytest.raises(AddressError):
        UniverseClient(ALICE_HOSTED)
    with pytest.raises(NetConfigError):
        NetSettings.from_mapping({"universe": ALICE_HOSTED})
    assert NetSettings.from_mapping({"universe": "Tau.Example.com"}).universe == "tau.example.com"
    with pytest.raises(SpineKitError):
        spine_host(ALICE_HOSTED)
    with pytest.raises(ValueError):
        FakeUniverse(ALICE_HOSTED)


# -- the fake network ----------------------------------------------------------------------------


def test_the_fake_network_routes_handle_paths(network: FakeNetwork) -> None:
    host = network.add(FakeSpine("tau.example.com"))
    alice = network.add(FakeSpine(ALICE_HOSTED))
    alice.publish("Alice's tau", "A" * 43, "B" * 43)
    assert route_key("https://tau.example.com/@alice/net/inbox") == (ALICE_HOSTED, "/net/inbox")
    assert route_key("https://tau.example.com/net/inbox") == ("tau.example.com", "/net/inbox")
    status, _, body = network(
        "GET", "https://tau.example.com/@alice/.well-known/tau.json", {}, None, 5
    )
    card = json.loads(body)
    assert status == 200 and card["address"] == ALICE_HOSTED
    assert card["inbox"] == "https://tau.example.com/@alice/net/inbox"
    # the host itself has no card yet; another handle on it has no fake at all
    assert network("GET", "https://tau.example.com/.well-known/tau.json", {}, None, 5)[0] == 404
    assert network("GET", "https://tau.example.com/@bob/.well-known/tau.json", {}, None, 5)[0] == (
        404
    )
    assert host.requests[-1] == ("GET", "/@bob/.well-known/tau.json")


# -- a hub and a hosted tau ----------------------------------------------------------------------


def hosted(tmp_path: Path, network: FakeNetwork, **kwargs) -> Tau:
    """Alice's tau on a tau-host, under /@alice (a fake spine with a handle address)."""
    return make_tau(tmp_path, network, ALICE_HOSTED, name="Alice's tau", **kwargs)


def test_contacts_and_messages_with_a_hosted_tau(tmp_path: Path, network: FakeNetwork) -> None:
    alice = hosted(tmp_path, network, replies=["Hi Bob, Alice's tau here."])
    bob = make_tau(tmp_path, network, BOB)
    bob_node, alice_node = connect(bob, alice)
    assert bob_node.contacts.get(ALICE_HOSTED).state == "accepted"
    assert alice_node.contacts.get(BOB).state == "accepted"
    # the card was fetched at the longer URL
    urls = [url for _, url in network.requests]
    assert "https://tau.example.com/@alice/.well-known/tau.json" in urls
    assert "https://tau.example.com/@alice/net/inbox" in urls

    delivery = bob_node.send(ALICE_HOSTED, "Hello Alice's tau.")
    assert delivery.status == "queued" and delivery.address == ALICE_HOSTED
    handled = poll(alice_node)
    assert [h.outcome for h in handled] == ["handled"] and handled[0].replied
    [mail] = bob.spine.pending()
    payload = open_verified(Envelope.from_json(mail["envelope"]), alice.identity.sign_key)
    assert payload.sender == ALICE_HOSTED and payload.recipient == BOB
    assert peek_sender(Envelope.from_json(mail["envelope"])) == ALICE_HOSTED
    content = parse_content("message", open_box(payload.box, bob.identity, payload.aad))
    assert content == {"text": "Hi Bob, Alice's tau here."}
    poll(bob_node)  # Bob's tau answers the reply (hop 2)
    assert {e["address"] for e in bob_node.store.log()} == {ALICE_HOSTED}
    assert bob_node.store.counts()[ALICE_HOSTED] == {"in": 1, "out": 2}


def test_a_sub_tau_of_a_hosted_tau(tmp_path: Path, network: FakeNetwork) -> None:
    alice = hosted(tmp_path, network)
    bob = make_tau(tmp_path, network, BOB)
    bob_node, _ = connect(bob, alice)
    bob_node.send("tau.example.com/@alice/coach", "Plan my week, please.")
    [mail] = alice.spine.pending()
    payload = open_verified(Envelope.from_json(mail["envelope"]), bob.identity.sign_key)
    assert payload.recipient == ALICE_HOSTED
    content = parse_content("message", open_box(payload.box, alice.identity, payload.aad))
    assert content == {"text": "Plan my week, please.", "sub": "coach"}
    [entry] = [e for e in bob_node.store.log() if e["kind"] == "message"]
    assert entry["address"] == ALICE_HOSTED and entry["peer_sub"] == "coach"


def test_a_stranger_with_a_handle_address_is_dropped_without_a_card_fetch(
    tmp_path: Path, network: FakeNetwork
) -> None:
    alice = hosted(tmp_path, network)
    bob = make_tau(tmp_path, network, BOB)
    bob_node = bob.node()
    bob_node.publish_card()
    alice.node().publish_card()
    from net_helpers import send_raw

    send_raw(alice, bob, "hello")
    network.requests.clear()
    [handled] = poll(bob_node)
    assert handled.outcome == "dropped" and handled.reason == "not a contact"
    assert handled.sender == ALICE_HOSTED
    assert not any("/.well-known/" in url for _, url in network.requests)


def test_the_cli_adds_and_writes_to_handle_addresses(tmp_path: Path, network: FakeNetwork) -> None:
    alice = hosted(tmp_path, network, replies=["Sure."])
    bob = make_tau(tmp_path, network, BOB)
    alice.node().publish_card()
    bob.node().publish_card()
    obj = {"home": bob.config.home, "net_env": bob.env, "net_transport": network}
    env = {"TAU_DATA_DIR": str(bob.config.data_dir), "TAU_LANG": "en"}
    runner = CliRunner()

    result = runner.invoke(net, ["add", "https://Tau.Example.com/@Alice/"], obj=obj, env=env)
    assert result.exit_code == 0, result.output
    assert ALICE_HOSTED in result.output
    alice_node = alice.node()
    poll(alice_node)
    alice_node.accept(BOB)
    poll(bob.node())

    result = runner.invoke(
        net, ["send", "tau.example.com/@alice/coach", "Hello", "coach."], obj=obj, env=env
    )
    assert result.exit_code == 0, result.output
    assert "tau.example.com/@alice/coach" in result.output
    result = runner.invoke(net, ["send", ALICE_HOSTED, "Hello", "Alice."], obj=obj, env=env)
    assert result.exit_code == 0, result.output

    result = runner.invoke(net, ["contacts"], obj=obj, env=env)
    assert ALICE_HOSTED in result.output
    result = runner.invoke(net, ["log", "--address", ALICE_HOSTED], obj=obj, env=env)
    assert "tau.example.com/@alice/coach" in result.output

    result = runner.invoke(net, ["send", "tau.example.com/@a/b/c", "x"], obj=obj, env=env)
    assert result.exit_code == 1 and "tau net:" in result.output


def test_peers_refuse_what_is_not_an_address(network: FakeNetwork) -> None:
    peers = PeerClient(network)
    for bad in ("tau.example.com/@Alice", "tau.example.com/@alice/coach", "tau.example.com/x"):
        with pytest.raises(AddressError):
            peers.fetch_card(bad)
