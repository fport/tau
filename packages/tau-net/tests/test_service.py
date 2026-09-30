"""The ``net`` hub service (§6.1) and two taus end to end over the fake network."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from net_helpers import ALICE, BOB, Pair, Tau, connect, make_tau, poll
from tau_core.hub.daemon import Hub
from tau_net import tools
from tau_net.envelope import Envelope, open_box, open_verified, parse_content
from tau_net.service import NetService, doctor_check
from tau_net.testing import FakeNetwork


class Run:
    def __init__(self, service: NetService, hub: Hub, sleeps: list[float]):
        self.service, self.hub, self.sleeps = service, hub, sleeps

    async def until(self, condition: Callable[[], bool], timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out; status={self.service.status()}")
            await asyncio.sleep(0.01)


def serve(
    tau: Tau,
    body: Callable[[Run], Awaitable[None]],
    *,
    env: dict[str, str] | None = None,
) -> Run:
    sleeps: list[float] = []

    async def fast_sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0.001)

    service = NetService(
        tau.config,
        env=tau.env if env is None else env,
        transport=tau.network,
        model_factory=lambda: tau.model,
        sleep=fast_sleep,
    )
    hub = Hub(tau.config)
    run = Run(service, hub, sleeps)

    async def main() -> None:
        await service.start(hub)
        try:
            await body(run)
        finally:
            await service.stop()

    asyncio.run(main())
    return run


async def nothing(run: Run) -> None:
    return None


# -- idle --------------------------------------------------------------------------------------


def test_idle_without_spine_variables(tmp_path: Path, network: FakeNetwork) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    run = serve(tau, nothing, env={})
    assert run.service.status() == {"configured": False, "reason": "TAU_SPINE_URL is not set"}
    assert run.hub.status()["net"]["configured"] is False
    assert network.requests == []
    run = serve(tau, nothing, env={"TAU_SPINE_URL": "https://alice.example"})
    assert run.service.status()["reason"] == "TAU_SPINE_TOKEN is not set"


def test_idle_without_identity_or_with_a_plain_http_spine(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE, with_identity=False)
    run = serve(tau, nothing)
    assert run.service.status() == {
        "configured": False,
        "reason": "no identity (run `tau net init`)",
    }
    run = serve(tau, nothing, env={**tau.env, "TAU_SPINE_URL": "http://alice.example"})
    assert "https" in run.service.status()["reason"]


# -- start, card, polling ----------------------------------------------------------------------


def test_card_is_published_on_start_and_status_is_reported(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE, name="Alice's tau")

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.state == "polling")

    run = serve(tau, body)
    assert tau.spine.card["name"] == "Alice's tau"
    assert tau.spine.card["sign_key"] == tau.identity.sign_key
    status = run.hub.status()["net"]
    assert status["configured"] is True and status["address"] == ALICE
    assert status["card_published"] is True and status["contacts"] == 0
    assert "token" not in str(status).lower() or "test-hub-token" not in str(status)
    puts = [r for r in tau.spine.requests if r == ("PUT", "/hub/card")]
    assert len(puts) == 1
    serve(tau, body)  # the same card: not published again
    assert len([r for r in tau.spine.requests if r == ("PUT", "/hub/card")]) == 1


def test_handle_then_ack_then_cursor(pair_factory) -> None:
    pair: Pair = pair_factory(replies=["Friday works."])
    pair.a_node.send(BOB, "When is Bob free?")
    network = pair.network
    before = len(network.requests)

    async def body(run: Run) -> None:
        await run.until(lambda: pair.b.spine.pending() == [])

    serve(pair.b, body)
    requests = [(m, u) for m, u in network.requests[before:]]
    reply_at = requests.index(("POST", "https://alice.example/net/inbox"))
    ack_at = requests.index(("POST", "https://bob.example/hub/ack"))
    assert reply_at < ack_at  # handled (and answered) before it was acknowledged
    seq = pair.b.spine.acked[-1]
    assert pair.b_node.store.cursor() == seq
    assert (pair.b.net_dir / "cursor").read_text() == f"{seq}\n"


def test_network_errors_back_off_up_to_a_minute(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    network.down.add(ALICE)

    async def body(run: Run) -> None:
        await run.until(lambda: len(run.sleeps) >= 8)
        assert run.service.status()["state"] == "retrying"
        network.down.clear()
        await run.until(lambda: run.service.state == "polling")

    run = serve(tau, body)
    assert run.sleeps[:8] == [1, 2, 4, 8, 16, 32, 60, 60]
    assert run.service.status()["last_error"] is None


def test_poll_errors_back_off_and_recover(pair_factory) -> None:
    pair: Pair = pair_factory()
    spine = pair.b.spine

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.state == "polling")
        spine.fail("GET", "/hub/updates", (500, {"error": "boom"}), (500, {"error": "boom"}))
        await run.until(lambda: len(run.sleeps) >= 2)
        await run.until(lambda: run.service.state == "polling")

    run = serve(pair.b, body)
    assert run.sleeps[:2] == [1, 2]


def test_a_rejected_token_stops_polling(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    env = {**tau.env, "TAU_SPINE_TOKEN": "wrong-token"}

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.state == "failed")

    run = serve(tau, body, env=env)
    status = run.service.status()
    assert "unauthorized" in status["last_error"] and "wrong-token" not in str(status)


def test_stop_returns_promptly_during_a_long_poll(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE, max_wait=None)  # waits the full 25 s

    async def body(run: Run) -> None:
        await run.until(lambda: ("GET", "/hub/updates") in tau.spine.requests)
        await asyncio.sleep(0.05)

    started = time.monotonic()
    serve(tau, body)
    assert time.monotonic() - started < 5


def test_the_service_shares_its_node_with_the_tools(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.state == "polling")
        assert tools.current_node() is run.service.node

    serve(tau, body)
    assert tools._active_node is None


def test_doctor_check(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    assert doctor_check(tau.config, {}, None).status == "info"
    assert doctor_check(tau.config, tau.env, None).status == "ok"
    polling = {"net": {"state": "polling", "address": ALICE}}
    check = doctor_check(tau.config, tau.env, polling)
    assert (check.status, check.detail) == ("ok", f"polling as {ALICE}")
    failed = {"net": {"state": "failed", "last_error": "spine answered 401 unauthorized"}}
    assert doctor_check(tau.config, tau.env, failed).status == "fail"
    assert doctor_check(tau.config, tau.env, {"pid": 1}).status == "warn"
    bare = make_tau(tmp_path / "x", network, "carol.example", with_identity=False)
    assert "tau net init" in doctor_check(bare.config, bare.env, None).detail


# -- two taus, end to end ----------------------------------------------------------------------


def test_two_taus_end_to_end(tmp_path: Path, network: FakeNetwork, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB, replies=["Bob is free on Friday afternoon."])
    a_node, b_node = connect(a, b)  # A adds B, B accepts, A sees the accept
    assert a_node.contacts.get(BOB).state == "accepted"
    assert b_node.contacts.get(ALICE).state == "accepted"

    sent = a_node.send(BOB, "When is Bob free this week?")
    assert sent.status == "queued"
    question = a_node.store.log(address=BOB)[-1]

    async def body(run: Run) -> None:  # B's hub answers with its FakeModel
        await run.until(lambda: len(a.spine.pending()) == 1)

    serve(b, body)
    [mail] = a.spine.pending()
    reply = open_verified(Envelope.from_json(mail["envelope"]), b.identity.sign_key)
    assert (reply.thread, reply.reply_to, reply.hops) == (question["id"], question["id"], 1)
    assert parse_content("message", open_box(reply.box, a.identity, reply.aad)) == {
        "text": "Bob is free on Friday afternoon."
    }

    poll(a_node)  # A receives the reply: its log has it
    log = a_node.store.log(address=BOB)
    received = [e for e in log if e["direction"] == "in" and e["kind"] == "message"]
    assert [e["text"] for e in received] == ["Bob is free on Friday afternoon."]
    assert received[0]["thread"] == question["id"]
    # auto_reply is on for A too: its own network turn answered in the same thread (hops 2)
    assert len(a.model.calls) == 1
    assert log[-1]["direction"] == "out" and log[-1]["thread"] == question["id"]
    [answer] = b.spine.pending()
    assert open_verified(Envelope.from_json(answer["envelope"]), a.identity.sign_key).hops == 2
    assert "test-hub-token" not in caplog.text
    assert a.identity.to_json()["sign_seed"] not in caplog.text


@pytest.mark.parametrize("store", ["spine"])
def test_cloud_mode_keeps_the_network_state_in_the_spine(
    tmp_path: Path, network: FakeNetwork, store: str
) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB, mode="cloud", component={"store": store})
    a_node, b_node = connect(a, b)
    assert b_node.store.kind == "spine"
    assert b.spine.state["net.contacts"]["value"][ALICE]["state"] == "accepted"
    assert not (b.net_dir / "contacts.json").exists()
    a_node.send(BOB, "hi")
    poll(b_node)
    assert b.spine.state["net.log"]["value"][-1]["direction"] == "out"
    assert b.spine.state["net.sessions"]["value"][ALICE]
    assert isinstance(b.spine.state["net.cursor"]["value"], int)
