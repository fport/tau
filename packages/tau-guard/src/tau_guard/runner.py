"""The hub's side of the worker protocol (see :mod:`tau_guard.worker`): spawn, read, kill.

:class:`WorkerRun` starts one worker for one attempt:

- the request JSON goes to stdin, which is then closed;
- stdout is read line by line in a dedicated daemon thread (never ``asyncio.to_thread``, whose
  executor is joined at shutdown, so ``tau hub stop`` is never delayed by a worker);
- stderr goes to ``worker.log`` (0600), never to the hub's stderr;
- each valid progress line calls ``on_progress``; the first valid verdict, or the reason the
  run failed, calls ``on_done`` exactly once;
- :meth:`WorkerRun.stop` (cancel, lock, hub stop) and the watchdog (timeout) send SIGTERM to
  the worker's process group, then SIGKILL after :data:`KILL_GRACE` seconds.

A malformed line, an unknown step or reason, a success without ``reason: "match"`` and a
``face`` or ``touch_id`` method, or an exit without a verdict all end the run with ``error``.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from tau_core.guard import PROGRESS_STEPS, VERDICT_REASONS

from tau_guard.state import Outcome

__all__ = [
    "DEFAULT_COMMAND",
    "KILL_GRACE",
    "Progress",
    "WorkerRun",
    "open_worker_log",
    "parse_line",
    "worker_env",
]

logger = logging.getLogger(__name__)

DEFAULT_COMMAND: tuple[str, ...] = (sys.executable, "-m", "tau_guard.worker")
KILL_GRACE = 1.0
"""Seconds between SIGTERM and SIGKILL."""
EXIT_GRACE = 1.0
"""Seconds a worker may take to exit on its own after its verdict."""
MAX_LINE = 8192
MAX_LINES = 2000
WORKER_LOG = "worker.log"
WORKER_LOG_MAX = 1024 * 1024
SUCCESS_METHODS = frozenset({"face", "touch_id"})
HUB_REASONS = frozenset({"cooldown", "locked", "busy", "cancelled"})
"""Verdict reasons only the hub decides; a worker that sends one is malformed."""
WORKER_REASONS = frozenset(VERDICT_REASONS) - HUB_REASONS
LIVENESS = frozenset({"challenge", "passive", "none"})
WORKER_ENV = {"OPENCV_LOG_LEVEL": "ERROR", "OPENCV_AVFOUNDATION_SKIP_AUTH": "1"}


class Malformed(ValueError):
    """A worker line that breaks the protocol."""


@dataclass(frozen=True)
class Progress:
    step: str
    hint: str | None
    deadline: datetime | None


def _deadline(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise Malformed("deadline must be an ISO time or null")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Malformed("deadline must be an ISO time or null") from exc
    if moment.tzinfo is None:
        raise Malformed("deadline must carry a time zone")
    return moment


def parse_line(raw: bytes, *, op: str = "verify") -> Progress | Outcome:
    """One stdout line → :class:`Progress` or a final :class:`Outcome`; raises
    :class:`Malformed`. Unknown keys are ignored and never passed on."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Malformed("not a JSON line") from exc
    if not isinstance(message, dict):
        raise Malformed("not a JSON object")
    kind = message.get("type")
    if kind == "progress":
        step = message.get("step")
        hint = message.get("hint")
        if step not in PROGRESS_STEPS:
            raise Malformed(f"unknown progress step {step!r}")
        if hint is not None and hint not in WORKER_REASONS:
            raise Malformed(f"unknown hint {hint!r}")
        return Progress(str(step), hint, _deadline(message.get("deadline")))
    if kind != "verdict":
        raise Malformed(f"unknown message type {kind!r}")
    ok = message.get("ok")
    reason = message.get("reason")
    method = message.get("method")
    if not isinstance(ok, bool):
        raise Malformed("verdict ok must be a bool")
    if op == "selftest":
        if ok and reason is not None:
            raise Malformed("a passing selftest has no reason")
        if not ok and reason not in WORKER_REASONS:
            raise Malformed(f"unknown reason {reason!r}")
        return Outcome(ok, reason or "match")
    if reason not in WORKER_REASONS:
        raise Malformed(f"unknown reason {reason!r}")
    if ok and (reason != "match" or method not in SUCCESS_METHODS):
        raise Malformed("a success needs reason 'match' and method 'face' or 'touch_id'")
    if not ok and reason == "match":
        raise Malformed("a failure cannot say 'match'")
    score = message.get("score")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise Malformed("score must be a number")
        score = round(float(score), 2)
    liveness = message.get("liveness")
    if liveness is not None and liveness not in LIVENESS:
        raise Malformed(f"unknown liveness {liveness!r}")
    return Outcome(ok, str(reason), method if ok else None, score, liveness)


def worker_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The worker's environment: the hub's plus the OpenCV quieting and auth switches."""
    env = dict(os.environ if base is None else base)
    env.update(WORKER_ENV)
    return env


def open_worker_log(directory: Path) -> int:
    """An append-only fd on ``directory/worker.log`` (0600); rotated once past 1 MiB."""
    path = directory / WORKER_LOG
    with suppress(OSError):
        if path.stat().st_size > WORKER_LOG_MAX:
            os.replace(path, directory / f"{WORKER_LOG}.1")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    return fd


class WorkerRun:
    """One worker process. ``on_progress(Progress)`` and ``on_done(Outcome)`` run in the
    reader (or watchdog) thread; ``on_done`` runs exactly once."""

    def __init__(
        self,
        op: str,
        request: Mapping[str, Any],
        *,
        command: Sequence[str] = DEFAULT_COMMAND,
        log_dir: Path,
        timeout: float,
        on_progress: Callable[[Progress], None],
        on_done: Callable[[Outcome], None],
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.op = op
        self.request = dict(request)
        self.command = [*command, op]
        self.log_dir = Path(log_dir)
        self.timeout = timeout
        self.on_progress = on_progress
        self.on_done = on_done
        self.env = worker_env(env)
        self.process: subprocess.Popen[bytes] | None = None
        self._finished_lock = threading.Lock()
        self._finished = False
        self._stopping: str | None = None
        self._reaper: threading.Thread | None = None
        self._reaper_lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    def start(self) -> None:
        """Spawn the worker and its reader and watchdog threads; a spawn failure ends the
        run with ``error`` (``on_done`` is called before this returns)."""
        try:
            log_fd = open_worker_log(self.log_dir)
        except OSError as exc:
            logger.error("guard: worker.log could not be opened: %s", exc)
            self._finish(Outcome(False, "error"))
            return
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log_fd,
                env=self.env,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            logger.error("guard: the worker could not be started: %s", exc)
            self._finish(Outcome(False, "error"))
            return
        finally:
            os.close(log_fd)
        threading.Thread(target=self._read, name="tau-guard-worker", daemon=True).start()
        threading.Thread(target=self._watch, name="tau-guard-watchdog", daemon=True).start()

    # -- stopping ---------------------------------------------------------------------------

    def stop(self, reason: str = "cancelled") -> None:
        """SIGTERM now, SIGKILL after :data:`KILL_GRACE` s (in a daemon thread); ``on_done``
        gets ``reason`` unless a verdict came first. Never blocks."""
        self._stopping = reason
        self._finish(Outcome(False, reason))
        self._terminate()

    def _terminate(self) -> None:
        with self._reaper_lock:
            if self.process is None or self._reaper is not None:
                return
            self._signal(signal.SIGTERM)
            self._reaper = threading.Thread(target=self._reap, name="tau-guard-reaper", daemon=True)
            self._reaper.start()

    def _reap(self) -> None:
        process = self.process
        assert process is not None
        try:
            process.wait(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            self._signal(signal.SIGKILL)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)

    def _signal(self, sig: signal.Signals) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            with suppress(OSError):
                process.send_signal(sig)

    def wait(self, timeout: float) -> bool:
        """Wait until the process is gone; ``True`` when it is."""
        process = self.process
        if process is None:
            return True
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # -- threads ----------------------------------------------------------------------------

    def _finish(self, outcome: Outcome) -> None:
        with self._finished_lock:
            if self._finished:
                return
            self._finished = True
        try:
            self.on_done(outcome)
        except Exception:
            logger.exception("guard: the worker verdict handler failed")

    def _watch(self) -> None:
        deadline = time.monotonic() + self.timeout
        while not self._finished:
            left = deadline - time.monotonic()
            if left <= 0:
                logger.warning("guard: a worker ran longer than %.0f s; stopping it", self.timeout)
                self.stop("timeout")
                return
            time.sleep(min(0.05, left))

    def _read(self) -> None:
        process = self.process
        assert process is not None and process.stdin is not None and process.stdout is not None
        try:
            payload = json.dumps(self.request).encode("utf-8")
            process.stdin.write(payload)
            process.stdin.close()
        except OSError:
            pass  # the worker died at once; its exit is handled below
        outcome = self._consume(process.stdout)
        if outcome is not None:
            self._finish(outcome)
            if process.poll() is None:
                try:
                    process.wait(timeout=EXIT_GRACE)
                except subprocess.TimeoutExpired:
                    self._terminate()
        else:
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=EXIT_GRACE)
            if self._stopping is None and not self._finished:
                logger.warning("guard: the worker ended without a verdict")
            self._finish(Outcome(False, "error"))
            if process.poll() is None:
                self._terminate()
        with suppress(OSError):
            process.stdout.close()

    def _consume(self, stream: IO[bytes]) -> Outcome | None:
        """Read progress lines until a verdict; ``None`` on EOF without one. A malformed line
        ends the run with ``error`` and stops the worker."""
        count = 0
        while not self._finished:
            try:
                raw = stream.readline(MAX_LINE + 1)
            except (OSError, ValueError):
                return None
            if not raw:
                return None
            count += 1
            if len(raw) > MAX_LINE or count > MAX_LINES:
                logger.warning("guard: the worker sent an oversized or endless answer")
                self._malformed()
                return Outcome(False, "error")
            if not raw.strip():
                continue
            try:
                message = parse_line(raw, op=self.op)
            except Malformed as exc:
                logger.warning("guard: the worker broke the protocol: %s", exc)
                self._malformed()
                return Outcome(False, "error")
            if isinstance(message, Outcome):
                return message
            try:
                self.on_progress(message)
            except Exception:
                logger.exception("guard: the worker progress handler failed")
        return None

    def _malformed(self) -> None:
        self._finish(Outcome(False, "error"))
        self._terminate()
