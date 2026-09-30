"""Shared helpers: taus with a fake spine each, on one fake network. No sockets, no keys on
disk outside ``tmp_path``, no model credentials (FakeModel).

Imported as ``net_helpers`` (``conftest.py`` puts this directory on ``sys.path``; the name
differs from tau-tui's ``helpers`` so the two never shadow each other)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau_core import Config
from tau_core.testing import FakeModel, test_config
from tau_net.envelope import Payload, build_envelope
from tau_net.identity import Identity, create_identity, identity_path
from tau_net.node import NetNode, open_node
from tau_net.peers import PeerClient
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeNetwork, FakeSpine

ALICE = "alice.example"
BOB = "bob.example"
USER_SECRET = "PRIVATE-USER-FACT: the owner's door code is 4711."
"""Written into every test tau's persona/user.md; a network turn must never show it."""


@dataclass
class Tau:
    address: str
    config: Config
    env: dict[str, str]
    spine: FakeSpine
    network: FakeNetwork
    identity: Identity
    model: FakeModel

    def node(self, **kwargs: Any) -> NetNode:
        return open_node(
            self.config,
            env=self.env,
            transport=self.network,
            model_factory=lambda: self.model,
            **kwargs,
        )

    @property
    def net_dir(self) -> Path:
        return self.config.data_dir / "net"


def make_tau(
    root: Path,
    network: FakeNetwork,
    address: str,
    *,
    name: str | None = None,
    replies: Sequence[Any] = (),
    default: str = "Okay.",
    component: dict[str, Any] | None = None,
    public_note: str | None = "- Public: the owner likes short meetings on weekday mornings.",
    mode: str = "local",
    max_wait: float | None = 0.3,
    with_identity: bool = True,
) -> Tau:
    config = test_config(root / address)
    persona = config.persona_dir
    (persona / "user.md").write_text(USER_SECRET + "\n", encoding="utf-8")
    if public_note is not None:
        (persona / "net.md").write_text(
            "<!-- the owner's public note -->\n" + public_note + "\n", encoding="utf-8"
        )
    settings = {"name": name or f"{address.split('.')[0].title()}'s tau", **(component or {})}
    with (config.home / "tau.toml").open("a", encoding="utf-8") as handle:
        handle.write("\n[component.net]\n")
        for key, value in settings.items():
            handle.write(f"{key} = {json.dumps(value)}\n")
    config = Config.load(config.home, env={"TAU_DATA_DIR": str(config.data_dir)})
    spine = network.add(FakeSpine(address, mode=mode, max_wait=max_wait))
    identity = create_identity(identity_path(config.data_dir)) if with_identity else None
    env = {"TAU_SPINE_URL": f"https://{address}", "TAU_SPINE_TOKEN": DEFAULT_HUB_TOKEN}
    model = FakeModel(list(replies), default=default)
    return Tau(address, config, env, spine, network, identity, model)  # type: ignore[arg-type]


def send_raw(
    sender: Tau,
    recipient: Tau,
    text: str,
    *,
    hops: int = 0,
    kind: str = "message",
    content: dict[str, str] | None = None,
    **kw: Any,
) -> Payload:
    """Deliver an envelope built by hand (any ``hops``, ``thread``, ``reply_to``)."""
    envelope, payload = build_envelope(
        sender.identity,
        sender=sender.address,
        recipient=recipient.address,
        recipient_box_key=recipient.identity.box_key,
        kind=kind,
        content=content if content is not None else {"text": text},
        hops=hops,
        **kw,
    )
    PeerClient(sender.network).deliver(recipient.address, envelope)
    return payload


def poll(node: NetNode) -> list:
    return asyncio.run(node.poll_once())


@dataclass
class Pair:
    a: Tau
    b: Tau
    a_node: NetNode
    b_node: NetNode
    network: FakeNetwork


def connect(a: Tau, b: Tau) -> tuple[NetNode, NetNode]:
    """Publish both cards, A adds B, B accepts, A sees the accept: an accepted pair."""
    a_node, b_node = a.node(), b.node()
    a_node.publish_card()
    b_node.publish_card()
    a_node.add(b.address, note="Hello from Alice's tau.")
    poll(b_node)
    b_node.accept(a.address)
    poll(a_node)
    return a_node, b_node
