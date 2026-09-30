"""Test helpers for the guard: a fake clock, a fake presence source and a fake worker.

Nothing here opens a camera, a microphone, the Keychain or a Touch ID prompt.

- :class:`FakeClock`: ``advance(seconds)`` moves wall and monotonic time together;
  ``sleep(seconds)`` moves only the wall clock, as a Mac's monotonic clock stops while the
  machine sleeps.
- :class:`FakePresence`: a :class:`~tau_guard.presence.PresenceSource` whose ``idle_seconds``
  and ``screen_locked`` a test sets.
- The fake worker, ``python -m tau_guard.testing <script> <op>``, speaks the worker protocol
  from a JSON script file (see :func:`write_script`) and appends every request it gets, with
  its pid, to ``requests.jsonl`` next to the script. :func:`fake_worker_command` builds the
  ``worker_command`` for :class:`~tau_guard.service.GuardService`.

A script is a list of runs; each worker takes the first run and leaves the rest (the last run
stays for every later worker). A run is a list of steps:

- ``{"progress": "look", "hint": null, "deadline": null}``: one progress line;
- ``{"verdict": {...}}``: the verdict line (``type`` is added);
- ``{"sleep": 0.2}``; ``{"hang": true}`` (sleep for a long time);
- ``{"raw": "text"}``: a raw stdout line; ``{"stderr": "text"}``: a stderr line;
- ``{"ignore_term": true}``: ignore SIGTERM from here on; ``{"exit": 3}``: exit at once.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tau_guard.state import Reading

__all__ = [
    "FakeClock",
    "FakePresence",
    "fake_worker_command",
    "match",
    "read_requests",
    "write_script",
]

START = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """A clock that moves only when told to."""

    def __init__(self, start: datetime = START, monotonic: float = 1000.0) -> None:
        self._wall = start
        self._mono = monotonic

    def wall(self) -> datetime:
        return self._wall

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._wall += timedelta(seconds=seconds)
        self._mono += seconds

    def sleep(self, seconds: float) -> None:
        """The machine slept: wall time moves, monotonic time does not."""
        self._wall += timedelta(seconds=seconds)


class FakePresence:
    """Presence a test controls; ``None`` means unknown."""

    def __init__(self, idle_seconds: float | None = 0.0, screen_locked: bool | None = False):
        self.idle_seconds = idle_seconds
        self.screen_locked = screen_locked
        self.reads = 0

    def read(self) -> Reading:
        self.reads += 1
        return Reading(self.idle_seconds, self.screen_locked)


def match(method: str = "face", score: float = 0.71, liveness: str = "challenge") -> dict:
    """A passing verdict step."""
    return {
        "verdict": {
            "ok": True,
            "reason": "match",
            "method": method,
            "score": score,
            "liveness": liveness,
        }
    }


def write_script(path: Path, runs: Sequence[Sequence[dict[str, Any]]]) -> Path:
    """Write a fake-worker script (a list of runs) to ``path``."""
    path.write_text(json.dumps([list(run) for run in runs]), encoding="utf-8")
    return path


def read_requests(script: Path) -> list[dict[str, Any]]:
    """What the fake workers were asked, oldest first (``op``, ``pid``, ``request``)."""
    path = script.parent / "requests.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fake_worker_command(script: Path) -> list[str]:
    """``worker_command`` for a :class:`~tau_guard.service.GuardService` under test."""
    return [sys.executable, "-m", "tau_guard.testing", str(script)]


def _take_run(script: Path) -> list[dict[str, Any]]:
    try:
        runs = json.loads(script.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(runs, list) or not runs:
        return []
    run = runs[0]
    if len(runs) > 1:
        script.write_text(json.dumps(runs[1:]), encoding="utf-8")
    return run if isinstance(run, list) else []


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tau_guard.testing <script> <op>", file=sys.stderr)
        return 2
    script, op = Path(argv[0]), argv[1]
    request = json.loads(sys.stdin.read() or "{}")
    with open(script.parent / "requests.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps({"op": op, "pid": os.getpid(), "request": request}) + "\n")
    for step in _take_run(script):
        if "progress" in step:
            message = {
                "type": "progress",
                "step": step["progress"],
                "hint": step.get("hint"),
                "deadline": step.get("deadline"),
            }
            _say(json.dumps(message))
        elif "verdict" in step:
            _say(json.dumps({"type": "verdict", **step["verdict"]}))
        elif "sleep" in step:
            time.sleep(float(step["sleep"]))
        elif "hang" in step:
            time.sleep(3600)
        elif "raw" in step:
            _say(str(step["raw"]))
        elif "stderr" in step:
            print(step["stderr"], file=sys.stderr, flush=True)
        elif "ignore_term" in step:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        elif "exit" in step:
            return int(step["exit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
