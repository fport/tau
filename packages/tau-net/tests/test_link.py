"""How the ``net`` service waits for mail (``[component.net] link``): the doorbell, its safety
fetch, reconnects, the fallback to the long poll and back, with a :class:`FakeDoorbell`."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from net_helpers import ALICE, BOB, Pair, Tau, make_tau
from tau_core.hub.daemon import Hub
from tau_net.config import NetConfigError, NetSettings
from tau_net.doorbell import DoorbellError, DoorbellUnauthorized, DoorbellUnsupported
from tau_net.service import (
    DOORBELL_RETRY_SECONDS,
    DOORBELL_STABLE_SECONDS,
    SAFETY_FETCH_SECONDS,
    NetService,
    doctor_check,
)
from tau_net.testing import FakeDoorbell, FakeNetwork


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


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
    doorbell: FakeDoorbell | None,
    monotonic: Callable[[], float] = time.monotonic,
) -> Run:
    sleeps: list[float] = []

    async def fast_sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0.001)

    service = NetService(
        tau.config,
        env=tau.env,
        transport=tau.network,
        model_factory=lambda: tau.model,
        sleep=fast_sleep,
        doorbell=(lambda: doorbell) if doorbell is not None else None,
        monotonic=monotonic,
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


def messages_in(tau: Tau, pair: Pair) -> int:
    """How many messages the tau's hub has handled (its network log)."""
    node = pair.b_node if tau is pair.b else pair.a_node
    return sum(1 for e in node.store.log() if e["direction"] == "in" and e["kind"] == "message")


def updates(tau: Tau, network: FakeNetwork, since: int = 0) -> list[str]:
    """The URLs of the tau's ``GET /hub/updates`` requests, in order, from request
    ``since`` on."""
    return [
        url
        for method, url in network.requests[since:]
        if method == "GET" and url.startswith(f"https://{tau.address}/hub/updates")
    ]


# -- the setting ---------------------------------------------------------------------------------


def test_the_link_setting() -> None:
    assert NetSettings.from_mapping({}).link == "auto"
    for link in ("auto", "websocket", "poll"):
        assert NetSettings.from_mapping({"link": link}).link == link
    for bad in ("ws", "", 1, None):
        with pytest.raises(NetConfigError, match="link"):
            NetSettings.from_mapping({"link": bad})


def test_the_real_service_uses_the_spines_websocket_doorbell(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    service = NetService(tau.config, env=tau.env)  # no transport: the real network
    service.node = service._open()
    assert service.node is not None and service.node.spine is not None
    assert service._doorbell_factory == service.node.spine.doorbell
    faked = NetService(tau.config, env=tau.env, transport=network)
    faked.node = faked._open()
    assert faked._doorbell_factory is None  # a fake network has no sockets: long poll


# -- on the doorbell -----------------------------------------------------------------------------


def test_a_ring_fetches_at_once_without_a_long_poll(pair_factory) -> None:
    pair: Pair = pair_factory(replies=["Friday works."])
    bell = pair.b.spine.doorbell()
    before = len(pair.network.requests)

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket" and run.service.last_poll_at)
        pair.a_node.send(BOB, "When is Bob free?")  # Bob's spine rings the doorbell
        await run.until(lambda: messages_in(pair.b, pair) == 1)
        status = run.hub.status()["net"]
        assert status["link"] == "websocket" and status["state"] == "polling"
        assert status["doorbell"]["setting"] == "auto"
        assert status["doorbell"]["connects"] == 1 and status["doorbell"]["reconnects"] == 0
        assert status["doorbell"]["rings"] >= 2  # the hello, then the mail
        assert status["doorbell"]["last_ring_at"] and status["doorbell"]["fallbacks"] == 0
        assert status["doorbell"]["retry_at"] is None

    serve(pair.b, body, doorbell=bell)
    urls = updates(pair.b, pair.network, since=before)
    assert urls and all("timeout=0" in url for url in urls)  # never a long poll
    assert bell.waits and all(wait == SAFETY_FETCH_SECONDS for wait in bell.waits)


def test_the_hello_fetches_mail_that_arrived_while_away(pair_factory) -> None:
    pair: Pair = pair_factory(replies=["Hi."])
    pair.a_node.send(BOB, "Are you there?")  # queued before Bob's hub starts
    bell = pair.b.spine.doorbell()

    async def body(run: Run) -> None:
        await run.until(lambda: messages_in(pair.b, pair) == 1)

    serve(pair.b, body, doorbell=bell)
    assert bell.connects == 1


def test_the_safety_fetch_runs_while_the_doorbell_stays_quiet(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell(max_wait=0.01)  # every wait "times out" at once

    async def body(run: Run) -> None:
        await run.until(lambda: len(updates(tau, network)) >= 5)

    run = serve(tau, body, doorbell=bell)
    assert run.service.doorbell_rings == 1  # only the hello rang
    assert all("timeout=0" in url for url in updates(tau, network))
    assert set(bell.waits) == {SAFETY_FETCH_SECONDS}


def test_a_full_batch_is_fetched_again_at_once(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    for _ in range(60):
        tau.spine.enqueue({"payload": "AAAA", "sig": "AAAA"})  # dropped by the hub, then acked
    bell = FakeDoorbell()

    async def body(run: Run) -> None:
        await run.until(lambda: tau.spine.pending() == [])

    run = serve(tau, body, doorbell=bell)
    assert len(tau.spine.acked) == 60
    assert run.service.doorbell_rings == 1  # one hello, two fetches


def test_a_dropped_doorbell_reconnects_and_fetches(pair_factory) -> None:
    pair: Pair = pair_factory(replies=["Hi."])
    bell = pair.b.spine.doorbell()
    clock = Clock()

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket" and run.service.last_poll_at)
        clock.now += DOORBELL_STABLE_SECONDS  # a long-lived connection
        bell.drop()
        await run.until(lambda: bell.connects == 2)
        pair.a_node.send(BOB, "Still there?")
        await run.until(lambda: messages_in(pair.b, pair) == 1)

    run = serve(pair.b, body, doorbell=bell, monotonic=clock)
    status = run.service.status()
    assert status["doorbell"]["reconnects"] == 1 and status["doorbell"]["fallbacks"] == 0
    assert status["link"] == "websocket"
    assert "dropped" in status["doorbell"]["last_error"]
    assert run.sleeps == []  # a stable connection reconnects without backing off


def test_a_flapping_doorbell_backs_off(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell()

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket")
        bell.drop()
        await run.until(lambda: bell.connects == 2)
        bell.drop()
        await run.until(lambda: bell.connects == 3)

    run = serve(tau, body, doorbell=bell)
    assert run.sleeps[:2] == [1, 2]
    assert run.service.doorbell_fallbacks == 0


# -- falling back and coming back ----------------------------------------------------------------


def test_a_spine_without_a_doorbell_is_long_polled_then_tried_again(tmp_path: Path, network):
    tau = make_tau(tmp_path, network, ALICE, max_wait=0.05)
    bell = FakeDoorbell()
    bell.refuse(DoorbellUnsupported("the spine answered 426 upgrade_required", 426))
    clock = Clock()

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "poll" and run.service.last_poll_at)
        status = run.service.status()
        assert status["doorbell"]["fallbacks"] == 1 and status["doorbell"]["retry_at"]
        assert "426" in status["doorbell"]["last_error"]
        assert any("timeout=25" in url for url in updates(tau, network))
        clock.now += DOORBELL_RETRY_SECONDS  # half an hour later
        await run.until(lambda: run.service.link == "websocket")
        assert run.service.status()["doorbell"]["retry_at"] is None

    run = serve(tau, body, doorbell=bell, monotonic=clock)
    assert bell.connects == 1
    assert run.sleeps == []  # a 426 falls back at once, without backing off


def test_repeated_failures_fall_back_to_the_long_poll(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell()
    bell.refuse(*(DoorbellError(f"cannot connect ({i})") for i in range(3)))

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "poll" and run.service.last_poll_at)

    run = serve(tau, body, doorbell=bell, monotonic=Clock())
    assert run.sleeps[:2] == [1, 2]
    assert run.service.doorbell_fallbacks == 1 and bell.connects == 0


def test_link_websocket_never_falls_back(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE, component={"link": "websocket"})
    bell = FakeDoorbell()
    bell.refuse(
        DoorbellUnsupported("the spine answered 404 not_found", 404),
        *(DoorbellError("cannot connect") for _ in range(4)),
    )

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket")

    run = serve(tau, body, doorbell=bell)
    assert run.sleeps[:5] == [1, 2, 4, 8, 16]
    assert run.service.doorbell_fallbacks == 0
    assert not any("timeout=25" in url for url in updates(tau, network))


def test_link_poll_never_rings(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE, component={"link": "poll"})
    bell = FakeDoorbell()

    async def body(run: Run) -> None:
        await run.until(lambda: len(updates(tau, network)) >= 2)

    run = serve(tau, body, doorbell=bell)
    assert bell.connects == 0 and run.service.link == "poll"
    assert all("timeout=25" in url for url in updates(tau, network))
    assert run.service.status()["doorbell"]["setting"] == "poll"


def test_a_rejected_token_on_the_doorbell_stops(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell()
    bell.refuse(DoorbellUnauthorized("the spine answered 401 unauthorized", 401))

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.state == "failed")

    run = serve(tau, body, doorbell=bell)
    assert "401" in run.service.status()["last_error"]


def test_a_rejected_token_on_a_fetch_stops(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell()

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket")
        tau.spine.hub_token = "rotated"
        bell.ring()
        await run.until(lambda: run.service.state == "failed")

    run = serve(tau, body, doorbell=bell)
    assert "unauthorized" in run.service.status()["last_error"]


def test_fetch_errors_back_off_on_the_doorbell(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell()

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket" and run.service.last_poll_at)
        tau.spine.fail("GET", "/hub/updates", (500, {"error": "boom"}), (500, {"error": "boom"}))
        bell.ring()
        await run.until(lambda: len(run.sleeps) >= 2)
        await run.until(lambda: run.service.last_error is None)

    run = serve(tau, body, doorbell=bell)
    assert run.sleeps[:2] == [1, 2]
    assert run.service.link == "websocket"


# -- stopping --------------------------------------------------------------------------------------


def test_stop_returns_promptly_while_waiting_on_the_doorbell(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    bell = FakeDoorbell()  # waits the full 300 s

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.link == "websocket" and len(bell.waits) >= 2)

    started = time.monotonic()
    serve(tau, body, doorbell=bell)
    assert time.monotonic() - started < 5
    deadline = time.monotonic() + 5
    while bell.closes == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert bell.closes == 1 and not bell.connected  # closed in the background


def test_doctor_names_the_doorbell(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    status = {"net": {"state": "polling", "address": ALICE, "link": "websocket"}}
    check = doctor_check(tau.config, tau.env, status)
    assert check.status == "ok" and "doorbell" in check.detail
