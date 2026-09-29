"""Single-instance lock: one hub per machine, and a dead holder never blocks the next start."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from tau_core import Config
from tau_core.cli import cli
from tau_core.hub import AlreadyRunning, Hub, HubLock

# Exit 0 = acquired, 3 = AlreadyRunning (message on stdout).
ACQUIRE = """\
import sys
from pathlib import Path
from tau_core.hub import AlreadyRunning, HubLock
try:
    HubLock(Path(sys.argv[1])).acquire()
except AlreadyRunning as exc:
    print(exc)
    sys.exit(3)
"""

HOLD = """\
import sys, time
from pathlib import Path
from tau_core.hub import HubLock
HubLock(Path(sys.argv[1])).acquire()
print("held", flush=True)
time.sleep(60)
"""


def _acquire_in_subprocess(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", ACQUIRE, str(path)], capture_output=True, text=True, timeout=60
    )


def test_second_acquisition_in_a_subprocess_fails(tmp_path: Path) -> None:
    path = tmp_path / "hub" / "hub.lock"
    lock = HubLock(path)
    lock.acquire()
    try:
        result = _acquire_in_subprocess(path)
        assert result.returncode == 3, result.stderr
        assert result.stdout.strip() == (
            f"tau hub zaten çalışıyor (pid {os.getpid()}). Aynı makinede tek hub çalışabilir."
        )
    finally:
        lock.release()
    assert _acquire_in_subprocess(path).returncode == 0


def test_lock_file_holds_the_pid_and_probe_sees_it(tmp_path: Path) -> None:
    path = tmp_path / "hub.lock"
    assert HubLock.probe(path) == (False, None)
    with HubLock(path) as lock:
        assert lock.held
        assert path.read_text().strip() == str(os.getpid())
        assert HubLock.probe(path) == (True, os.getpid())
    assert not lock.held
    assert HubLock.probe(path) == (False, None)
    assert path.exists()  # never deleted


def test_second_acquisition_in_the_same_process_fails(tmp_path: Path) -> None:
    path = tmp_path / "hub.lock"
    with HubLock(path):
        with pytest.raises(AlreadyRunning) as info:
            HubLock(path).acquire()
    assert info.value.pid == os.getpid()


def test_kill_9_releases_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "hub.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        assert HubLock.probe(path) == (True, holder.pid)
        os.kill(holder.pid, signal.SIGKILL)
        holder.wait(timeout=30)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()
    deadline = time.monotonic() + 5
    while HubLock.probe(path)[0] and time.monotonic() < deadline:
        time.sleep(0.05)
    with HubLock(path) as lock:
        assert lock.held


def test_hub_run_raises_already_running(config: Config) -> None:
    with HubLock(config.hub_dir / "hub.lock"):
        with pytest.raises(AlreadyRunning):
            Hub(config).run()
    assert not (config.hub_dir / "state.json").exists()


def test_tau_hub_run_refuses_a_second_hub(config: Config, tmp_path: Path) -> None:
    env = {
        "TAU_HOME": str(config.home),
        "TAU_DATA_DIR": str(config.data_dir),
        "TAU_PROFILE": None,
        "TAU_ROLE": None,
        "TAU_HUB_PORT": None,
    }
    with HubLock(config.hub_dir / "hub.lock"):
        result = CliRunner().invoke(cli, ["hub", "run"], env=env)
    assert result.exit_code == 1
    assert (
        f"tau hub zaten çalışıyor (pid {os.getpid()}). Aynı makinede tek hub çalışabilir."
        in result.output
    )
    assert "Traceback" not in result.output
