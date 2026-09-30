"""A hub start is always locked, including after ``kill -9`` of the previous hub (a real hub
process, the real reflex loop, ``HubGuard`` as the client)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from guard_helpers import TURN, until, until_async, write_marker
from tau_core import GuardVerdict, HubGuard
from tau_core.config import HubConfig
from tau_core.testing import test_config
from tau_guard.testing import match, write_script

HUB = Path(__file__).parent / "hub_process.py"


def start_hub(tmp_path: Path, script: Path, name: str) -> tuple[subprocess.Popen, int]:
    port_file = tmp_path / f"{name}.port"
    process = subprocess.Popen(
        [sys.executable, str(HUB), str(tmp_path), str(script), str(port_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    until(lambda: port_file.exists() and port_file.read_text().strip() != "", timeout=60)
    return process, int(port_file.read_text())


async def test_a_hub_start_after_kill_9_is_locked(tmp_path: Path) -> None:
    config = test_config(tmp_path, component_tables={"guard": {"enabled": True}})
    write_marker(config)
    work = tmp_path / "worker"
    work.mkdir()
    script = write_script(work / "script.json", [[match()]])
    first, port = start_hub(tmp_path, script, "first")
    try:
        guard = HubGuard(config.with_overrides(hub=HubConfig(control_port=port)))
        await until_async(lambda: (config.hub_dir / "control.token").exists())
        assert await guard.unlock(channel="tui", client_id="c1") == GuardVerdict(
            True, "match", "face"
        )
        assert (await guard.admit(TURN)).allowed
    finally:
        os.kill(first.pid, signal.SIGKILL)
        first.wait(10)
    second, port = start_hub(tmp_path, script, "second")
    try:
        guard = HubGuard(config.with_overrides(hub=HubConfig(control_port=port)))
        status = await guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "startup")
        assert (await guard.admit(TURN)).reason == "locked"
    finally:
        second.send_signal(signal.SIGTERM)
        assert second.wait(15) == 0
