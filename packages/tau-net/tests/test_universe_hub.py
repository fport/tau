"""The tau universe on the hub (ADR 0010, docs/reference/tau-universe.md §3): reports from a
node (only listed contacts), two taus with one mutual link, the ``net`` hub service and
``tau net universe``. Offline: every host is a fake on one FakeNetwork."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from net_helpers import (
    ALICE,
    BOB,
    UNIVERSE,
    Tau,
    connect,
    make_tau,
    poll,
    published,
    universe_tau,
)
from tau_core.hub.daemon import Hub
from tau_net.cli import net
from tau_net.node import NetError
from tau_net.service import NetService
from tau_net.testing import FakeNetwork, FakeUniverse
from tau_net.universe import parse_request, tau_links

CAROL = "carol.example"
DAVE = "dave.example"


# -- reports from a node -----------------------------------------------------------------------


def contacts_of_alice(tmp_path: Path, network: FakeNetwork) -> tuple[Tau, Any, Tau, Tau]:
    """Alice with two accepted contacts: Bob (who joins the universe) and Carol (who does not),
    and a pending request to Dave (who joins)."""
    a = universe_tau(tmp_path, network, ALICE, component={"auto_reply": False})
    b = universe_tau(tmp_path, network, BOB, component={"auto_reply": False})
    c = universe_tau(tmp_path, network, CAROL, component={"auto_reply": False})
    d = universe_tau(tmp_path, network, DAVE)
    a_node, b_node = connect(a, b)
    connect(a, c)
    published(d)
    a_node.add(DAVE)
    for tau in (b, d):
        node = tau.node()
        node.update_profile(universe_join=True)
        node.universe_join()
    a_node.send(BOB, "one")
    a_node.send(CAROL, "two")
    return a, a_node, b, c


def test_reports_list_only_contacts_the_universe_lists(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    a, a_node, _, _ = contacts_of_alice(tmp_path, network)
    a_node.update_profile(universe_join=True)
    a_node.universe_join()
    before = len(universe.requests)
    answer = a_node.universe_report()
    assert universe.requests[before] == ("GET", "/api/universe")  # the snapshot comes first
    assert answer == {"ok": True, "visible_links": 0}  # Bob has not reported Alice yet
    [report] = [p for p in universe.payloads("report") if p["address"] == ALICE]
    assert report["links"] == [{"peer": BOB, "messages": 1}]
    alice_bodies = [
        body for body in universe.bodies() if parse_request(body).payload["address"] == ALICE
    ]
    for body in alice_bodies:  # the unlisted contact never leaves the hub in any form
        assert CAROL.encode() not in parse_request(body).payload_bytes
        assert CAROL.encode() not in body
    # DAVE is listed but only pending: not a link either
    assert all(link["peer"] != DAVE for link in report["links"])


def test_links_off_sends_an_empty_list_without_reading_the_snapshot(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    a, a_node, _, _ = contacts_of_alice(tmp_path, network)
    a_node.update_profile(universe_join=True, universe_links=False)
    a_node.universe_join()
    before = len(universe.requests)
    a_node.universe_report()
    assert ("GET", "/api/universe") not in universe.requests[before:]
    assert universe.payloads("report")[-1]["links"] == []
    # the tau.toml setting is the default the profile overrides
    off = universe_tau(
        tmp_path / "off", network, "erin.example", component={"universe_links": False}
    )
    assert off.node().universe_links_enabled() is False
    assert off.node().universe_links() == []


def test_a_switched_off_universe(tmp_path: Path, network: FakeNetwork) -> None:
    tau = make_tau(tmp_path, network, ALICE, component={"universe": ""})
    node = tau.node()
    with pytest.raises(NetError, match="switched off"):
        node.universe()
    node.update_profile(universe_join=True)
    assert node.universe_sync().visible_links is None


def test_two_taus_join_talk_report_and_show_one_mutual_link(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    a = universe_tau(tmp_path, network, ALICE, component={"auto_reply": False})
    b = universe_tau(tmp_path, network, BOB, component={"auto_reply": False})
    a_node, b_node = connect(a, b)
    for node, owner in ((a_node, "Alice"), (b_node, "Bob")):
        node.update_profile(universe_join=True, universe_owner=owner)
        assert node.universe_join()["url"].endswith(f"#{node.address()}")
    for text in ("one", "two", "three"):
        a_node.send(BOB, text)
    poll(b_node)
    b_node.send(ALICE, "four")  # Alice has not polled yet: she counts 3, Bob counts 4
    assert a_node.universe_report()["visible_links"] == 0  # one-sided: not shown
    assert universe.snapshot()["links"] == []
    assert b_node.universe_report()["visible_links"] == 1
    snapshot = universe.snapshot()
    assert snapshot["links"] == [{"a": ALICE, "b": BOB, "messages": 3}]  # the smaller count
    assert snapshot["stats"] == {"taus": 2, "online": 2, "messages": 3}
    assert [(t["address"], t["owner"]) for t in snapshot["taus"]] == [
        (ALICE, "Alice"),
        (BOB, "Bob"),
    ]
    poll(a_node)
    assert a_node.universe_report()["visible_links"] == 1
    assert universe.snapshot()["links"][0]["messages"] == 4
    entry = json.loads(universe.handle("GET", f"/api/taus/{ALICE}", {})[2])
    assert entry["links"] == [{"peer": BOB, "messages": 4}]
    assert tau_links(entry, ALICE) == [(BOB, 4)]
    # the one who leaves takes the link along
    b_node.universe_leave()
    snapshot = universe.snapshot()
    assert snapshot["links"] == [] and [t["address"] for t in snapshot["taus"]] == [ALICE]


# -- the hub service ---------------------------------------------------------------------------


FIXED = int(time.time()) + 100
"""The service's clock: ahead of every real-clock request a test makes, within the 300 s a
universe allows, so the service's ts always wins."""


class Interval:
    """The report-interval sleeper: records each delay and waits until the test releases it."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.released = 0

    def release(self) -> None:
        self.released += 1

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        while len(self.delays) > self.released:
            await asyncio.sleep(0.002)


async def until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.005)


def serve(
    tau: Tau, body: Callable[[NetService], Awaitable[None]], interval: Interval
) -> NetService:
    async def fast(delay: float) -> None:
        await asyncio.sleep(0.001)

    service = NetService(
        tau.config,
        env=tau.env,
        transport=tau.network,
        model_factory=lambda: tau.model,
        sleep=fast,
        universe_sleep=interval.sleep,
        clock=lambda: FIXED,
    )

    async def main() -> None:
        await service.start(Hub(tau.config))
        try:
            await body(service)
        finally:
            await service.stop()

    asyncio.run(main())
    return service


def test_the_service_reports_at_start_and_every_interval(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    tau = universe_tau(tmp_path, network, ALICE, component={"universe_report_minutes": 30})
    node = published(tau)
    node.update_profile(universe_join=True)
    node.universe_join()
    interval = Interval()

    async def body(service: NetService) -> None:
        await until(lambda: len(interval.delays) == 1)
        assert service.universe_reports == 1  # at start
        interval.release()
        await until(lambda: len(interval.delays) == 2)
        assert service.universe_reports == 2  # after one interval

    service = serve(tau, body, interval)
    assert interval.delays == [1800, 1800]
    assert [p["kind"] for p in universe.payloads()] == ["join", "report", "report"]
    assert service.status()["universe"] == {
        "universe": UNIVERSE,
        "joined": True,
        "last_report_at": datetime.fromtimestamp(FIXED, UTC).isoformat(timespec="seconds"),
        "last_error": None,
        "visible_links": 0,
    }
    assert "test-hub-token" not in json.dumps(service.status())


def test_the_service_never_crashes_on_universe_errors(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    tau = universe_tau(tmp_path, network, ALICE)
    tau.node().update_profile(universe_join=True)
    network.down.add(UNIVERSE)
    interval = Interval()

    async def body(service: NetService) -> None:
        await until(lambda: len(interval.delays) == 1)
        status = service.status()
        assert status["state"] == "polling"  # the poll loop does not care
        assert "unreachable" in status["universe"]["last_error"]
        assert status["universe"]["joined"] is True
        assert status["universe"]["last_report_at"] is None
        network.down.clear()
        interval.release()
        await until(lambda: len(interval.delays) == 2)

    service = serve(tau, body, interval)
    # the universe did not list the tau: the service joined before it reported again
    assert [p["kind"] for p in universe.payloads()] == ["report", "join", "report"]
    assert service.universe_status()["last_error"] is None
    assert service.universe_reports == 1 and ALICE in universe.taus


def test_the_service_follows_join_and_leave_without_a_restart(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse
) -> None:
    tau = universe_tau(tmp_path, network, ALICE)
    node = published(tau)
    interval = Interval()

    async def body(service: NetService) -> None:
        await until(lambda: len(interval.delays) == 1)
        assert service.status()["universe"]["joined"] is False  # not joined: nothing sent
        node.update_profile(universe_join=True)  # `tau net universe join` in a terminal
        node.universe_join()
        interval.release()
        await until(lambda: len(interval.delays) == 2)
        assert service.universe_reports == 1
        node.update_profile(universe_join=False)  # `tau net universe leave`
        interval.release()
        await until(lambda: len(interval.delays) == 3)
        assert service.universe_joined is False

    serve(tau, body, interval)
    assert [p["kind"] for p in universe.payloads()] == ["join", "report"]


def test_the_service_has_no_universe_task_when_it_is_switched_off(
    tmp_path: Path, network: FakeNetwork
) -> None:
    tau = make_tau(tmp_path, network, BOB, component={"universe": ""})
    tau.node().update_profile(universe_join=True)
    interval = Interval()

    async def body(service: NetService) -> None:
        await until(lambda: service.state == "polling")
        await asyncio.sleep(0.05)

    service = serve(tau, body, interval)
    assert interval.delays == [] and service.status()["universe"]["universe"] == ""


# -- tau net universe --------------------------------------------------------------------------


@pytest.fixture
def invoke(monkeypatch: pytest.MonkeyPatch):
    def run(tau: Tau, *args: str, env: dict[str, str] | None = None) -> Result:
        monkeypatch.setenv("TAU_DATA_DIR", str(tau.config.data_dir))
        obj = {
            "home": tau.config.home,
            "net_env": tau.env if env is None else env,
            "net_transport": tau.network,
            "net_model_factory": lambda: tau.model,
        }
        return CliRunner().invoke(net, list(args), obj=obj)

    return run


def test_join_status_leave_from_the_command_line(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse, invoke
) -> None:
    a = universe_tau(tmp_path, network, ALICE, component={"auto_reply": False})
    b = universe_tau(tmp_path, network, BOB, component={"auto_reply": False})
    a_node, b_node = connect(a, b)
    a_node.send(BOB, "hello")
    toml = (a.config.home / "tau.toml").read_bytes()

    result = invoke(b, "universe", "join")
    assert result.exit_code == 0, result.output
    joined = invoke(a, "universe", "join", "--owner", "Alice", "--about", "Plans hikes.")
    assert joined.exit_code == 0, joined.output
    assert joined.output.splitlines() == [
        f"Joined the universe {UNIVERSE}: https://{UNIVERSE}/universe#{ALICE}",
        "Report sent. Listed contacts: 1; visible links: 0 "
        "(a link shows once both taus report each other).",
    ]
    poll(b_node)
    assert b_node.universe_report()["visible_links"] == 1  # Bob's hub reports Alice back
    assert (a.config.home / "tau.toml").read_bytes() == toml  # never tau.toml
    profile = json.loads((a.net_dir / "profile.json").read_text())
    assert profile == {
        "universe_join": True,
        "universe_owner": "Alice",
        "universe_about": "Plans hikes.",
    }

    status = invoke(a, "universe", "status")
    assert status.exit_code == 0, status.output
    lines = status.output.splitlines()
    assert lines[:5] == [
        f"universe: {UNIVERSE}",
        "joined:   yes, the hub reports every 60 min",
        "links:    on (mutual links with listed contacts are reported)",
        "owner:    Alice",
        "about:    Plans hikes.",
    ]
    assert lines[5].startswith("listed:   yes, online, last report ")
    assert lines[6:] == [
        f"page:     https://{UNIVERSE}/universe#{ALICE}",
        f"visible:  {BOB}, messages: 1",
    ]

    left = invoke(a, "universe", "leave")
    assert left.output.strip() == (
        f"Left the universe {UNIVERSE}: this tau and its links are no longer listed."
    )
    assert json.loads((a.net_dir / "profile.json").read_text())["universe_join"] is False
    again = invoke(a, "universe", "leave")
    assert again.exit_code == 0
    assert "was not listed" in again.output
    after = invoke(a, "universe", "status").output.splitlines()
    assert "joined:   no (`tau net universe join` lists this tau)" in after
    assert after[-1] == "listed:   no"
    assert (a.config.home / "tau.toml").read_bytes() == toml


def test_join_with_no_links_and_a_card_to_publish(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse, invoke
) -> None:
    a = universe_tau(tmp_path, network, ALICE)
    result = invoke(a, "universe", "join", "--no-links")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"Published the card of {ALICE} as Alice's tau.",
        f"Joined the universe {UNIVERSE}: https://{UNIVERSE}/universe#{ALICE}",
        "Report sent without links (links are off).",
    ]
    assert universe.payloads("report")[-1]["links"] == []
    assert json.loads((a.net_dir / "profile.json").read_text())["universe_links"] is False
    assert "links:    off" in invoke(a, "universe", "status").output
    invoke(a, "universe", "join", "--links")
    assert json.loads((a.net_dir / "profile.json").read_text())["universe_links"] is True


def test_universe_command_errors(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse, invoke
) -> None:
    a = universe_tau(tmp_path, network, ALICE)
    published(a)
    long_owner = invoke(a, "universe", "join", "--owner", "x" * 61)
    assert long_owner.exit_code == 1
    assert long_owner.stderr.strip() == (
        "tau net: the universe owner name must be at most 60 characters"
    )
    assert not (a.net_dir / "profile.json").exists()
    network.down.add(UNIVERSE)
    down = invoke(a, "universe", "join")
    assert down.exit_code == 1
    assert down.stderr.startswith(f"tau net: the join failed: universe {UNIVERSE} unreachable")
    assert len(down.stderr.strip().splitlines()) == 1
    status = invoke(a, "universe", "status")
    assert status.exit_code == 1 and "joined:   yes" in status.output
    network.down.clear()
    off = make_tau(tmp_path / "off", network, BOB, component={"universe": ""})
    for args in (("join",), ("leave",)):
        result = invoke(off, "universe", *args)
        assert result.exit_code == 1 and "switched off" in result.stderr
    assert invoke(off, "universe", "status").output.strip() == (
        'universe: off ([component.net] universe = "")'
    )
    no_spine = invoke(a, "universe", "join", env={})
    assert no_spine.exit_code == 1 and "TAU_SPINE_URL" in no_spine.stderr


def test_name_command_and_turkish_output(
    tmp_path: Path, network: FakeNetwork, universe: FakeUniverse, invoke, monkeypatch
) -> None:
    a = universe_tau(tmp_path, network, ALICE)
    toml = (a.config.home / "tau.toml").read_bytes()
    named = invoke(a, "name", "Alice's", "home", "tau")
    assert named.exit_code == 0
    assert named.output.splitlines()[0].startswith(
        "Card name set to Alice's home tau in the network profile (file "
    )
    assert (a.config.home / "tau.toml").read_bytes() == toml
    assert "name:     Alice's home tau" in invoke(a, "status").output
    monkeypatch.setenv("TAU_LANG", "tr")
    joined = invoke(a, "universe", "join")
    assert (
        joined.output.splitlines()[0] == "alice.example kartı Alice's home tau adıyla yayımlandı."
    )
    assert joined.output.splitlines()[1] == (
        f"{UNIVERSE} evrenine katıldın: https://{UNIVERSE}/universe#{ALICE}"
    )
