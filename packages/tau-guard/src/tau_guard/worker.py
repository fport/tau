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
  an embedding or a frame, only what went wrong: an unexpected exception is logged as its type
  and traceback frames, never its message, which could quote a value.
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
  ``add`` the existing template; the camera permission and device (``permission_pending``,
  ``camera_denied``, ``camera_unavailable`` before any prompt); then LocalAuthentication with
  the prompt text from ``reason_text`` (:func:`admin_policy`: the device-owner policy for a
  first enrollment, else Touch ID only with the pinned fingerprint set when the Mac has Touch
  ID, ``touch_id_unavailable`` when it cannot be used now, the device-owner policy on a Mac
  without it; ``touch_id_failed`` or ``touch_id_unavailable`` when it does not pass, and the
  camera stays off); then the guided capture (:mod:`tau_guard.enroll`); then the key (a new one
  only for a first enrollment, read back before anything is written: a key store that drops
  writes is ``key_unavailable``), the encrypted template (with the fingerprint set pinned when
  Touch ID is available) and the marker. The verdict carries ``first``.
- ``forget``: refused with ``SSH_CONNECTION`` set; LocalAuthentication as for a re-enrollment;
  then the template, the marker and the key are removed (:func:`tau_guard.store.forget`).
  ``{"ok", "reason": null, "removed"}`` on success; when the key cannot be removed the answer
  is ``ok: false`` (``key_unavailable``) and ``removed`` still lists what went.
- ``touch_id`` (issue 114): the Touch ID unlock fallback (``kind`` ``unlock`` or ``recheck``:
  ``unlock_fallback = "touch_id"`` is Touch ID only with the pinned fingerprint set,
  ``touch_id_or_password`` the device-owner policy) and the ``step_up = "touch_id"`` step-up
  (Touch ID only, pinned). It never opens the camera. The template must decrypt for either
  policy (``key_unavailable``, ``template_invalid``, ...). An enrollment without a pinned set
  gives ``touch_id_failed`` for Touch ID only; ``touch_id_unavailable`` when the lid is
  closed, there is no sensor or the policy cannot be evaluated. A success is ``method:
  "touch_id"``.
- ``verify`` for a step-up with ``step_up = "face_or_touch_id"``: when the face check fails
  for a reason that does not count (:data:`TOUCH_ID_AFTER`: ``too_dark``, ``no_face``, a
  ``camera_*`` verdict, ...), the camera is released and Touch ID (pinned) is asked instead.
- Every verdict that followed a LocalAuthentication prompt (or its refusal before the prompt)
  carries ``local_auth: {"policy", "outcome", "ms"}``, from which the hub writes the ``touch_id``
  audit record. Every prompt's ``LAContext`` is invalidated after 30 s and at once on SIGTERM
  (:mod:`tau_guard.localauth`).
- ``selftest``: the platform and the imports, ``{"type": "verdict", "ok", "reason", "checks"}``
  (``reason`` is ``null`` when every check passed). With ``"deep": true`` (``tau guard
  doctor``) it adds ``details``: OpenCV's version, both model checksums, the Keychain item
  (``ok``, ``missing``, ``invalid`` or ``unavailable``), whether the template decrypts, the
  camera device, the camera permission and Touch ID (``touch_id``: its state and why, the lid,
  and whether the fingerprint set is the pinned one: ``ok``, ``changed``, ``not_pinned`` or
  ``unknown``). It never opens a camera or shows a LocalAuthentication prompt; reading the
  Keychain may bring up macOS's Keychain access prompt (after a Python upgrade changed the
  interpreter), which the doctor explains.

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
TOUCH_ID_AFTER = frozenset(
    {
        "no_face",
        "timeout",
        "too_dark",
        "face_too_small",
        "camera_busy",
        "camera_unavailable",
        "camera_denied",
        "permission_pending",
    }
)
"""Face verdicts after which a ``face_or_touch_id`` step-up asks Touch ID: the face check could
not work. A counted failure (``no_match``, ``spoof``, ``multiple_faces``) never does."""
FALLBACK_POLICIES = {"touch_id": "biometrics", "touch_id_or_password": "device_owner"}
"""``unlock_fallback`` → the LocalAuthentication policy of the Touch ID unlock and recheck."""
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
    """For ``selftest`` and the enrollment's early camera check: → a
    :class:`~tau_guard.camera.DeviceList`."""
    permission: Callable[[], Any] | None = None
    """For ``selftest`` and the enrollment's early camera check: → a
    :class:`~tau_guard.camera.Permission`."""


def system_deps(op: str = "verify") -> Deps:
    """The real camera, engine, Keychain and LocalAuthentication (constructed lazily). An
    enrollment and ``forget`` run with the owner at the Mac, so their Keychain calls may wait
    for macOS's access prompt (:data:`~tau_guard.store.KEY_TIMEOUT_AT_MAC`)."""
    from tau_guard.camera import AVFoundationCamera, AVFoundationDevices, AVFoundationPermission
    from tau_guard.engine import OpenCvFaceEngine, sface_path
    from tau_guard.localauth import LA_TIMEOUT, Biometry, MacLocalAuth
    from tau_guard.store import KEY_TIMEOUT, KEY_TIMEOUT_AT_MAC, KeychainKeyStore

    class _LazyLocalAuth:
        def _factor(self) -> MacLocalAuth | None:
            try:
                return MacLocalAuth()
            except Exception as exc:
                log(f"LocalAuthentication is not available ({type(exc).__name__})")
                return None

        def biometry(self) -> Biometry:
            factor = self._factor()
            return factor.biometry() if factor is not None else Biometry("unavailable", "error")

        def authenticate(
            self,
            policy: str,
            reason: str,
            *,
            timeout: float = LA_TIMEOUT,
            domain_state: str | None = None,
        ) -> str:
            factor = self._factor()
            if factor is None:
                return "unavailable"
            return factor.authenticate(policy, reason, timeout=timeout, domain_state=domain_state)

    return Deps(
        platform=sys.platform,
        source=lambda camera: AVFoundationCamera(camera),
        engine=lambda data_dir: OpenCvFaceEngine(sface_path(data_dir)),
        keys=KeychainKeyStore(
            timeout=KEY_TIMEOUT_AT_MAC if op in ("enroll", "forget") else KEY_TIMEOUT
        ),
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
        if _touch_id_after(request, exc.reason):
            return _step_up_touch_id(request, deps, progress, template.domain_state, source)
        return verdict(False, exc.reason, **_camera_ms(source))
    extra = {**_score(result.score), **_camera_ms(source)}
    if result.ok:
        return {**verdict(True, "match", **extra), "method": "face", "liveness": result.liveness}
    if _touch_id_after(request, result.reason):
        return _step_up_touch_id(request, deps, progress, template.domain_state, source)
    return verdict(False, result.reason, **extra)


def _touch_id_after(request: dict[str, Any], reason: str | None) -> bool:
    """A ``face_or_touch_id`` step-up whose face check could not work (not a counted failure)."""
    policy = request.get("policy")
    mode = policy.get("step_up") if isinstance(policy, dict) else None
    return (
        request.get("kind") == "step_up"
        and mode == "face_or_touch_id"
        and (reason in TOUCH_ID_AFTER)
    )


def _step_up_touch_id(
    request: dict[str, Any], deps: Deps, progress: _Progress, pin: str | None, source: Any
) -> dict[str, Any]:
    """The Touch ID half of a ``face_or_touch_id`` step-up (the camera is already released)."""
    from tau_guard.localauth import BIOMETRICS

    camera = _camera_ms(source)
    if pin is None:
        log("step-up: the enrollment pinned no Touch ID fingerprint set; enroll again")
        return verdict(False, "touch_id_failed", **camera)
    progress.step("touch_id")
    refused, auth = _authenticate(request, deps, BIOMETRICS, pin=pin)
    if refused is not None:
        return verdict(False, refused, **camera, **auth)
    return {**verdict(True, "match", **camera, **auth), "method": "touch_id"}


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


def _authenticate(
    request: dict[str, Any], deps: Deps, policy: str, *, pin: str | None = None
) -> tuple[str | None, dict[str, Any]]:
    """LocalAuthentication with ``policy`` (Touch ID only checks the pinned fingerprint set
    ``pin``): ``(None, extra)`` when it passed, else ``(verdict reason, extra)``; ``extra``
    holds the ``local_auth`` record."""
    from tau_guard.localauth import LA_TIMEOUT, OUTCOMES, verdict_reason

    started = deps.clock()
    try:
        outcome = deps.local_auth.authenticate(
            policy, _reason_text(request), timeout=LA_TIMEOUT, domain_state=pin
        )
    except Exception as exc:  # a factor must not raise; fail closed if one does
        log(f"LocalAuthentication failed ({type(exc).__name__})")
        outcome = "failed"
    if outcome not in OUTCOMES:
        log("LocalAuthentication answered something unknown; refusing")
        outcome = "failed"
    extra = _local_auth(policy, str(outcome), started, deps)
    if outcome == "ok":
        return None, extra
    if outcome == "changed":
        log("LocalAuthentication: the Touch ID fingerprint set is not the one pinned at enrollment")
    else:
        log(f"LocalAuthentication did not pass ({outcome})")
    return verdict_reason(str(outcome)), extra


def _local_auth(policy: str, outcome: str, started: float | None, deps: Deps) -> dict[str, Any]:
    """The ``local_auth`` field of a verdict (policy, outcome, how long the prompt took)."""
    ms = 0 if started is None else max(0, int((deps.clock() - started) * 1000))
    return {"local_auth": {"policy": policy, "outcome": outcome, "ms": ms}}


def _biometry(deps: Deps) -> Any:
    """Touch ID's state from the factor (``unavailable`` when it breaks its contract)."""
    from tau_guard.localauth import BIOMETRY_STATES, Biometry

    try:
        biometry = deps.local_auth.biometry()
    except Exception as exc:
        log(f"Touch ID's state cannot be read ({type(exc).__name__})")
        return Biometry("unavailable", "error")
    if getattr(biometry, "state", None) not in BIOMETRY_STATES:
        return Biometry("unavailable", "error")
    return biometry


def admin_policy(deps: Deps, *, first: bool) -> tuple[str | None, str | None]:
    """``(policy, None)`` for authorising an enrollment or ``forget``, or ``(None, reason)``.

    A first enrollment uses the device-owner policy (Touch ID or the Mac password). Otherwise a
    Mac with Touch ID uses Touch ID only (with the pinned fingerprint set) and refuses with
    ``touch_id_unavailable`` while it cannot be used (a closed lid, a disconnected keyboard, a
    lockout); a Mac without Touch ID uses the device-owner policy."""
    from tau_guard.localauth import BIOMETRICS, DEVICE_OWNER

    if first:
        return DEVICE_OWNER, None
    biometry = _biometry(deps)
    if biometry.state == "available":
        return BIOMETRICS, None
    if biometry.state == "unavailable":
        log(f"Touch ID exists but cannot be used now ({biometry.detail})")
        return None, "touch_id_unavailable"
    return DEVICE_OWNER, None


def _admin_authenticate(
    request: dict[str, Any], deps: Deps, *, first: bool, pin: str | None
) -> tuple[str | None, dict[str, Any]]:
    """LocalAuthentication for an enrollment or ``forget`` (:func:`admin_policy`)."""
    from tau_guard.localauth import BIOMETRICS

    policy, refusal = admin_policy(deps, first=first)
    if policy is None:
        return refusal, _local_auth(BIOMETRICS, "unavailable", None, deps)
    return _authenticate(request, deps, policy, pin=pin if policy == BIOMETRICS else None)


def _stored_pin(guard_dir: Path, deps: Deps) -> str | None:
    """The pinned fingerprint set, ``None`` when there is none or it cannot be read (then a
    Touch ID authorisation cannot compare it)."""
    from tau_guard.store import StoreError, read_pin

    try:
        return read_pin(guard_dir, deps.keys)
    except StoreError as exc:
        log(f"the pinned Touch ID fingerprint set cannot be read ({exc.reason})")
        return None


def _current_pin(deps: Deps) -> str | None:
    """The fingerprint set to pin now: Touch ID's, when it is available."""
    biometry = _biometry(deps)
    return biometry.domain_state if biometry.state == "available" else None


def _camera_ready(request: dict[str, Any], deps: Deps) -> str | None:
    """The camera permission and the device, checked before LocalAuthentication, so the owner
    never authenticates only to hear that the camera is not allowed (``permission_pending``
    asks macOS for access); ``None`` when both are fine."""
    from tau_guard.camera import CameraError, check_permission, select_device

    try:
        if deps.permission is not None:
            check_permission(deps.permission())
        if deps.devices is not None:
            select_device(deps.devices().devices(), _camera_setting(request))
    except CameraError as exc:
        log(f"enroll: camera: {exc}")
        return exc.reason
    except Exception as exc:  # pyobjc missing or failing: the camera cannot be used either
        log(f"enroll: the camera cannot be checked ({type(exc).__name__})")
        return "camera_unavailable"
    return None


def enroll_op(request: dict[str, Any], deps: Deps, emit: Emit) -> dict[str, Any]:
    import hmac
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
    pin = None if first else _stored_pin(guard_dir, deps)
    camera_refused = _camera_ready(request, deps)
    if camera_refused is not None:
        return verdict(False, camera_refused)
    progress = _Progress(emit, deps)
    progress.step("touch_id")
    refused, auth = _admin_authenticate(request, deps, first=first, pin=pin)
    if refused is not None:
        return verdict(False, refused, **auth)
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
        return verdict(False, exc.reason, **_camera_ms(source), **auth)
    camera = {**_camera_ms(source), **auth}
    if not result.ok or result.calibration is None:
        log(f"enroll: the capture did not pass ({result.reason})")
        return verdict(False, result.reason, **camera)
    try:
        key = new_key() if first else deps.keys.get()
        if key is None:
            raise StoreError("key_unavailable", "the key disappeared during the enrollment")
        if first:
            deps.keys.set(key)
            stored = deps.keys.get()  # a key store that drops writes must not pass
            if stored is None or not hmac.compare_digest(stored, key):
                raise StoreError("key_unavailable", "the key store did not keep the key")
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
        domain_state=_current_pin(deps),
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
    guard_dir = data_dir / "guard"
    pin = _stored_pin(guard_dir, deps)
    refused, auth = _admin_authenticate(request, deps, first=False, pin=pin)
    if refused is not None:
        return verdict(False, refused, **auth)
    try:
        removed = forget(guard_dir, deps.keys)
    except StoreError as exc:
        log(f"forget: {exc.reason}")
        return verdict(False, exc.reason, removed=exc.removed, **auth)
    return verdict(True, None, removed=removed, **auth)


def _factor_policy(request: dict[str, Any]) -> str | None:
    """The LocalAuthentication policy of a ``touch_id`` request, ``None`` when it asks for
    something the settings or the merged policy do not allow."""
    from tau_guard.localauth import BIOMETRICS

    kind = request.get("kind")
    if kind in ("unlock", "recheck"):
        return FALLBACK_POLICIES.get(str(_settings(request).get("unlock_fallback")))
    policy = request.get("policy")
    mode = policy.get("step_up") if isinstance(policy, dict) else None
    if kind == "step_up" and mode in ("touch_id", "face_or_touch_id"):
        return BIOMETRICS
    return None


def touch_id_op(request: dict[str, Any], deps: Deps, emit: Emit) -> dict[str, Any]:
    """The Touch ID unlock fallback, recheck or step-up; never opens the camera."""
    from tau_guard.localauth import BIOMETRICS
    from tau_guard.store import StoreError, read_pin

    data_dir = _data_dir(request)
    if data_dir is None:
        log("touch_id: the request has no absolute data_dir")
        return verdict(False, "error")
    if not _enrolled(request):
        return verdict(False, "not_enrolled")
    policy = _factor_policy(request)
    if policy is None:
        log("touch_id: the settings or the policy do not allow Touch ID here")
        return verdict(False, "touch_id_unavailable")
    try:  # the enrollment must be intact for either policy; Touch ID only needs its pin
        pin = read_pin(data_dir / "guard", deps.keys)
    except StoreError as exc:
        log(f"touch_id: the template cannot be used ({exc.reason})")
        return verdict(False, exc.reason)
    if policy != BIOMETRICS:
        pin = None  # the device-owner policy takes the password: no pin applies
    elif pin is None:
        log("touch_id: the enrollment pinned no fingerprint set; enroll again to pin it")
        return verdict(False, "touch_id_failed")
    _Progress(emit, deps).step("touch_id")
    refused, auth = _authenticate(request, deps, policy, pin=pin)
    if refused is not None:
        return verdict(False, refused, **auth)
    return {**verdict(True, "match", **auth), "method": "touch_id"}


def selftest(
    platform: str | None = None,
    *,
    request: dict[str, Any] | None = None,
    deps: Deps | None = None,
) -> dict[str, Any]:
    """Platform and import checks (plus ``details`` when ``deep``); never opens a camera or a
    LocalAuthentication prompt."""
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
    from tau_guard.store import KeyInvalid, KeyUnavailable, StoreError, load_template, read_pin

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
    except KeyInvalid:
        details["keychain"] = "invalid"
    except KeyUnavailable:
        details["keychain"] = "unavailable"
    pin: str | None = None
    pin_read = False
    if data_dir is None or not (data_dir / ENROLLED_MARKER).is_file():
        details["template"] = "not_enrolled"
    else:
        try:
            load_template(data_dir / "guard", deps.keys, SFACE_SHA256)
        except StoreError as exc:
            details["template"] = exc.reason
        else:
            details["template"] = "ok"
        try:
            pin, pin_read = read_pin(data_dir / "guard", deps.keys), True
        except StoreError:
            pass
    details["touch_id"] = _touch_id_details(deps, pin, pin_read)
    camera: dict[str, Any] = {"device": None, "others": 0, "permission": None}
    try:
        listed = deps.devices().devices() if deps.devices is not None else []
        _, device = select_device(listed, _camera_setting(request))
        camera["device"] = device.name
        camera["others"] = len(listed) - 1
        camera["builtin"] = device.builtin
    except Exception as exc:
        camera["error"] = type(exc).__name__
    try:
        if deps.permission is not None:
            camera["permission"] = int(deps.permission().status())
    except Exception:
        camera["permission"] = None
    details["camera"] = camera
    return details


def _touch_id_details(deps: Deps, pin: str | None, pin_read: bool) -> dict[str, Any]:
    """Touch ID for the doctor: its state and why, the lid, and the pinned fingerprint set
    (``ok``, ``changed``, ``not_pinned`` or ``unknown``). No prompt."""
    biometry = _biometry(deps)
    if not pin_read:
        pinned = "unknown"
    elif pin is None:
        pinned = "not_pinned"
    elif biometry.state != "available" or biometry.domain_state is None:
        pinned = "unknown"
    else:
        pinned = "ok" if biometry.domain_state == pin else "changed"
    return {
        "biometry": biometry.state,
        "detail": biometry.detail,
        "clamshell": biometry.clamshell,
        "pin": pinned,
    }


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
    if op not in ("verify", "enroll", "forget", "touch_id"):
        return verdict(False, "error")
    platform = deps.platform if deps is not None else sys.platform
    if platform != "darwin":
        return verdict(False, "unsupported_platform")
    if op in ("verify", "touch_id") and not _enrolled(request):
        return verdict(False, "not_enrolled" if _data_dir(request) else "error")
    deps = deps or system_deps(op)
    if op == "verify":
        return verify_op(request, deps, emit)
    if op == "touch_id":
        return touch_id_op(request, deps, emit)
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
    except Exception as exc:  # where it failed goes to worker.log; never the message
        import traceback

        frames = "".join(traceback.format_tb(exc.__traceback__))
        print(frames, file=sys.stderr, end="", flush=True)
        log(f"{op} failed: {type(exc).__name__}")  # a message could quote a value
        answer = verdict(False, "error")
    finally:
        signal.signal(signal.SIGTERM, previous)
    emit_line(out, answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
