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
from tau_guard.runner import (
    KILL_GRACE,
    Malformed,
    Progress,
    WorkerRun,
    parse_line,
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


# -- the real worker (plumbing only in this slice) -----------------------------------------------


def test_verify_without_an_enrollment_answers_not_enrolled(tmp_path: Path) -> None:
    code, lines, _ = run_worker("verify", {"v": 1, "data_dir": str(tmp_path)})
    assert code == 0
    assert lines == [{"type": "verdict", "ok": False, "reason": "not_enrolled", "method": None}]


def test_verify_with_an_enrollment_but_no_engine_answers_unavailable(tmp_path: Path) -> None:
    (tmp_path / "guard").mkdir()
    (tmp_path / "guard" / "enrolled").write_text('{"v": 1, "enrollment": "E1"}')
    _, lines, _ = run_worker("verify", {"v": 1, "data_dir": str(tmp_path)})
    assert lines[-1]["reason"] == "unavailable" and lines[-1]["ok"] is False


@pytest.mark.parametrize(
    ("op", "reason"), [("enroll", "not_enrolled"), ("touch_id", "touch_id_unavailable")]
)
def test_other_operations_answer_until_their_issue(op: str, reason: str) -> None:
    _, lines, _ = run_worker(op, {"v": 1})
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
    ],
)
def test_malformed_lines(raw: bytes) -> None:
    with pytest.raises(Malformed):
        parse_line(raw)


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
