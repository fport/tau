"""The owner's network profile (runtime data, never ``tau.toml``) and the ``counts`` document
of message envelopes a universe report sums up (docs/reference/tau-universe.md §3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from net_helpers import ALICE, BOB, connect, make_tau, poll, send_raw
from tau_core import Config
from tau_net.config import NetConfigError
from tau_net.node import open_node
from tau_net.profile import NetProfile, check_profile_changes
from tau_net.testing import FakeNetwork

CAROL = "carol.example"


# -- the owner's profile ---------------------------------------------------------------------


def test_profile_changes_are_checked() -> None:
    assert check_profile_changes({"name": "  Alice's\n tau ", "universe_owner": ""}) == {
        "name": "Alice's tau",
        "universe_owner": "",
    }
    for bad in (
        {"name": ""},
        {"name": "x" * 81},
        {"universe_owner": "x" * 61},
        {"universe_about": "x" * 201},
        {"universe_join": "yes"},
        {"universe_links": "no"},
        {"secret": 1},
    ):
        with pytest.raises(NetConfigError):
            check_profile_changes(bad)
    lenient = NetProfile.from_json({"name": 3, "universe_join": "yes", "universe_links": 1})
    assert lenient == NetProfile()


def test_card_name_precedence(tmp_path: Path, network: FakeNetwork) -> None:
    tau = make_tau(tmp_path, network, ALICE, name="Alice's tau")
    node = tau.node()
    assert node.display_name() == "Alice's tau"  # [component.net] name, the fallback
    node.update_profile(name="Alice's other tau")
    assert node.display_name() == "Alice's other tau"  # the profile wins
    assert node.publish_card()["name"] == "Alice's other tau"
    bare = make_tau(tmp_path / "bare", network, CAROL)
    toml = bare.config.home / "tau.toml"
    toml.write_text(toml.read_text().replace('name = "Carol\'s tau"\n', ""))
    config = Config.load(bare.config.home, env={"TAU_DATA_DIR": str(bare.config.data_dir)})
    assert "name" not in config.component("net")
    assert open_node(config, env=bare.env, transport=network).display_name() == "tau"


# -- message counts ----------------------------------------------------------------------------


@pytest.mark.parametrize("store", ["file", "spine"])
def test_counts_follow_handled_and_sent_messages(
    tmp_path: Path, network: FakeNetwork, store: str
) -> None:
    mode = "cloud" if store == "spine" else "local"
    a = make_tau(tmp_path, network, ALICE, replies=["[no reply]"])
    b = make_tau(tmp_path, network, BOB, mode=mode, component={"store": store}, default="Sure.")
    a_node, b_node = connect(a, b)
    assert a_node.store.counts() == {} and b_node.store.counts() == {}  # requests do not count

    a_node.send(BOB, "Lunch on Friday?")  # the owner's send
    assert a_node.store.counts() == {BOB: {"in": 0, "out": 1}}
    poll(b_node)  # handled from a contact, and the network turn's auto-reply
    assert b_node.store.counts() == {ALICE: {"in": 1, "out": 1}}
    poll(a_node)  # A's turn answers [no reply]: nothing sent
    assert a_node.store.counts() == {BOB: {"in": 1, "out": 1}}

    if store == "spine":
        assert b.spine.state["net.counts"]["value"] == {ALICE: {"in": 1, "out": 1}}
        assert not (b.net_dir / "counts.json").exists()
    else:
        assert json.loads((b.net_dir / "counts.json").read_text()) == {ALICE: {"in": 1, "out": 1}}


def test_counts_are_not_doubled_by_an_envelope_handled_again(tmp_path: Path, network) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB, component={"auto_reply": False})
    a_node, b_node = connect(a, b)
    a_node.send(BOB, "hi")
    [mail] = b.spine.pending()
    first = asyncio.run(b_node.handle(mail["envelope"]))
    b_node.store.backend.write("seen", [])  # a crash before the id was marked as seen
    second = asyncio.run(b_node.handle(mail["envelope"]))
    assert first.outcome == second.outcome == "handled"
    assert b_node.store.counts() == {ALICE: {"in": 1, "out": 0}}


def test_messages_from_strangers_and_pending_contacts_are_not_counted(
    tmp_path: Path, network
) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB)
    a_node, b_node = a.node(), b.node()
    a_node.publish_card()
    b_node.publish_card()
    a_node.add(BOB)
    poll(b_node)  # a pending request
    send_raw(a, b, "a message before the accept")
    poll(b_node)
    assert b_node.store.counts() == {}
