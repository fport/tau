"""The guard worker: ``python -m tau_guard.worker <op>``, one short-lived process per attempt.

Every camera and LocalAuthentication operation runs here, never in the hub (ADR 0008 decision
2): a native crash cannot take the hub down, OpenCV and AVFoundation output never reaches a
terminal, cancelling is a kill, and the hub never holds a template or an embedding.

Protocol:

- ``op`` is one of :data:`OPS`: ``verify``, ``enroll``, ``touch_id`` or ``selftest``.
- The request is one JSON object on stdin (at most :data:`MAX_REQUEST` bytes):
  ``{"v": 1, "op", "kind", "attempt", "data_dir", "policy", "settings", "challenge_fresh"}``.
- Stdout carries JSON lines: any number of
  ``{"type": "progress", "step", "hint", "deadline"}`` (``step`` one of tau-core's
  ``PROGRESS_STEPS``, ``hint`` a verdict reason or ``null``, ``deadline`` UTC ISO or ``null``),
  then one ``{"type": "verdict", "ok", "reason", "method", "score"?, "liveness"?}``. ``score``
  is rounded to 2 decimals and only reaches the audit log. Every value has the documented
  type; anything else (a list where a string belongs) ends the run with ``error``.
- A face success reports ``liveness``: ``challenge`` when the head-turn challenge passed,
  ``passive`` for a passive match. The hub turns a success the attempt's merged ``policy``
  excludes into ``error`` (see :mod:`tau_guard.state`): an unlock needs ``challenge`` unless
  ``unlock_liveness`` is ``none``; a step-up needs ``challenge`` unless ``challenge_fresh``
  (then ``passive`` is enough) and its method must fit ``step_up``; ``touch_id`` needs
  ``unlock_fallback`` other than ``none`` for an unlock or a recheck.
- Stderr goes to ``TAU_DATA_DIR/guard/worker.log`` (the hub opens it, 0600).
- The hub kills the worker on cancel, lock, timeout or hub stop: SIGTERM, then SIGKILL after
  1 s.

This slice has the plumbing only. ``selftest`` checks the platform and the imports and answers
``{"type": "verdict", "ok", "reason", "checks"}`` (``reason`` is ``null`` when every check
passed). ``verify`` answers ``not_enrolled`` without an enrollment marker and ``unavailable``
with one (the face engine and the camera come with issue 112); ``enroll`` answers
``not_enrolled`` and ``touch_id`` answers ``touch_id_unavailable`` (issue 114).

The module imports nothing but the standard library at start, so the worker starts fast;
camera and pyobjc imports happen inside the operations.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, TextIO

__all__ = ["MAX_REQUEST", "OPS", "main", "run"]

OPS = ("verify", "enroll", "touch_id", "selftest")
MAX_REQUEST = 64 * 1024
ENROLLED_MARKER = "guard/enrolled"
"""Relative to ``data_dir``; the same path as ``tau_core.guard.ENROLLED_MARKER``."""
SELFTEST_IMPORTS = (
    "numpy",
    "cv2",
    "cryptography",
    "keyring",
    "Quartz",
    "AVFoundation",
    "LocalAuthentication",
)


def emit(out: TextIO, message: dict[str, Any]) -> None:
    out.write(json.dumps(message, separators=(",", ":")) + "\n")
    out.flush()


def verdict(ok: bool, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {"type": "verdict", "ok": ok, "reason": reason, "method": None, **extra}


def _enrolled(request: dict[str, Any]) -> bool:
    data_dir = request.get("data_dir")
    return isinstance(data_dir, str) and (Path(data_dir) / ENROLLED_MARKER).is_file()


def selftest(platform: str | None = None) -> dict[str, Any]:
    """Platform and import checks; never opens a camera or a prompt."""
    platform = sys.platform if platform is None else platform
    checks: dict[str, bool] = {"platform": platform == "darwin"}
    for name in SELFTEST_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception:
            checks[name] = False
        else:
            checks[name] = True
    if not checks["platform"]:
        return verdict(False, "unsupported_platform", checks=checks)
    if not all(checks.values()):
        return verdict(False, "unavailable", checks=checks)
    return verdict(True, None, checks=checks)


def run(op: str, request: dict[str, Any]) -> dict[str, Any]:
    """The verdict of one operation (this slice: the plumbing answers)."""
    if op == "selftest":
        return selftest()
    if op == "verify":
        return verdict(False, "unavailable" if _enrolled(request) else "not_enrolled")
    if op == "enroll":
        return verdict(False, "not_enrolled")
    if op == "touch_id":
        return verdict(False, "touch_id_unavailable")
    return verdict(False, "error")


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = sys.stdout
    source = sys.stdin if stdin is None else stdin
    op = args[0] if args else ""
    if op not in OPS:
        print(f"tau-guard worker: unknown operation {op!r}", file=sys.stderr)
        emit(out, verdict(False, "error"))
        return 2
    try:
        raw = source.read(MAX_REQUEST + 1)
        request = json.loads(raw) if raw.strip() else {}
        if len(raw) > MAX_REQUEST or not isinstance(request, dict):
            raise ValueError("the request is not a JSON object within the size limit")
    except ValueError as exc:
        print(f"tau-guard worker: bad request: {exc}", file=sys.stderr)
        emit(out, verdict(False, "error"))
        return 2
    try:
        answer = run(op, request)
    except Exception as exc:  # the traceback goes to worker.log only
        import traceback

        traceback.print_exc(file=sys.stderr)
        print(f"tau-guard worker: {op} failed: {exc}", file=sys.stderr)
        answer = verdict(False, "error")
    emit(out, answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
