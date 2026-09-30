"""Crash-report persistence: a stale state.json becomes a crash report; a clean stop leaves none."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tau_core import Config, __version__
from tau_core.hub import UNCLEAN_EXIT, CrashReport, Hub, HubFiles, HubState

T0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


class Clock:
    """A clock that moves one second per call."""

    def __init__(self, start: datetime = T0):
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Stopper:
    """Asks the hub to stop as soon as every service has started."""

    name = "stopper"

    def __init__(self) -> None:
        self.seen_state: dict | None = None

    async def start(self, hub: Hub) -> None:
        self.seen_state = json.loads(hub.files.state.read_text(encoding="utf-8"))
        hub.request_stop()

    async def stop(self) -> None:
        pass


class Failing:
    name = "failing"

    async def start(self, hub: Hub) -> None:
        raise RuntimeError("boom")

    async def stop(self) -> None:
        pass


def _stale_state(pid: int = 4242) -> HubState:
    return HubState(
        pid=pid,
        started_at="2026-09-29T10:00:00+00:00",
        heartbeat_at="2026-09-29T11:59:55+00:00",
        version="0.1.0",
        role="hub",
        profile="home",
        last_crash=None,
    )


def _run(config: Config, *services, clock=None) -> tuple[Hub, int]:
    hub = Hub(config, services=[*services, Stopper()], clock=clock or Clock())
    return hub, hub.run()


def test_run_writes_state_and_stops_cleanly(config: Config) -> None:
    stopper = Stopper()
    hub = Hub(config, services=[stopper], clock=Clock())
    assert hub.run() == 0
    assert stopper.seen_state == {
        "pid": os.getpid(),
        "started_at": "2026-09-29T12:00:02+00:00",
        "heartbeat_at": "2026-09-29T12:00:02+00:00",
        "version": __version__,
        "role": "hub",
        "profile": "home",
        "last_crash": None,
        "stopped_at": None,
    }
    state = HubFiles(config.hub_dir).read_state()
    assert state is not None
    assert state.stopped_at == "2026-09-29T12:00:03+00:00"
    assert state.heartbeat_at == state.stopped_at


def test_stale_state_becomes_a_crash_report(config: Config) -> None:
    files = HubFiles(config.hub_dir)
    files.write_state(_stale_state())
    hub, code = _run(config)
    assert code == 0
    expected = CrashReport(
        pid=4242,
        started_at="2026-09-29T10:00:00+00:00",
        last_heartbeat_at="2026-09-29T11:59:55+00:00",
        reason=UNCLEAN_EXIT,
        detected_at="2026-09-29T12:00:01+00:00",
    )
    assert hub.crash_report == expected
    assert files.read_crash_reports() == [expected]
    assert files.read_last_crash() == expected.to_dict()
    assert hub.state is not None and hub.state.last_crash == expected.to_dict()
    assert hub.status()["last_crash"] == expected.to_dict()


def test_crash_marker_gives_the_reason(config: Config) -> None:
    files = HubFiles(config.hub_dir)
    files.write_state(_stale_state(pid=4242))
    files.write_crash_marker(
        pid=4242, reason="RuntimeError: boom", at="2026-09-29T11:59:56+00:00", traceback="..."
    )
    hub, _ = _run(config)
    assert hub.crash_report is not None
    assert hub.crash_report.reason == "RuntimeError: boom"
    assert not files.crash.exists()  # consumed


def test_crash_marker_of_another_pid_is_ignored(config: Config) -> None:
    files = HubFiles(config.hub_dir)
    files.write_state(_stale_state(pid=4242))
    files.write_crash_marker(pid=1, reason="old", at="2026-09-01T00:00:00+00:00", traceback=None)
    hub, _ = _run(config)
    assert hub.crash_report is not None and hub.crash_report.reason == UNCLEAN_EXIT


def test_clean_stop_leaves_no_crash_report(config: Config) -> None:
    files = HubFiles(config.hub_dir)
    for _ in range(3):
        hub, code = _run(config)
        assert code == 0
        assert hub.crash_report is None
    assert not files.crash_reports.exists()
    assert not files.last_crash.exists()
    assert not files.crash.exists()
    assert files.read_state().last_crash is None


def test_crash_reports_accumulate_and_last_crash_sticks(config: Config) -> None:
    files = HubFiles(config.hub_dir)
    files.write_state(_stale_state(pid=1001))
    _run(config)
    files.write_state(_stale_state(pid=1002))
    _run(config)
    assert [r.pid for r in files.read_crash_reports()] == [1001, 1002]
    # A clean restart still shows the most recent crash.
    hub, _ = _run(config)
    assert hub.crash_report is None
    assert hub.state.last_crash["pid"] == 1002
    assert len(files.read_crash_reports()) == 2


def test_failing_service_records_a_crash_and_the_next_start_reports_it(config: Config) -> None:
    log: list[str] = []

    class First:
        name = "first"

        async def start(self, hub: Hub) -> None:
            log.append("start first")

        async def stop(self) -> None:
            log.append("stop first")

    files = HubFiles(config.hub_dir)
    crashed = Hub(config, services=[First(), Failing()], clock=Clock())
    assert crashed.run() == 1
    assert crashed.crash_reason == "RuntimeError: boom"
    assert log == ["start first", "stop first"]
    state = files.read_state()
    assert state is not None and state.pid == os.getpid() and state.stopped_at is None
    marker = json.loads(files.crash.read_text(encoding="utf-8"))
    assert marker["reason"] == "RuntimeError: boom"
    assert "RuntimeError: boom" in marker["traceback"]

    hub, code = _run(config)
    assert code == 0
    assert hub.crash_report is not None
    assert hub.crash_report.pid == os.getpid()
    assert hub.crash_report.reason == "RuntimeError: boom"


def test_heartbeat_refreshes_state(config: Config) -> None:
    beats: list[str] = []

    class Beater:
        name = "beater"

        async def start(self, hub: Hub) -> None:
            hub.beat()
            beats.append(json.loads(hub.files.state.read_text())["heartbeat_at"])
            hub.beat()
            beats.append(json.loads(hub.files.state.read_text())["heartbeat_at"])

        async def stop(self) -> None:
            pass

    hub, _ = _run(config, Beater())
    assert beats == ["2026-09-29T12:00:03+00:00", "2026-09-29T12:00:04+00:00"]
    assert hub.state.started_at == "2026-09-29T12:00:02+00:00"


def test_unreadable_state_is_not_a_crash(config: Config) -> None:
    files = HubFiles(config.hub_dir)
    files.dir.mkdir(parents=True)
    files.state.write_text("{not json", encoding="utf-8")
    hub, code = _run(config)
    assert code == 0
    assert hub.crash_report is None
    assert files.read_state().stopped_at is not None


def test_state_round_trip_ignores_unknown_keys(tmp_path: Path) -> None:
    data = _stale_state().to_dict() | {"added_later": 1}
    assert HubState.from_dict(data) == _stale_state()
    report = CrashReport(1, "a", "b", "c", "d")
    assert CrashReport.from_dict(report.to_dict() | {"x": 1}) == report


def test_a_hub_start_makes_its_logs_private(config: Config) -> None:
    """launchd creates hub/logs/*.log with the default umask; the hub chmods them (ADR 0008)."""
    logs = HubFiles(config.hub_dir).logs
    logs.mkdir(parents=True, mode=0o755)
    os.chmod(logs, 0o755)
    for name in ("hub.out.log", "hub.err.log"):
        (logs / name).write_text("")
        os.chmod(logs / name, 0o644)
    assert _run(config)[1] == 0
    assert logs.stat().st_mode & 0o777 == 0o700
    for name in ("hub.out.log", "hub.err.log"):
        assert (logs / name).stat().st_mode & 0o777 == 0o600


def test_secure_logs_without_a_logs_directory(tmp_path: Path) -> None:
    HubFiles(tmp_path / "hub").secure_logs()  # nothing to do, nothing raised
