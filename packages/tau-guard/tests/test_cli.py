"""``tau guard status|lock|log`` (CliRunner; a hub on port 0, never the live one)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from guard_helpers import cli_config, running_hub
from tau_core import Config
from tau_core.config import HubConfig
from tau_core.hub import HubClient
from tau_core.i18n import t
from tau_guard.audit import AuditLog
from tau_guard.cli import entry_line, guard, parse_since
from tau_guard.testing import FakeClock, match


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def invoke(config: Config, *args: str, client: object | None = None, env: dict | None = None):
    obj = {"home": config.home, "guard_client": client or HubClient(config)}
    environment = {"TAU_DATA_DIR": str(config.data_dir), **(env or {})}
    return CliRunner().invoke(guard, list(args), obj=obj, env=environment)


def test_status_when_the_guard_is_off(tmp_path: Path) -> None:
    config = cli_config(tmp_path, active=False)
    result = invoke(config, "status")
    assert result.exit_code == 0 and result.output.strip() == t("guard.cli.off")
    assert json.loads(invoke(config, "status", "--json").output) == {"state": "off"}


def test_status_without_a_hub(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    result = invoke(config, "status")
    assert result.exit_code == 0
    assert result.output.strip() == t("guard.cli.no_hub", hint=t("guard.start_hub"))
    answer = json.loads(invoke(config, "status", "--json").output)
    assert answer == {"state": "unavailable", "reason": "no_hub"}


async def test_status_and_lock_against_a_running_hub(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    with running_hub(tmp_path, config=config, runs=[[match()]]) as running:
        client = running.client
        result = invoke(config, "status", client=client)
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == t("guard.cli.state", state=t("guard.state.locked"))
        assert t("guard.lock_trigger.startup") in lines[1]
        assert (await running.guard.unlock(channel="tui", client_id="c1")).ok
        result = invoke(config, "status", client=client)
        assert t("guard.state.unlocked") in result.output and "face" in result.output
        payload = json.loads(invoke(config, "status", "--json", client=client).output)
        assert payload["state"] == "unlocked" and payload["enrollment"] == "E1"
        result = invoke(config, "lock", client=client)
        assert result.exit_code == 0 and result.output.strip() == t("guard.cli.locked")
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "command")
        turkish = invoke(config, "status", client=client, env={"TAU_LANG": "tr"})
        assert turkish.output.splitlines()[0] == t(
            "guard.cli.state", "tr", state=t("guard.state.locked", "tr")
        )


def test_lock_without_a_hub_says_tau_is_locked_anyway(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    result = invoke(config, "lock")
    assert result.exit_code == 0 and result.output.strip() == t("guard.cli.lock_no_hub")


def test_status_of_a_hub_without_the_guard_service(tmp_path: Path) -> None:
    from tau_core.hub import ControlApi

    config = cli_config(tmp_path)
    api = ControlApi(0, lambda: {}, hub_dir=config.hub_dir)
    api.write_token()
    api.serve()
    try:
        client = HubClient(config.with_overrides(hub=HubConfig(control_port=api.port)))
        result = invoke(config, "status", client=client)
        assert result.exit_code == 1 and result.output.strip() == t("guard.cli.hub_off")
        result = invoke(config, "lock", client=client)
        assert result.exit_code == 1
    finally:
        api.shutdown()


def test_log_reads_the_audit_file(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    clock = FakeClock()
    audit = AuditLog(config.data_dir / "guard", now=clock.wall)
    audit.record("lock", trigger="startup")
    clock.advance(3600)
    audit.record("verify", channel="tui", client_id="c1", ok=False, reason="no_match", score=0.3)
    audit.record("cooldown", ok=False, reason="cooldown", duration_ms=30000)
    audit.record("verify", channel="tui", ok=False, reason="spoof", liveness="no_return")
    result = invoke(config, "log")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert len(lines) == 4
    assert t("guard.cli.log.event.lock") in lines[0] and t("guard.lock_trigger.startup") in lines[0]
    assert "no_match" in lines[1] and "tui" in lines[1] and "0.30" in lines[1]
    assert "30 s" in lines[2]
    assert "spoof (no_return)" in lines[3]  # which liveness rule failed
    raw = invoke(config, "log", "--json").output.splitlines()
    assert [json.loads(line)["event"] for line in raw] == ["lock", "verify", "cooldown", "verify"]
    since = clock.wall().isoformat()  # the hour of the last two entries
    recent = invoke(config, "log", "--json", "--since", since).output.splitlines()
    assert [json.loads(line)["event"] for line in recent] == ["verify", "cooldown", "verify"]


def test_log_when_empty_and_a_bad_since(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    assert invoke(config, "log").output.strip() == t("guard.cli.log.empty")
    result = invoke(config, "log", "--since", "last tuesday")
    assert result.exit_code == 2 and "--since" in result.output


def test_parse_since() -> None:
    now = FakeClock().wall()
    assert (now - parse_since("30m", now=now)).total_seconds() == 1800  # type: ignore[operator]
    assert (now - parse_since("2h", now=now)).total_seconds() == 7200  # type: ignore[operator]
    assert (now - parse_since("7d", now=now)).days == 7  # type: ignore[operator]
    assert parse_since("2026-09-30T10:00:00+00:00") == now.replace(hour=10)
    assert parse_since(None) is None


def test_entry_line_never_shows_more_than_the_schema() -> None:
    line = entry_line(
        {
            "v": 1,
            "at": "2026-09-30T12:00:00+00:00",
            "event": "step_up",
            "channel": "tui",
            "client_id": "c1",
            "trigger": None,
            "ok": True,
            "reason": "match",
            "duration_ms": 900,
            "tool": "lamp",
        },
        "en",
    )
    assert "step-up" in line and "ok" in line and "lamp" in line and "match" not in line


def test_log_lines_never_drive_the_terminal(tmp_path: Path) -> None:
    """Even a record written by hand (or by an older version) is printed inert."""
    config = cli_config(tmp_path)
    guard_dir = config.data_dir / "guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    forged = {
        "v": 1,
        "at": "2026-09-30T12:00:00+00:00",
        "event": "odd\x1b[31m",
        "channel": "tui\x1b]0;owned\x07\r30.09.2026 12:00:00  unlocked  ok",
        "client_id": "c1",
        "trigger": None,
        "ok": False,
        "reason": "no_match\x9b2J",
        "duration_ms": 1,
        "tool": "lamp\x1b[2K",
    }
    (guard_dir / "audit.jsonl").write_text(json.dumps(forged) + "\n", encoding="utf-8")
    line = entry_line(forged, "en")
    assert line.isprintable() and "owned" in line
    output = invoke(config, "log").output
    assert "\x1b" not in output and "\r" not in output and "\x9b" not in output
    raw = invoke(config, "log", "--json").output
    assert "\x1b" not in raw and "\x9b" not in raw and json.loads(raw)["tool"] == "lamp\x1b[2K"


@pytest.mark.parametrize("language", ["en", "tr"])
def test_the_status_labels_read_apart(language: str) -> None:
    labels = {
        t(key, language, trigger="x", reason="x").split(":")[0].strip()
        for key in ("guard.cli.trigger", "guard.cli.reason")
    }
    assert len(labels) == 2  # "why it is locked" and "why it is unavailable" never look alike
