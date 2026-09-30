"""The worker run from the CLI: ``tau guard setup``, ``enroll``, ``verify``, ``forget`` and
``doctor`` when no hub with an active guard runs, and always for ``verify --explain``,
``forget`` and the doctor's self-test.

:func:`run_local` spawns ``python -P -m tau_guard.worker <op>`` like the hub does (the same
environment, stderr to ``guard/worker.log``, its own process group), writes the request, and
reads the answer with the hub's strict parser: progress lines go to ``on_progress``, explain
lines (numbers only) to ``on_explain``, and the verdict comes back as a validated dict. A
timeout or Ctrl-C stops the worker (SIGTERM, then SIGKILL after 1 s), so its ``finally``
releases the camera. The camera permission is then the terminal's, not the hub's.
"""

from __future__ import annotations

import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from tau_core.guard import VERDICT_REASONS

from tau_guard.audit import secure_dir
from tau_guard.runner import (
    DEFAULT_COMMAND,
    EXIT_GRACE,
    KILL_GRACE,
    MAX_LINE,
    Malformed,
    Progress,
    open_worker_log,
    parse_line,
    parse_local_auth,
    worker_env,
)

__all__ = ["EXPLAIN_KEYS", "LocalWorkerError", "Runner", "run_local", "validate_explain"]

MAX_LINES = 20000
"""An explain run writes one line per frame (at most 20 s at 30 fps, plus progress)."""
EXPLAIN_KEYS = (
    "phase",
    "t",
    "faces",
    "score",
    "iod",
    "brightness",
    "sharpness",
    "yaw",
    "similarity",
    "hint",
)
EXPLAIN_PHASES = ("look", "challenge", "after")
Runner = Callable[..., dict[str, Any]]
"""``runner(op, request, *, on_progress=None, on_explain=None, timeout) -> verdict dict``."""


class LocalWorkerError(Exception):
    """The worker did not answer properly (timeout, a broken line, no verdict)."""


def validate_explain(message: Mapping[str, Any]) -> dict[str, Any]:
    """An explain line with only its known keys, each a finite number, ``None`` or (for
    ``phase`` and ``hint``) one of the known words; raises :class:`Malformed`."""
    clean: dict[str, Any] = {}
    for key in EXPLAIN_KEYS:
        value = message.get(key)
        if key == "phase":
            if value not in EXPLAIN_PHASES:
                raise Malformed("unknown explain phase")
        elif key == "hint":
            if value is not None and value not in VERDICT_REASONS:
                raise Malformed("unknown explain hint")
        elif value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise Malformed(f"explain {key} must be a number")
        clean[key] = value
    return clean


def _verdict(op: str, message: dict[str, Any], raw: bytes) -> dict[str, Any]:
    """The verdict dict, checked like the hub checks it (``forget`` like ``selftest``)."""
    outcome = parse_line(raw, op="selftest" if op in ("selftest", "forget") else op)
    answer = dict(message)
    answer["ok"] = outcome.ok
    if op in ("selftest", "forget"):
        answer["reason"] = None if outcome.ok else outcome.reason
    if op == "forget":
        removed = message.get("removed")
        items = removed if isinstance(removed, list) else []
        answer["removed"] = [item for item in items if isinstance(item, str)]
    if "local_auth" in message:  # the selftest-style parse of forget does not look at it
        record = parse_local_auth(message.get("local_auth"))
        answer["local_auth"] = (
            None if record is None else dict(zip(("policy", "outcome", "ms"), record, strict=True))
        )
    return answer


def run_local(
    guard_dir: Path,
    op: str,
    request: Mapping[str, Any],
    *,
    on_progress: Callable[[Progress], None] | None = None,
    on_explain: Callable[[dict[str, Any]], None] | None = None,
    timeout: float,
    command: Sequence[str] = DEFAULT_COMMAND,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run one worker operation and return its verdict; raises :class:`LocalWorkerError`."""
    secure_dir(guard_dir)
    log_fd = open_worker_log(guard_dir)
    try:
        process = subprocess.Popen(
            [*command, op],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log_fd,
            env=worker_env(env),
            cwd=guard_dir,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise LocalWorkerError(f"the worker could not be started: {exc}") from exc
    finally:
        os.close(log_fd)
    lines: queue.Queue[bytes | None] = queue.Queue()

    def read() -> None:
        assert process.stdout is not None
        try:
            for raw in iter(lambda: process.stdout.readline(MAX_LINE + 1), b""):  # type: ignore[union-attr]
                lines.put(raw)
        except (OSError, ValueError):
            pass
        lines.put(None)

    grace = 0.0
    try:
        assert process.stdin is not None
        with suppress(OSError):
            process.stdin.write(json.dumps(dict(request)).encode("utf-8"))
            process.stdin.close()
        threading.Thread(target=read, name="tau-guard-local", daemon=True).start()
        deadline = time.monotonic() + timeout
        count = 0
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise LocalWorkerError(f"the worker did not answer within {timeout:g} s")
            try:
                raw = lines.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            if raw is None:
                raise LocalWorkerError("the worker ended without a verdict")
            count += 1
            if len(raw) > MAX_LINE or count > MAX_LINES:
                raise LocalWorkerError("the worker sent an oversized or endless answer")
            if not raw.strip():
                continue
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise LocalWorkerError("the worker sent a line that is not JSON") from exc
            if not isinstance(message, dict):
                raise LocalWorkerError("the worker sent a line that is not an object")
            try:
                if message.get("type") == "explain":
                    if on_explain is None:
                        raise Malformed("an explain line nobody asked for")
                    on_explain(validate_explain(message))
                    continue
                if message.get("type") == "verdict":
                    answer = _verdict(op, message, raw)
                    grace = EXIT_GRACE  # it releases the camera and exits on its own
                    return answer
                parsed = parse_line(raw, op=op)
            except Malformed as exc:
                raise LocalWorkerError(f"the worker broke the protocol: {exc}") from exc
            if isinstance(parsed, Progress) and on_progress is not None:
                on_progress(parsed)
    finally:
        _stop(process, grace)


def _stop(process: subprocess.Popen[bytes], grace: float) -> None:
    """Give the worker ``grace`` seconds to exit, then SIGTERM its process group, then
    SIGKILL after :data:`KILL_GRACE` seconds."""
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=grace)
    if process.poll() is None:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
    for stream in (process.stdout, process.stdin):
        if stream is not None:
            with suppress(OSError):
                stream.close()
