"""The worker protocol: the real ``python -m tau_guard.worker`` answers of this slice, and
``WorkerRun`` driving the fake worker (progress, verdicts, garbage, kills, stderr)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from tau_guard.liveness import FAILURES
from tau_guard.runner import (
    DEFAULT_COMMAND,
    KILL_GRACE,
    WORKER_ENV,
    Malformed,
    Progress,
    WorkerRun,
    parse_line,
    worker_env,
)
from tau_guard.state import Outcome
from tau_guard.testing import fake_worker_command, match, read_requests, write_script


def run_worker(op: str, request: dict[str, Any] | str) -> tuple[int, list[dict], str]:
    raw = request if isinstance(request, str) else json.dumps(request)
    done = subprocess.run(
        [sys.executable, "-m", "tau_guard.worker", op],
        input=raw,
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    return done.returncode, lines, done.stderr


# -- the real worker process (answers that need no camera, Keychain or prompt) ----------------
#
# Each request below stops before the worker would read the Keychain, show a prompt or open a
# camera: no template, no face model, or no data dir. The operations themselves are tested
# in-process with fakes in test_worker_ops.py.

VERIFY = {"v": 1, "kind": "unlock", "settings": {}, "policy": {}}


def test_verify_without_an_enrollment_answers_not_enrolled(tmp_path: Path) -> None:
    code, lines, _ = run_worker("verify", {**VERIFY, "data_dir": str(tmp_path)})
    assert code == 0
    expected = "not_enrolled" if sys.platform == "darwin" else "unsupported_platform"
    assert lines == [{"type": "verdict", "ok": False, "reason": expected, "method": None}]


@pytest.mark.skipif(sys.platform != "darwin", reason="the face check runs only on macOS")
def test_verify_with_a_marker_but_no_template_answers_not_enrolled(tmp_path: Path) -> None:
    (tmp_path / "guard").mkdir()
    (tmp_path / "guard" / "enrolled").write_text('{"v": 1, "enrollment": "E1"}')
    _, lines, _ = run_worker("verify", {**VERIFY, "data_dir": str(tmp_path)})
    assert lines[-1]["reason"] == "not_enrolled" and lines[-1]["ok"] is False


@pytest.mark.skipif(sys.platform != "darwin", reason="the face check runs only on macOS")
def test_enroll_without_the_face_model_answers_unavailable(tmp_path: Path) -> None:
    _, lines, stderr = run_worker("enroll", {"v": 1, "data_dir": str(tmp_path)})
    assert lines == [{"type": "verdict", "ok": False, "reason": "unavailable", "method": None}]
    assert "SFace" in stderr


@pytest.mark.parametrize(
    ("op", "reason"),
    [("enroll", "error"), ("forget", "error"), ("touch_id", "touch_id_unavailable")],
)
def test_operations_without_a_usable_request(op: str, reason: str) -> None:
    _, lines, _ = run_worker(op, {"v": 1})
    if sys.platform != "darwin" and op != "touch_id":
        reason = "unsupported_platform"
    assert lines == [{"type": "verdict", "ok": False, "reason": reason, "method": None}]


def test_unknown_operation_and_bad_request() -> None:
    code, lines, stderr = run_worker("peek", {})
    assert code == 2 and lines[-1]["reason"] == "error" and "unknown operation" in stderr
    code, lines, _ = run_worker("verify", "[1, 2]")
    assert code == 2 and lines[-1]["reason"] == "error"


def test_selftest_reports_the_platform_and_imports() -> None:
    _, lines, _ = run_worker("selftest", {})
    (answer,) = lines
    checks = answer["checks"]
    assert set(checks) >= {"platform", "numpy", "cv2", "cryptography", "Quartz"}
    if sys.platform != "darwin":
        assert answer["ok"] is False and answer["reason"] == "unsupported_platform"
    elif all(checks.values()):
        assert answer == {**answer, "ok": True, "reason": None}
    parse_line(json.dumps(answer).encode(), op="selftest")  # the hub accepts it


def test_the_worker_module_imports_only_the_standard_library() -> None:
    code = (
        "import sys, tau_guard.worker; "
        "bad = [m for m in ('tau_core', 'cv2', 'objc', 'Quartz', 'numpy') if m in sys.modules]; "
        "print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]"


# -- parse_line ----------------------------------------------------------------------------------


EMBEDDING = [round(0.0123 * i, 4) for i in range(1, 129)]
"""What a worker bug might put where a string belongs."""
FLOATS = [0.0123, 0.0246]


def line(message: Any) -> bytes:
    return json.dumps(message).encode()


def test_parse_progress_and_verdict() -> None:
    progress = parse_line(
        line(
            {
                "type": "progress",
                "step": "turn_left",
                "hint": "too_dark",
                "deadline": "2026-09-30T12:00:03+00:00",
                "extra": [1.0, 2.0],
            }
        )
    )
    assert isinstance(progress, Progress) and progress.step == "turn_left"
    assert progress.hint == "too_dark" and progress.deadline is not None
    verdict = parse_line(line({"type": "verdict", **match()["verdict"], "score": 0.7149}))
    assert verdict == Outcome(True, "match", "face", 0.71, "challenge")


@pytest.mark.parametrize("rule", FAILURES)
def test_a_spoof_carries_the_liveness_rule_that_failed(rule: str) -> None:
    message = {"type": "verdict", "ok": False, "reason": "spoof", "liveness": rule}
    verdict = parse_line(line(message))
    assert verdict == Outcome(False, "spoof", liveness=rule)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[1, 2]",
        line({"type": "progress", "step": "dance"}),
        line({"type": "progress", "step": "look", "hint": "sunny"}),
        line({"type": "progress", "step": "look", "deadline": "tomorrow"}),
        line({"type": "progress", "step": "look", "deadline": "2026-09-30T12:00:00"}),
        line({"type": "hello"}),
        line({"type": "verdict", "ok": "yes", "reason": "match", "method": "face"}),
        line({"type": "verdict", "ok": True, "reason": "match", "method": "voice"}),
        line({"type": "verdict", "ok": True, "reason": "no_match", "method": "face"}),
        line({"type": "verdict", "ok": False, "reason": "match"}),
        line({"type": "verdict", "ok": False, "reason": "unheard_of"}),
        line({"type": "verdict", "ok": False, "reason": "cooldown"}),  # the hub decides that
        line({"type": "verdict", "ok": False, "reason": "no_match", "score": "high"}),
        line({"type": "verdict", "ok": False, "reason": "no_match", "liveness": "vibes"}),
        # values of the wrong type never raise anything but Malformed (no TypeError)
        line({"type": "progress", "step": ["look"]}),
        line({"type": "progress", "step": "look", "hint": FLOATS}),
        line({"type": "progress", "step": "look", "hint": {"a": 1}}),
        line({"type": FLOATS}),
        line({"type": {"verdict": True}}),
        line({"type": "verdict", "ok": False, "reason": FLOATS}),
        line({"type": "verdict", "ok": False, "reason": {"no_match": 1}}),
        line({"type": "verdict", "ok": True, "reason": "match", "method": ["face"]}),
        line({"type": "verdict", "ok": True, "reason": "match", "method": {"face": 1}}),
        line({"type": "verdict", "ok": False, "reason": "no_match", "liveness": FLOATS}),
        line({"type": "verdict", "ok": False, "reason": "no_match", "liveness": {"a": 1}}),
        line({"type": "verdict", "ok": False, "reason": "no_match", "score": FLOATS}),
        b'{"type": "verdict", "ok": false, "reason": "no_match", "score": NaN}',
        b'{"type": "verdict", "ok": false, "reason": "no_match", "score": Infinity}',
        b'{"type": "verdict", "ok": false, "reason": "no_match", "score": 1' + b"0" * 400 + b"}",
        b"[" * 5000 + b"]" * 5000,
    ],
)
def test_malformed_lines(raw: bytes) -> None:
    with pytest.raises(Malformed):
        parse_line(raw)


@pytest.mark.parametrize(
    "message",
    [
        {"type": EMBEDDING},
        {"type": "verdict", "ok": False, "reason": str(EMBEDDING)},
        {"type": "verdict", "ok": False, "reason": "no_match", "liveness": str(EMBEDDING)},
        {"type": "progress", "step": str(EMBEDDING)},
        {"type": "verdict", "ok": False, "reason": EMBEDDING},
    ],
)
def test_malformed_messages_never_echo_worker_values(message: dict) -> None:
    with pytest.raises(Malformed) as caught:
        parse_line(line(message))
    assert "0.0123" not in str(caught.value) and len(str(caught.value)) < 100


# -- WorkerRun with the fake worker --------------------------------------------------------------


class Collector:
    def __init__(self) -> None:
        self.progress: list[Progress] = []
        self.outcomes: list[Outcome] = []
        self.done = threading.Event()

    def on_progress(self, progress: Progress) -> None:
        self.progress.append(progress)

    def on_done(self, outcome: Outcome) -> None:
        self.outcomes.append(outcome)
        self.done.set()


def start(tmp_path: Path, runs: list[list[dict]], *, timeout: float = 10.0) -> tuple:
    work = tmp_path / "worker"
    work.mkdir(exist_ok=True)
    script = write_script(work / "script.json", runs)
    collector = Collector()
    run = WorkerRun(
        "verify",
        {"v": 1, "kind": "unlock", "attempt": "a1"},
        command=fake_worker_command(script),
        log_dir=tmp_path,
        timeout=timeout,
        on_progress=collector.on_progress,
        on_done=collector.on_done,
    )
    run.start()
    return run, collector, script


def wait_for_pid(script: Path) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        requests = read_requests(script)
        if requests:
            return int(requests[-1]["pid"])
        time.sleep(0.02)
    raise AssertionError("the fake worker never started")


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_progress_then_verdict(tmp_path: Path) -> None:
    run, collector, script = start(
        tmp_path,
        [[{"progress": "look"}, {"progress": "turn_left", "hint": "too_dark"}, match()]],
    )
    assert collector.done.wait(10)
    assert [p.step for p in collector.progress] == ["look", "turn_left"]
    assert collector.outcomes == [Outcome(True, "match", "face", 0.71, "challenge")]
    assert read_requests(script)[0]["request"]["attempt"] == "a1"  # the request reached stdin
    assert run.wait(5)


def test_garbage_output_gives_error_and_stops_the_worker(tmp_path: Path) -> None:
    run, collector, script = start(tmp_path, [[{"raw": "garbage"}, {"hang": True}]])
    assert collector.done.wait(10)
    assert collector.outcomes == [Outcome(False, "error")]
    assert run.wait(5)


def test_exit_without_a_verdict_gives_error(tmp_path: Path) -> None:
    run, collector, _ = start(tmp_path, [[{"progress": "look"}, {"exit": 0}]])
    assert collector.done.wait(10)
    assert collector.outcomes == [Outcome(False, "error")]
    assert [p.step for p in collector.progress] == ["look"]


def test_a_crash_gives_error(tmp_path: Path) -> None:
    run, collector, _ = start(tmp_path, [[{"exit": 139}]])
    assert collector.done.wait(10) and collector.outcomes == [Outcome(False, "error")]


def test_stop_sends_sigterm_first(tmp_path: Path) -> None:
    run, collector, script = start(tmp_path, [[{"hang": True}]])
    pid = wait_for_pid(script)
    began = time.monotonic()
    run.stop("cancelled")
    assert collector.outcomes == [Outcome(False, "cancelled")]  # at once, before the exit
    assert run.wait(5)
    assert time.monotonic() - began < KILL_GRACE  # SIGTERM was enough
    assert gone(pid)


def test_stop_escalates_to_sigkill_after_one_second(tmp_path: Path) -> None:
    run, collector, script = start(tmp_path, [[{"ignore_term": True}, {"hang": True}]])
    pid = wait_for_pid(script)
    time.sleep(0.2)  # let it install the SIGTERM handler
    began = time.monotonic()
    run.stop("cancelled")
    time.sleep(0.5)
    assert not gone(pid)  # SIGTERM ignored, SIGKILL not yet
    assert run.wait(5)
    assert time.monotonic() - began >= KILL_GRACE
    assert gone(pid)


def test_timeout_stops_the_worker(tmp_path: Path) -> None:
    run, collector, script = start(tmp_path, [[{"hang": True}]], timeout=0.5)
    assert collector.done.wait(10)
    assert collector.outcomes == [Outcome(False, "timeout")]
    assert run.wait(5)


def test_on_done_runs_exactly_once(tmp_path: Path) -> None:
    run, collector, _ = start(tmp_path, [[match(), {"hang": True}]])
    assert collector.done.wait(10)
    run.stop("cancelled")
    run.stop("timeout")
    assert run.wait(5)
    assert collector.outcomes == [Outcome(True, "match", "face", 0.71, "challenge")]


def test_stderr_goes_to_worker_log_only(tmp_path: Path, capfd: pytest.CaptureFixture) -> None:
    run, collector, _ = start(tmp_path, [[{"stderr": "opencv noise"}, match()]])
    assert collector.done.wait(10) and run.wait(5)
    log = tmp_path / "worker.log"
    assert "opencv noise" in log.read_text()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    captured = capfd.readouterr()
    assert "opencv noise" not in captured.err and "opencv noise" not in captured.out


def test_a_missing_worker_binary_gives_error(tmp_path: Path) -> None:
    collector = Collector()
    run = WorkerRun(
        "verify",
        {},
        command=[str(tmp_path / "no-such-python")],
        log_dir=tmp_path,
        timeout=5,
        on_progress=collector.on_progress,
        on_done=collector.on_done,
    )
    run.start()
    assert collector.outcomes == [Outcome(False, "error")]


def raw_worker(tmp_path: Path, message: dict) -> list[str]:
    worker = tmp_path / "raw_worker.py"
    worker.write_text(
        f"import sys\nsys.stdin.read()\nprint({json.dumps(message)!r}, flush=True)\n"
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    return [sys.executable, str(worker)]


@pytest.mark.parametrize(
    "message",
    [
        {"type": "verdict", "ok": False, "reason": EMBEDDING},
        {"type": "progress", "step": "look", "hint": EMBEDDING},
        {"type": "verdict", "ok": False, "reason": "no_match", "liveness": {"a": 1}},
        {"type": "verdict", "ok": True, "reason": "match", "method": ["face"]},
        {"type": "verdict", "ok": False, "reason": str(EMBEDDING)},
    ],
)
def test_a_value_of_the_wrong_type_ends_the_run_with_error_at_once(
    tmp_path: Path, message: dict, caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    uncaught: list[BaseException | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: uncaught.append(args.exc_value))
    collector = Collector()
    began = time.monotonic()
    run = WorkerRun(
        "verify",
        {"v": 1},
        command=raw_worker(tmp_path, message),
        log_dir=tmp_path,
        timeout=20,
        on_progress=collector.on_progress,
        on_done=collector.on_done,
    )
    with caplog.at_level("DEBUG", logger="tau_guard"):
        run.start()
        assert collector.done.wait(10)
        assert run.wait(5)
    assert collector.outcomes == [Outcome(False, "error")]
    assert time.monotonic() - began < 5  # never left to the watchdog
    assert uncaught == []  # the reader thread did not die
    assert "0.0123" not in caplog.text  # the hub log names the field, never the value


def test_the_worker_runs_without_the_working_directory_on_its_path(
    tmp_path: Path, monkeypatch
) -> None:
    """A ``tau_guard`` directory where the hub was started cannot stand in for the worker."""
    shadow = tmp_path / "cwd" / "tau_guard"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    forged = {"type": "verdict", "ok": True, "reason": "match", "method": "face"}
    (shadow / "worker.py").write_text(f"print({json.dumps(forged)!r})\n", encoding="utf-8")
    monkeypatch.chdir(shadow.parent)
    monkeypatch.setenv("PYTHONPATH", str(shadow.parent))
    assert "-P" in DEFAULT_COMMAND and "PYTHONPATH" not in worker_env()
    hub = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/tmp/shadow",
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "KEYCHAIN_PATH": "/tmp/other.keychain",
    }
    assert worker_env(hub) == {"PATH": "/usr/bin", **WORKER_ENV}
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    collector = Collector()
    run = WorkerRun(
        "verify",
        {"v": 1, "data_dir": str(tmp_path / "data")},
        log_dir=guard_dir,
        timeout=30,
        on_progress=collector.on_progress,
        on_done=collector.on_done,
    )
    run.start()
    assert collector.done.wait(30) and run.wait(5)
    assert collector.outcomes == [Outcome(False, "not_enrolled")]  # the real worker answered
