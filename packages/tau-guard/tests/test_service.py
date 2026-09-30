"""``GuardService`` in a fake hub: inactive and broken modes, the open ``/status`` block, the
in-hub ``tau_core.Guard``, ``subscribe`` and ``face_fresh``."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from guard_helpers import TURN, FakeHub, guard_config, until_async, write_marker
from tau_core import Guard, GuardStatus, Tier
from tau_core.approval import ApprovalRequest
from tau_core.hub import ControlApi
from tau_core.testing import test_config
from tau_guard.service import PRESENCE_WAIT, GuardService, make_service
from tau_guard.state import Attempt, Refusal
from tau_guard.testing import (
    FakeClock,
    FakePresence,
    fake_worker_command,
    match,
    read_requests,
    write_script,
)

REQUEST = ApprovalRequest("r1", "lamp", Tier.PHYSICAL, {"state": "on"}, "", "s1", "tui")
OPEN_KEYS = {"state", "enrolled", "available", "reason"}


def make(
    tmp_path: Path, config=None, *, runs=None, clock=None, presence=None, **kwargs
) -> tuple[GuardService, FakeHub, ControlApi, Path]:
    config = config or guard_config(tmp_path)
    work = tmp_path / "worker"
    work.mkdir(exist_ok=True)
    script = write_script(work / "script.json", runs or [[match()]])
    api = ControlApi(0, lambda: {})
    service = GuardService(
        config,
        clock=clock or FakeClock(),
        presence=presence if presence is not None else FakePresence(),
        worker_command=fake_worker_command(script),
        platform=kwargs.pop("platform", "darwin"),
        reflex_loop=kwargs.pop("reflex_loop", False),
        attempt_timeout=kwargs.pop("attempt_timeout", 10.0),
        **kwargs,
    )
    return service, FakeHub({"control-api": api}), api, script


def guard_routes(api: ControlApi) -> set[tuple[str, str]]:
    return {key for key in api.routes if key[1].startswith("/guard/")}


# -- inactive ------------------------------------------------------------------------------------


async def test_inactive_service_reports_off_only(tmp_path: Path) -> None:
    service, hub, api, _ = make(tmp_path, test_config(tmp_path))
    await service.start(hub)  # type: ignore[arg-type]
    assert hub.status() == {"guard": {"state": "off"}}
    assert service.mode == "off" and guard_routes(api) == set()
    assert service._reflex_thread is None and service.machine is None
    assert not (tmp_path / "data" / "guard").exists()
    assert await service.admit(TURN) == type(await service.admit(TURN))(False, "unavailable")
    assert (await service.status()).state == "off"
    await service.stop()


def test_inactive_hub_starts_no_thread_and_imports_no_camera_module(tmp_path: Path) -> None:
    """In a fresh interpreter: the full ``assemble_hub`` with every installed component."""
    code = textwrap.dedent(
        f"""
        import json, sys, threading, time, urllib.request
        from tau_core.testing import test_config
        from tau_core.hub.cli import assemble_hub
        config = test_config({str(tmp_path)!r})
        hub, api = assemble_hub(config, port=0)
        thread = threading.Thread(target=hub.run, daemon=True)
        thread.start()
        while api.port == 0 or hub.find_service("guard") is None:
            time.sleep(0.02)
        status = json.load(urllib.request.urlopen(api.url + "/status"))
        names = sorted(t.name for t in threading.enumerate())
        routes = sorted(p for _, p in api.routes if p.startswith("/guard"))
        modules = sorted(m for m in ("cv2", "objc", "Quartz", "AVFoundation") if m in sys.modules)
        hub.request_stop(); thread.join(10)
        print(json.dumps({{"guard": status.get("guard"), "threads": names,
                           "routes": routes, "modules": modules}}))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True
    )
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report["guard"] == {"state": "off"}
    assert report["routes"] == [] and report["modules"] == []
    assert not [name for name in report["threads"] if name.startswith("tau-guard")]


# -- active --------------------------------------------------------------------------------------


async def test_active_service_starts_locked_with_routes_and_a_private_directory(
    tmp_path: Path,
) -> None:
    service, hub, api, _ = make(tmp_path)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert service.mode == "active"
        assert guard_routes(api) == set(service.routes) and len(service.routes) == 6
        assert hub.status()["guard"] == {
            "state": "locked",
            "enrolled": True,
            "available": True,
            "reason": None,
        }
        status = await service.status()
        assert (status.state, status.lock_trigger, status.enrolled) == ("locked", "startup", True)
        guard_dir = tmp_path / "data" / "guard"
        assert stat.S_IMODE(guard_dir.stat().st_mode) == 0o700
        audit = [json.loads(line) for line in (guard_dir / "audit.jsonl").read_text().splitlines()]
        assert audit[0]["event"] == "lock" and audit[0]["trigger"] == "startup"
    finally:
        await service.stop()


@pytest.mark.parametrize(
    ("table", "platform", "presence", "reason"),
    [
        ({"idle_lock_minutes": 0}, "darwin", FakePresence(), "config"),
        ({"max_unlock_hours": "eight"}, "darwin", FakePresence(), "config"),
        ({"enabled": "yes"}, "darwin", FakePresence(), "config"),
        ({"enable": True}, "darwin", FakePresence(), "config"),  # a typo never means "off"
        ({}, "linux", FakePresence(), "unsupported_platform"),
    ],
)
async def test_active_but_broken_is_unavailable_never_omitted(
    tmp_path: Path, table: dict, platform: str, presence: FakePresence, reason: str
) -> None:
    config = test_config(tmp_path, component_tables={"guard": {"enabled": True, **table}})
    if "enabled" in table or "enable" in table:
        config = test_config(tmp_path, component_tables={"guard": table})
    write_marker(config)
    service, hub, api, script = make(tmp_path, config, platform=platform, presence=presence)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        block = hub.status()["guard"]
        assert block == {
            "state": "unavailable",
            "enrolled": True,
            "available": False,
            "reason": reason,
        }
        assert set(block) == OPEN_KEYS
        assert guard_routes(api)  # the routes answer "unavailable" instead of a 404
        assert (await service.admit(TURN)).reason == "unavailable"
        verdict = await service.unlock(channel="tui", client_id="c1")
        assert not verdict.ok and verdict.reason == "unavailable"
        assert not (script.parent / "requests.jsonl").exists()
    finally:
        await service.stop()


async def test_no_presence_source_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "Quartz", None)
    config = guard_config(tmp_path)
    service = GuardService(config, clock=FakeClock(), platform="darwin", reflex_loop=False)
    hub = FakeHub({"control-api": ControlApi(0, lambda: {})})
    await service.start(hub)  # type: ignore[arg-type]
    assert hub.status()["guard"]["reason"] == "presence_unavailable"
    await service.stop()


async def test_a_start_failure_still_reports_unavailable(tmp_path: Path, monkeypatch) -> None:
    service, hub, _, _ = make(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("tau_guard.service.secure_dir", boom)
    await service.start(hub)  # never raises into the hub
    assert hub.status()["guard"] == {
        "state": "unavailable",
        "enrolled": True,
        "available": False,
        "reason": "error",
    }
    await service.stop()


async def test_enabled_but_not_enrolled_admits_nothing(tmp_path: Path) -> None:
    service, hub, _, script = make(tmp_path, guard_config(tmp_path, enrolled=False))
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert hub.status()["guard"]["enrolled"] is False
        assert (await service.admit(TURN)).reason == "not_enrolled"
        verdict = await service.unlock(channel="tui", client_id="c1")
        assert (verdict.ok, verdict.reason) == (False, "not_enrolled")
        assert not (script.parent / "requests.jsonl").exists()
    finally:
        await service.stop()


async def test_open_status_shows_a_stalled_reflex_loop_and_an_unknown_screen(
    tmp_path: Path, clock: FakeClock
) -> None:
    presence = FakePresence(screen_locked=None)
    service, hub, _, _ = make(tmp_path, clock=clock, presence=presence)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert hub.status()["guard"]["reason"] == "screen_unknown"
        clock.advance(7)
        block = hub.status()["guard"]
        assert block["available"] is False and block["reason"] == "reflex_stalled"
        assert (await service.admit(TURN)).reason == "unavailable"
    finally:
        await service.stop()


# -- the in-hub Guard ----------------------------------------------------------------------------


async def test_service_is_a_guard_and_unlocks_in_hub(tmp_path: Path, clock: FakeClock) -> None:
    service, hub, _, _ = make(
        tmp_path, clock=clock, runs=[[{"progress": "look"}, {"sleep": 0.05}, match()]]
    )
    assert isinstance(service, Guard) and isinstance(make_service(guard_config(tmp_path)), Guard)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        steps: list[str] = []
        verdict = await service.unlock(
            channel="tui", client_id="c1", on_progress=lambda p: steps.append(p.step)
        )
        assert (verdict.ok, verdict.reason, verdict.method) == (True, "match", "face")
        assert "look" in steps
        assert (await service.admit(TURN)).allowed is True
        assert await service.step_up(REQUEST, client_id="c1") is True
        await service.lock(channel="telegram", client_id="t1", trigger="telegram")
        status = await service.status()
        assert (status.state, status.lock_trigger) == ("locked", "telegram")
        assert await service.step_up(REQUEST, client_id="c1") is False
        assert (await service.unlock(channel="tui", client_id="c1", kind="bogus")).reason == "error"
    finally:
        await service.stop()


async def test_subscribe_sees_every_change_and_face_fresh_follows_the_face(
    tmp_path: Path, clock: FakeClock
) -> None:
    service, hub, _, _ = make(tmp_path, clock=clock, runs=[[{"progress": "look"}, match()]])
    await service.start(hub)  # type: ignore[arg-type]
    seen: list[GuardStatus] = []
    unsubscribe = service.subscribe(seen.append)
    try:
        assert not service.face_fresh(30)
        await service.unlock(channel="tui", client_id="c1")
        await asyncio.sleep(0.05)  # callbacks run on the hub loop
        states = [s.state for s in seen]
        assert states[0] == "verifying" and states[-1] == "unlocked"
        assert [s.seq for s in seen] == sorted({s.seq for s in seen})
        assert any(s.attempt is not None and s.attempt.step == "look" for s in seen)
        assert service.face_fresh(30)
        clock.advance(31)
        service.tick()
        assert not service.face_fresh(30) and service.face_fresh(60)
        count = len(seen)
        await service.lock(channel="tui", client_id="c1")
        await asyncio.sleep(0.05)
        assert seen[-1].state == "locked" and len(seen) > count
        unsubscribe()
        await service.lock(channel="tui", client_id="c1")
        await service.unlock(channel="tui", client_id="c1")
        await asyncio.sleep(0.05)
        assert seen[-1].state == "locked"  # nothing after unsubscribing
    finally:
        await service.stop()


async def test_a_raising_subscriber_does_not_break_the_guard(tmp_path: Path) -> None:
    service, hub, _, _ = make(tmp_path)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        service.subscribe(lambda status: 1 / 0)
        verdict = await service.unlock(channel="tui", client_id="c1")
        assert verdict.ok
    finally:
        await service.stop()


async def test_watch_returns_on_a_change(tmp_path: Path) -> None:
    service, hub, _, _ = make(tmp_path)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        first = await service.status()
        waiter = asyncio.ensure_future(service.watch(first.seq, wait=5))
        await asyncio.sleep(0.05)
        assert not waiter.done()
        await service.unlock(channel="tui", client_id="c1")
        changed = await asyncio.wait_for(waiter, 5)
        assert changed.seq > first.seq
        quiet = await service.watch(10**9, wait=0.05)
        assert quiet.state == "unlocked"
    finally:
        await service.stop()


async def test_cancelling_an_in_hub_unlock_cancels_the_attempt(tmp_path: Path) -> None:
    service, hub, _, script = make(tmp_path, runs=[[{"hang": True}]])
    await service.start(hub)  # type: ignore[arg-type]
    try:
        task = asyncio.ensure_future(service.unlock(channel="tui", client_id="c1"))
        await until_async(lambda: (script.parent / "requests.jsonl").exists())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        status = await service.status()
        assert status.state == "locked" and status.last_verdict == "cancelled"
    finally:
        await service.stop()


# -- verification fixes: stopping, reflexes at the verdict, restarts, the event loop -------------


class GatedPresence(FakePresence):
    """A presence source whose reads block (in the named thread, or in any) until released."""

    def __init__(self, thread_name: str | None = None) -> None:
        super().__init__()
        self.thread_name = thread_name
        self.armed = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def read(self):  # type: ignore[no-untyped-def]
        name = threading.current_thread().name
        if self.armed and (self.thread_name is None or name == self.thread_name):
            self.entered.set()
            self.release.wait(10)
        return super().read()


class SlowPresence(FakePresence):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    def read(self):  # type: ignore[no-untyped-def]
        time.sleep(self.delay)
        return super().read()


def workers(script: Path) -> list[int]:
    return [int(entry["pid"]) for entry in read_requests(script)]


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


async def test_a_request_that_read_presence_before_the_stop_starts_no_worker(
    tmp_path: Path,
) -> None:
    """The hub stops services in reverse order, so /guard/verify is still served meanwhile."""
    presence = GatedPresence("verify-route")
    service, hub, _, script = make(tmp_path, runs=[[{"hang": True}]], presence=presence)
    await service.start(hub)  # type: ignore[arg-type]
    presence.armed = True
    result: dict = {}

    def route() -> None:  # what a control-API thread does for POST /guard/verify
        result["answer"] = service._request_sync("unlock", channel="tui", client_id="c1")

    thread = threading.Thread(target=route, name="verify-route")
    thread.start()
    await until_async(presence.entered.is_set)  # past the mode check, reading presence
    stopping = asyncio.ensure_future(service.stop())
    await until_async(lambda: service.mode == "stopped")
    presence.release.set()
    thread.join(5)
    await stopping
    answer, _ = result["answer"]
    assert answer == Refusal("unavailable")
    assert workers(script) == [] and service.machine is not None
    assert service.machine.running is None and service.machine.state == "locked"


async def test_no_worker_starts_once_the_hub_is_stopping(tmp_path: Path) -> None:
    service, hub, _, script = make(tmp_path, runs=[[{"hang": True}]])
    await service.start(hub)  # type: ignore[arg-type]
    try:
        service._stop_event.set()  # stop() has begun
        with service._transaction() as machine:
            attempt = machine.request("unlock", channel="tui", client_id="c1")
        assert isinstance(attempt, Attempt)
        assert (attempt.done, attempt.reason) == (True, "unavailable")
        assert workers(script) == [] and service._all_runs == []
    finally:
        await service.stop()


async def test_stop_kills_a_worker_the_machine_no_longer_tracks(tmp_path: Path) -> None:
    service, hub, _, script = make(tmp_path, runs=[[{"hang": True}]])
    await service.start(hub)  # type: ignore[arg-type]
    task = asyncio.ensure_future(service.unlock(channel="tui", client_id="c1"))
    await until_async(lambda: bool(workers(script)))
    service._runs.clear()  # as if the lock's kill effect never found the run
    await service.stop()
    assert all(gone(pid) for pid in workers(script))
    assert not (await task).ok


def slept(clock: FakeClock, presence: FakePresence) -> None:
    clock.sleep(120)  # the Mac slept: wall time moved, monotonic time did not


def screen_locked(clock: FakeClock, presence: FakePresence) -> None:
    presence.screen_locked = True


def aged(clock: FakeClock, presence: FakePresence) -> None:
    clock.advance(8 * 3600 + 1)


@pytest.mark.parametrize(
    ("change", "trigger"),
    [(slept, "sleep"), (screen_locked, "screen_lock"), (aged, "max_age")],
    ids=["sleep", "screen_lock", "max_age"],
)
async def test_a_step_up_verdict_after_a_reflex_lock_counts_for_nothing(
    tmp_path: Path, change, trigger: str
) -> None:
    clock, presence = FakeClock(), FakePresence()
    runs = [[match()], [{"sleep": 0.4}, match()]]
    service, hub, _, script = make(tmp_path, clock=clock, presence=presence, runs=runs)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert (await service.unlock(channel="tui", client_id="c1")).ok
        step_up = asyncio.ensure_future(service.step_up(REQUEST, client_id="c1"))
        await until_async(lambda: len(workers(script)) == 2)
        change(clock, presence)  # no reflex tick before the verdict arrives
        assert await step_up is False
        status = await service.status()
        assert (status.state, status.lock_trigger) == ("locked", trigger)
    finally:
        await service.stop()


async def test_an_unlock_verdict_after_a_screen_lock_does_not_unlock(tmp_path: Path) -> None:
    presence = FakePresence()
    runs = [[{"sleep": 0.4}, match()]]
    service, hub, _, script = make(tmp_path, presence=presence, runs=runs)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        unlock = asyncio.ensure_future(service.unlock(channel="tui", client_id="c1"))
        await until_async(lambda: bool(workers(script)))
        presence.screen_locked = True
        verdict = await unlock
        assert (verdict.ok, verdict.reason) == (False, "cancelled")
        status = await service.status()
        assert (status.state, status.lock_trigger) == ("locked", "screen_lock")
    finally:
        await service.stop()


async def test_subscribers_see_the_switch_to_unavailable(tmp_path: Path) -> None:
    service, hub, _, _ = make(tmp_path)
    seen: list[GuardStatus] = []
    service.subscribe(seen.append)
    await service.start(hub)  # type: ignore[arg-type]
    assert (await service.unlock(channel="tui", client_id="c1")).ok
    await service.stop()
    await asyncio.sleep(0.05)
    assert [s.state for s in seen[-2:]] == ["locked", "unavailable"]
    assert seen[-2].lock_trigger == "hub_stop" and seen[-1].reason == "stopped"
    broken, hub2, _, _ = make(tmp_path / "b", platform="linux")
    later: list[GuardStatus] = []
    broken.subscribe(later.append)
    await broken.start(hub2)  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    assert later and later[-1].state == "unavailable"
    assert later[-1].reason == "unsupported_platform"
    await broken.stop()


SPOOF = {"verdict": {"ok": False, "reason": "spoof", "method": None, "score": 0.3}}


async def test_a_restart_keeps_the_failures_and_the_cooldown(tmp_path: Path) -> None:
    clock, config = FakeClock(), guard_config(tmp_path)
    service, hub, _, script = make(tmp_path, config, clock=clock, runs=[[SPOOF]])
    await service.start(hub)  # type: ignore[arg-type]
    for _ in range(3):
        assert (await service.unlock(channel="tui", client_id="c1")).reason == "spoof"
    assert (await service.unlock(channel="tui", client_id="c1")).reason == "cooldown"
    await service.stop()
    saved = tmp_path / "data" / "guard" / "failures.json"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert set(json.loads(saved.read_text())) >= {"failures", "cooldown_until", "level"}
    clock.advance(3)  # TauBar's switch off and on again
    again, hub2, _, _ = make(tmp_path, config, clock=clock, runs=[[match()]])
    await again.start(hub2)  # type: ignore[arg-type]
    try:
        status = await again.status()
        assert (status.state, status.failures) == ("locked", 3)
        assert status.cooldown_until is not None
        verdict = await again.unlock(channel="tui", client_id="c1")
        assert (verdict.ok, verdict.reason, verdict.retry_after) == (False, "cooldown", 27.0)
        assert len(workers(script)) == 3  # no worker ran after the restart
    finally:
        await again.stop()


async def test_a_malformed_failure_file_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    guard_dir = tmp_path / "data" / "guard"
    guard_dir.mkdir(parents=True)
    (guard_dir / "failures.json").write_text('{"v": 1, "failures": "many"}', encoding="utf-8")
    service, hub, _, _ = make(tmp_path)
    with caplog.at_level("WARNING", logger="tau_guard"):
        await service.start(hub)  # type: ignore[arg-type]
    try:
        assert service.mode == "active" and (await service.status()).failures == 0
        assert "failures.json is malformed" in caplog.text
    finally:
        await service.stop()


async def test_nothing_starts_while_the_screen_is_locked(tmp_path: Path) -> None:
    presence = FakePresence(screen_locked=True)
    service, hub, _, script = make(tmp_path, presence=presence)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        verdict = await service.unlock(channel="ssh", client_id="c1")
        assert (verdict.ok, verdict.reason) == (False, "locked")
        answer, _ = service._request_sync("enroll", channel="enroll", client_id="c1")
        assert answer == Refusal("locked") and workers(script) == []
    finally:
        await service.stop()


async def test_in_hub_calls_never_stall_the_event_loop(tmp_path: Path) -> None:
    service, hub, _, _ = make(tmp_path, runs=[[match()]])
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert (await service.unlock(channel="tui", client_id="c1")).ok
        service.presence = SlowPresence(0.4)  # a WindowServer that answers slowly
        gaps: list[float] = []
        done = False

        async def ticker() -> None:
            last = time.monotonic()
            while not done:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        ticking = asyncio.ensure_future(ticker())
        assert (await service.admit(TURN)).allowed
        assert await service.step_up(REQUEST, client_id="c1") is True
        done = True
        await ticking
        assert gaps and max(gaps) < 0.3  # a 0.4 s read never blocked the loop
        hung = GatedPresence()
        hung.armed = True
        service.presence = hung
        began = time.monotonic()
        assert service.face_fresh(3600) is False  # no reading, no microphone
        assert time.monotonic() - began < PRESENCE_WAIT + 0.5
        hung.release.set()
    finally:
        await service.stop()


async def test_cancelling_during_the_request_withdraws_from_its_attempt(tmp_path: Path) -> None:
    presence = GatedPresence("tau-guard-call")
    service, hub, _, _ = make(tmp_path, presence=presence, runs=[[{"hang": True}]])
    await service.start(hub)  # type: ignore[arg-type]
    try:
        presence.armed = True
        task = asyncio.ensure_future(service.unlock(channel="tui", client_id="c1"))
        await until_async(presence.entered.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        presence.release.set()  # the request goes on and starts its attempt after all
        machine = service.machine
        assert machine is not None
        await until_async(lambda: machine.last_verdict == "cancelled")
        assert machine.running is None and machine.state == "locked"
        await until_async(lambda: not any(run.alive for run in service._all_runs), timeout=5)
    finally:
        await service.stop()
