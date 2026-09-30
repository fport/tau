"""The guard worker: ``python -m tau_guard.worker <op>``, one short-lived process per attempt.

Every camera, Keychain and LocalAuthentication operation runs here, never in the hub (ADR 0008
decision 2): a native crash cannot take the hub down, OpenCV and AVFoundation output never
reaches a terminal, cancelling is a kill, and the hub never holds a template or an embedding.

Protocol:

- ``op`` is one of :data:`OPS`: ``verify``, ``enroll``, ``touch_id`` and ``selftest`` (the hub
  and the CLI), and ``forget`` (the CLI only, ``tau guard forget``).
- The request is one JSON object on stdin (at most :data:`MAX_REQUEST` bytes):
  ``{"v": 1, "op", "kind", "attempt", "data_dir", "policy", "settings", "challenge_fresh",
  "add"?, "reason_text"?, "explain"?, "deep"?}``.
- Stdout carries JSON lines: any number of
  ``{"type": "progress", "step", "hint", "deadline"}`` (``step`` one of tau-core's
  ``PROGRESS_STEPS``, ``hint`` a verdict reason or ``null``, ``deadline`` UTC ISO or ``null``),
  then one ``{"type": "verdict", "ok", "reason", "method", "score"?, "liveness"?,
  "camera_ms"?}``. ``score`` is rounded to 2 decimals and only reaches the audit log;
  ``camera_ms`` says how long the camera was on (the audit's ``camera_open``). Every value has
  the documented type; anything else (a list where a string belongs) ends the run with
  ``error`` in the hub.
- A face success reports ``liveness``: ``challenge`` when the head-turn challenge passed,
  ``passive`` for a passive match. The worker picks the check from the request
  (:func:`tau_guard.verify.policy_for`); the hub turns a success the attempt's merged ``policy``
  excludes into ``error`` as a second line (see :mod:`tau_guard.state`).
- With ``"explain": true`` (only ``tau guard verify --explain``, never the hub) ``verify`` also
  writes one ``{"type": "explain", ...}`` line per frame with its numbers (detector score, eye
  distance, brightness, sharpness, yaw proxy, similarity). No frame is ever saved.
- Stderr goes to ``TAU_DATA_DIR/guard/worker.log`` (the caller opens it, 0600). It never gets
  an embedding or a frame, only what went wrong.
- The hub kills the worker on cancel, lock, timeout or hub stop: SIGTERM, then SIGKILL after
  1 s. SIGTERM raises :class:`Terminated` here, so every ``finally`` runs and the camera is
  released; the worker then exits without a verdict.

Operations:

- ``verify``: the settings and policy (:func:`~tau_guard.verify.policy_for`; a threshold below
  the 0.45 floor is ``error``), the template (read again every time: ``not_enrolled``,
  ``model_changed``, ``key_unavailable``, ``template_invalid``), the engine (SFace missing or
  changed: ``unavailable``), the camera, then the check (:func:`~tau_guard.verify.run_check`).
- ``enroll``: refused with ``SSH_CONNECTION`` set; the engine; whether it is the first
  enrollment (from the Keychain item, :func:`~tau_guard.store.first_enrollment`); with
  ``add`` the existing template; then LocalAuthentication (device owner, prompt text from
  ``reason_text``: ``touch_id_failed`` or ``touch_id_unavailable`` when it does not pass, and the
  camera stays off); then the guided capture (:mod:`tau_guard.enroll`); then the key (a new one
  only for a first enrollment), the encrypted template and the marker. The verdict carries
  ``first``.
- ``forget``: refused with ``SSH_CONNECTION`` set; LocalAuthentication; then the template,
  the marker and the key are removed (:func:`tau_guard.store.forget`). ``{"ok", "reason":
  null}`` on success.
- ``touch_id``: ``touch_id_unavailable`` until issue 114.
- ``selftest``: the platform and the imports, ``{"type": "verdict", "ok", "reason", "checks"}``
  (``reason`` is ``null`` when every check passed). With ``"deep": true`` (``tau guard
  doctor``) it adds ``details``: OpenCV's version, both model checksums, the Keychain item,
  whether the template decrypts, the camera device and the camera permission. It never opens a
  camera or shows a prompt.

The module imports nothing but the standard library at start, so the worker starts fast;
camera, pyobjc, keyring and cryptography imports happen inside the operations. Tests call
:func:`run` in-process with fakes (:class:`Deps`).
"""

from __future__ import annotations

import importlib
import json
import math
import os
import random
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

__all__ = ["MAX_REQUEST", "OPS", "Deps", "Terminated", "main", "run", "system_deps"]

OPS = ("verify", "enroll", "touch_id", "selftest", "forget")
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
WORKER_ENV = {"OPENCV_LOG_LEVEL": "ERROR", "OPENCV_AVFOUNDATION_SKIP_AUTH": "1"}
DEFAULT_REASON_TEXT = "confirm your identity for the tau guard"
MAX_REASON_TEXT = 200
Emit = Callable[[dict[str, Any]], None]


class Terminated(BaseException):  # noqa: N818 (a signal, not an error)
    """SIGTERM from the hub: unwinds every ``finally`` (the camera is released)."""


def _on_term(signum: int, frame: Any) -> None:
    raise Terminated()


def emit_line(out: TextIO, message: dict[str, Any]) -> None:
    out.write(json.dumps(message, separators=(",", ":")) + "\n")
    out.flush()


def verdict(ok: bool, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {"type": "verdict", "ok": ok, "reason": reason, "method": None, **extra}


def log(message: str) -> None:
    """One line for ``worker.log`` (stderr). Never pass an embedding or a frame."""
    print(f"tau-guard worker: {message}", file=sys.stderr, flush=True)


# -- dependencies --------------------------------------------------------------------------------


@dataclass
class Deps:
    """What the operations use. :func:`system_deps` builds the macOS ones; tests pass fakes."""

    platform: str
    source: Callable[[str], Any]
    """``camera`` setting → a :class:`~tau_guard.camera.FrameSource`."""
    engine: Callable[[Path], Any]
    """``data_dir`` → a :class:`~tau_guard.engine.FaceEngine` (raises ``ModelError``)."""
    keys: Any
    """A :class:`~tau_guard.store.KeyStore`."""
    local_auth: Any
    """A :class:`~tau_guard.localauth.LocalAuthFactor`."""
    rng: random.Random = field(default_factory=random.SystemRandom)
    clock: Callable[[], float] = time.monotonic
    wall: Callable[[], datetime] = lambda: datetime.now(UTC)
    devices: Callable[[], Any] | None = None
    """For ``selftest``: → a :class:`~tau_guard.camera.DeviceList`."""
    permission: Callable[[], Any] | None = None
    """For ``selftest``: → a :class:`~tau_guard.camera.Permission`."""


def system_deps() -> Deps:
    """The real camera, engine, Keychain and LocalAuthentication (constructed lazily)."""
    from tau_guard.camera import AVFoundationCamera, AVFoundationDevices, AVFoundationPermission
    from tau_guard.engine import OpenCvFaceEngine, sface_path
    from tau_guard.localauth import MacLocalAuth
    from tau_guard.store import KeychainKeyStore

    class _LazyLocalAuth:
        def authenticate(self, policy: str, reason: str, *, timeout: float = 60.0) -> str:
            try:
                factor = MacLocalAuth()
            except Exception as exc:
                log(f"LocalAuthentication is not available ({type(exc).__name__})")
                return "unavailable"
            return factor.authenticate(policy, reason, timeout=timeout)

    return Deps(
        platform=sys.platform,
        source=lambda camera: AVFoundationCamera(camera),
        engine=lambda data_dir: OpenCvFaceEngine(sface_path(data_dir)),
        keys=KeychainKeyStore(),
        local_auth=_LazyLocalAuth(),
        devices=AVFoundationDevices,
        permission=AVFoundationPermission,
    )


# -- helpers -------------------------------------------------------------------------------------


def _data_dir(request: dict[str, Any]) -> Path | None:
    value = request.get("data_dir")
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return None
    return Path(value)


def _enrolled(request: dict[str, Any]) -> bool:
    data_dir = _data_dir(request)
    return data_dir is not None and (data_dir / ENROLLED_MARKER).is_file()


def _settings(request: dict[str, Any]) -> dict[str, Any]:
    settings = request.get("settings")
    return settings if isinstance(settings, dict) else {}


def _camera_setting(request: dict[str, Any]) -> str:
    camera = _settings(request).get("camera", "builtin")
    return camera if isinstance(camera, str) and camera else "builtin"


def _reason_text(request: dict[str, Any]) -> str:
    text = request.get("reason_text")
    if isinstance(text, str) and 0 < len(text) <= MAX_REASON_TEXT and text.isprintable():
        return text
    return DEFAULT_REASON_TEXT


def _camera_ms(source: Any) -> dict[str, Any]:
    seconds = getattr(source, "open_seconds", None)
    if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds >= 0:
        return {"camera_ms": int(seconds * 1000)}
    return {}


def _score(value: float | None) -> dict[str, Any]:
    if value is None or not math.isfinite(value):
        return {}
    return {"score": round(float(value), 2)}


class _Progress:
    """Turns verify/enroll :class:`~tau_guard.verify.Progress` values into protocol lines
    (monotonic deadlines become UTC ISO times)."""

    def __init__(self, emit: Emit, deps: Deps) -> None:
        self.emit = emit
        self.deps = deps

    def step(self, step: str, hint: str | None = None, deadline: float | None = None) -> None:
        when = None
        if deadline is not None:
            moment = self.deps.wall() + timedelta(seconds=deadline - self.deps.clock())
            when = moment.astimezone(UTC).isoformat(timespec="milliseconds")
        self.emit({"type": "progress", "step": step, "hint": hint, "deadline": when})

    def __call__(self, progress: Any) -> None:
        self.step(progress.step, progress.hint, progress.deadline)


# -- operations ----------------------------------------------------------------------------------


def verify_op(request: dict[str, Any], deps: Deps, emit: Emit) -> dict[str, Any]:
    from tau_guard.camera import CameraError
    from tau_guard.engine import SFACE_SHA256, ModelError
    from tau_guard.store import StoreError, load_template
    from tau_guard.verify import PolicyError, policy_for, run_check

    data_dir = _data_dir(request)
    if data_dir is None:
        log("verify: the request has no absolute data_dir")
        return verdict(False, "error")
    try:
        policy = policy_for(request)
    except PolicyError as exc:
        log(f"verify: {exc}")
        return verdict(False, exc.reason)
    if not _enrolled(request):
        return verdict(False, "not_enrolled")
    guard_dir = data_dir / "guard"
    try:
        template = load_template(guard_dir, deps.keys, SFACE_SHA256)
    except StoreError as exc:
        log(f"verify: the template cannot be used ({exc.reason})")
        return verdict(False, exc.reason)
    try:
        engine = deps.engine(data_dir)
    except ModelError as exc:
        log(f"verify: {exc}")
        return verdict(False, "unavailable")
    progress = _Progress(emit, deps)
    progress.step("starting")
    source = deps.source(_camera_setting(request))
    explain = _explainer(emit) if request.get("explain") is True else None
    try:
        result = run_check(
            policy,
            template.vector,
            template.calibration,
            engine,
            source,
            rng=deps.rng,
            emit=progress,
            explain=explain,
        )
    except CameraError as exc:
        log(f"verify: camera: {exc}")
        return verdict(False, exc.reason, **_camera_ms(source))
    extra = {**_score(result.score), **_camera_ms(source)}
    if result.ok:
        return {**verdict(True, "match", **extra), "method": "face", "liveness": result.liveness}
    return verdict(False, result.reason, **extra)


def _explainer(emit: Emit) -> Callable[[Any, str, Any], None]:
    def explain(obs: Any, phase: str, machine: Any) -> None:
        face = obs.primary
        start = machine.start if machine.start is not None else obs.at
        emit(
            {
                "type": "explain",
                "phase": phase,
                "t": round(obs.at - start, 3),
                "faces": obs.faces,
                "score": _round(face.score if face else None, 3),
                "iod": _round(face.iod if face else None, 1),
                "brightness": _round(obs.brightness, 1),
                "sharpness": _round(obs.sharpness, 1),
                "yaw": _round(face.yaw if face else None, 3),
                "similarity": _round(obs.similarity, 3),
                "hint": obs.hint,
            }
        )

    return explain


def _round(value: float | None, digits: int) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _authenticate(request: dict[str, Any], deps: Deps) -> str | None:
    """LocalAuthentication with the device-owner policy (issue 114 adds biometrics-only);
    ``None`` when it passed, else the verdict reason."""
    from tau_guard.localauth import DEVICE_OWNER, LA_TIMEOUT, verdict_reason

    try:
        outcome = deps.local_auth.authenticate(
            DEVICE_OWNER, _reason_text(request), timeout=LA_TIMEOUT
        )
    except Exception as exc:  # a factor must not raise; fail closed if one does
        log(f"LocalAuthentication failed ({type(exc).__name__})")
        return "touch_id_failed"
    if outcome == "ok":
        return None
    log(f"LocalAuthentication did not pass ({outcome})")
    return verdict_reason(str(outcome))


def enroll_op(request: dict[str, Any], deps: Deps, emit: Emit) -> dict[str, Any]:
    import secrets

    from tau_guard.camera import CameraError
    from tau_guard.engine import SFACE_SHA256, ModelError
    from tau_guard.enroll import Enrollment, run_enrollment
    from tau_guard.store import (
        KeyUnavailable,
        StoreError,
        first_enrollment,
        load_template,
        new_key,
        save_enrollment,
        template_from,
    )

    data_dir = _data_dir(request)
    if data_dir is None:
        log("enroll: the request has no absolute data_dir")
        return verdict(False, "error")
    if os.environ.get("SSH_CONNECTION"):
        log("enroll: refused in a session started over SSH")
        return verdict(False, "unavailable")
    guard_dir = data_dir / "guard"
    try:
        engine = deps.engine(data_dir)
    except ModelError as exc:
        log(f"enroll: {exc}")
        return verdict(False, "unavailable")
    add = request.get("add") is True
    try:
        first = first_enrollment(deps.keys)
        existing = load_template(guard_dir, deps.keys, SFACE_SHA256) if add else None
    except StoreError as exc:
        log(f"enroll: {exc.reason}")
        return verdict(False, exc.reason)
    progress = _Progress(emit, deps)
    progress.step("touch_id")
    refused = _authenticate(request, deps)
    if refused is not None:
        return verdict(False, refused)
    progress.step("starting")
    machine = Enrollment(
        existing_vector=existing.vector if existing else None,
        existing_samples=existing.samples if existing else (),
        existing_calibration=existing.calibration if existing else None,
    )
    source = deps.source(_camera_setting(request))
    try:
        result = run_enrollment(engine, source, emit=progress, machine=machine)
    except CameraError as exc:
        log(f"enroll: camera: {exc}")
        return verdict(False, exc.reason, **_camera_ms(source))
    camera = _camera_ms(source)
    if not result.ok or result.calibration is None:
        log(f"enroll: the capture did not pass ({result.reason})")
        return verdict(False, result.reason, **camera)
    try:
        key = new_key() if first else deps.keys.get()
        if key is None:
            raise StoreError("key_unavailable", "the key disappeared during the enrollment")
        if first:
            deps.keys.set(key)
    except (KeyUnavailable, StoreError) as exc:
        log(f"enroll: the key cannot be stored ({type(exc).__name__})")
        return verdict(False, "key_unavailable", **camera)
    created = deps.wall().astimezone(UTC).isoformat(timespec="seconds")
    template = template_from(
        result.samples,
        enrollment=existing.enrollment if existing else secrets.token_hex(8),
        created=existing.created if existing else created,
        model_sha=SFACE_SHA256,
        calibration=result.calibration,
    )
    save_enrollment(guard_dir, template, key)
    extra = {**_score(result.consistency), **camera, "first": first}
    return {**verdict(True, "match", **extra), "method": "face"}


def forget_op(request: dict[str, Any], deps: Deps) -> dict[str, Any]:
    from tau_guard.store import StoreError, forget

    data_dir = _data_dir(request)
    if data_dir is None:
        log("forget: the request has no absolute data_dir")
        return verdict(False, "error")
    if os.environ.get("SSH_CONNECTION"):
        log("forget: refused in a session started over SSH")
        return verdict(False, "unavailable")
    refused = _authenticate(request, deps)
    if refused is not None:
        return verdict(False, refused)
    try:
        removed = forget(data_dir / "guard", deps.keys)
    except StoreError as exc:
        log(f"forget: {exc.reason}")
        return verdict(False, exc.reason)
    return verdict(True, None, removed=removed)


def selftest(
    platform: str | None = None,
    *,
    request: dict[str, Any] | None = None,
    deps: Deps | None = None,
) -> dict[str, Any]:
    """Platform and import checks (plus ``details`` when ``deep``); never opens a camera or a
    prompt."""
    platform = sys.platform if platform is None else platform
    checks: dict[str, bool] = {"platform": platform == "darwin"}
    for name in SELFTEST_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception:
            checks[name] = False
        else:
            checks[name] = True
    extra: dict[str, Any] = {"checks": checks}
    if request is not None and request.get("deep") is True and checks["platform"]:
        extra["details"] = _deep(request, deps or system_deps())
    if not checks["platform"]:
        return verdict(False, "unsupported_platform", **extra)
    if not all(checks.values()):
        return verdict(False, "unavailable", **extra)
    return verdict(True, None, **extra)


def _deep(request: dict[str, Any], deps: Deps) -> dict[str, Any]:
    from tau_guard.camera import VERIFIED_OPENCV, select_device
    from tau_guard.engine import (
        SFACE_SHA256,
        YUNET_SHA256,
        model_state,
        sface_path,
        vendored_yunet,
    )
    from tau_guard.store import KeyUnavailable, StoreError, load_template

    details: dict[str, Any] = {}
    try:
        cv2 = importlib.import_module("cv2")
        version = str(cv2.__version__)
    except Exception:
        version = None
    details["opencv"] = version
    details["opencv_verified"] = bool(version) and version.startswith(VERIFIED_OPENCV)
    details["yunet"] = model_state(vendored_yunet(), YUNET_SHA256)
    data_dir = _data_dir(request)
    details["sface"] = model_state(sface_path(data_dir), SFACE_SHA256) if data_dir else "missing"
    try:
        details["keychain"] = "ok" if deps.keys.get() is not None else "missing"
    except KeyUnavailable:
        details["keychain"] = "unavailable"
    if data_dir is None or not (data_dir / ENROLLED_MARKER).is_file():
        details["template"] = "not_enrolled"
    else:
        try:
            load_template(data_dir / "guard", deps.keys, SFACE_SHA256)
        except StoreError as exc:
            details["template"] = exc.reason
        else:
            details["template"] = "ok"
    camera: dict[str, Any] = {"device": None, "others": 0, "permission": None}
    try:
        listed = deps.devices().devices() if deps.devices is not None else []
        _, device = select_device(listed, _camera_setting(request))
        camera["device"] = device.name
        camera["others"] = len(listed) - 1
    except Exception as exc:
        camera["error"] = type(exc).__name__
    try:
        if deps.permission is not None:
            camera["permission"] = int(deps.permission().status())
    except Exception:
        camera["permission"] = None
    details["camera"] = camera
    return details


def run(
    op: str,
    request: dict[str, Any],
    *,
    deps: Deps | None = None,
    emit: Emit | None = None,
) -> dict[str, Any]:
    """The verdict of one operation; progress (and explain) lines go to ``emit``."""
    emit = emit or (lambda message: None)
    if op == "selftest":
        return selftest(request=request, deps=deps)
    if op == "touch_id":
        return verdict(False, "touch_id_unavailable")
    if op not in ("verify", "enroll", "forget"):
        return verdict(False, "error")
    platform = deps.platform if deps is not None else sys.platform
    if platform != "darwin":
        return verdict(False, "unsupported_platform")
    if op == "verify" and not _enrolled(request):
        return verdict(False, "not_enrolled" if _data_dir(request) else "error")
    deps = deps or system_deps()
    if op == "verify":
        return verify_op(request, deps, emit)
    if op == "enroll":
        return enroll_op(request, deps, emit)
    return forget_op(request, deps)


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    os.environ.update(WORKER_ENV)  # before anything can import cv2
    args = sys.argv[1:] if argv is None else argv
    out = sys.stdout
    source = sys.stdin if stdin is None else stdin
    op = args[0] if args else ""
    if op not in OPS:
        log(f"unknown operation {op!r}")
        emit_line(out, verdict(False, "error"))
        return 2
    try:
        raw = source.read(MAX_REQUEST + 1)
        request = json.loads(raw) if raw.strip() else {}
        if len(raw) > MAX_REQUEST or not isinstance(request, dict):
            raise ValueError("the request is not a JSON object within the size limit")
    except ValueError as exc:
        log(f"bad request: {exc}")
        emit_line(out, verdict(False, "error"))
        return 2
    previous = signal.signal(signal.SIGTERM, _on_term)
    try:
        answer = run(op, request, emit=lambda message: emit_line(out, message))
    except Terminated:
        log(f"{op} stopped by SIGTERM")
        return 143
    except Exception as exc:  # the traceback goes to worker.log only
        import traceback

        traceback.print_exc(file=sys.stderr)
        log(f"{op} failed: {type(exc).__name__}")
        answer = verdict(False, "error")
    finally:
        signal.signal(signal.SIGTERM, previous)
    emit_line(out, answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
