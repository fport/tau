"""LocalAuthentication in the worker: Touch ID and the Mac password (ADR 0008 decision 15).

Two policies:

- :data:`BIOMETRICS` (``LAPolicyDeviceOwnerAuthenticationWithBiometrics``, policy 1): Touch ID
  only. The prompt has no "Use Password…" button, the reuse duration is 0 (a fingerprint from
  a moment ago never counts), and the enrolled fingerprint set is pinned: its ``domainState``
  (as a sha256, :func:`state_hash`) is stored in the encrypted template at enrollment, and a
  different set answers ``changed`` (``touch_id_failed``), before the prompt and again after
  it. Someone who knows the Mac password and adds a finger in System Settings therefore gets
  nothing from Touch ID here, and removing every finger does not bring the password back:
  a pinned enrollment is only ever authorised by Touch ID with its pin
  (:func:`tau_guard.worker.admin_policy`).
- :data:`DEVICE_OWNER` (``LAPolicyDeviceOwnerAuthentication``, policy 2): Touch ID, the Mac
  password or a paired Apple Watch, as macOS offers them. It authorises a first enrollment,
  re-enrollment and ``forget`` on a Mac without Touch ID, and the ``touch_id_or_password``
  unlock fallback (the opt-in for a closed lid). The pin does not apply to it: whoever could
  change the fingerprint set knows the password.

**Availability** (:meth:`LocalAuthFactor.biometry`, which never shows a prompt): ``available``;
``unavailable`` when the Mac has Touch ID that cannot be used now (the lid is closed, so the
built-in sensor is off, a Touch ID keyboard is disconnected, or Touch ID is locked out after
failed tries); ``none`` when there is no sensor or no enrolled finger. A closed lid makes the
biometrics policy ``unavailable`` whatever else is attached (``touch_id_unavailable``) on a Mac
that has Touch ID; a Mac that reports no sensor stays ``none`` with the lid closed, so its
re-enrollment and ``forget`` keep the device-owner policy.

**Time limit.** Every ``LAContext`` is used once and invalidated in a ``finally``: after
:data:`LA_TIMEOUT` (30 s) without an answer (``timeout``), at once when the attempt is
cancelled (the hub's SIGTERM raises in the waiting worker), and after an answer.

:class:`LocalAuthFactor` is the seam. :class:`MacLocalAuth` runs ``LAContext`` inside the worker
(``LocalAuthentication`` from pyobjc, imported lazily; tests pass a fake module), so the sheet
appears on the Mac's screen and the hub never imports pyobjc. Tests use
``tau_guard.testing.FakeLocalAuth``, so no test ever shows a prompt. The reason text is UI chrome:
the hub or the CLI puts it into the worker request in the owner's language
(``guard.cli.la.*``); macOS shows "<app> is trying to <text>."
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "BIOMETRICS",
    "BIOMETRY_STATES",
    "DEVICE_OWNER",
    "LA_TIMEOUT",
    "OUTCOMES",
    "POLICIES",
    "Biometry",
    "LocalAuthFactor",
    "MacLocalAuth",
    "clamshell_closed",
    "state_hash",
    "verdict_reason",
]

DEVICE_OWNER = "device_owner"
BIOMETRICS = "biometrics"
POLICIES = (BIOMETRICS, DEVICE_OWNER)
LA_TIMEOUT = 30.0
"""Seconds a prompt may stay up before its context is invalidated."""
OUTCOMES = ("ok", "failed", "cancelled", "unavailable", "timeout", "changed")
"""``changed``: the enrolled fingerprint set is not the pinned one."""
BIOMETRY_STATES = ("available", "unavailable", "none")
_POLICY_IDS = {BIOMETRICS: 1, DEVICE_OWNER: 2}
"""``LAPolicyDeviceOwnerAuthenticationWithBiometrics`` and ``LAPolicyDeviceOwnerAuthentication``."""
TOUCH_ID = 1
"""``LABiometryTypeTouchID``."""
# LAError codes
_USER_CANCEL, _SYSTEM_CANCEL, _APP_CANCEL = -2, -4, -9
_PASSCODE_NOT_SET = -5
_NOT_AVAILABLE, _NOT_ENROLLED, _LOCKOUT = -6, -7, -8
_NOT_PAIRED, _DISCONNECTED = -12, -13
IOREG = ("/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "1")
_CLAMSHELL = re.compile(r'"AppleClamshellState"\s*=\s*(Yes|No)')


@dataclass(frozen=True)
class Biometry:
    """Touch ID right now (see the module docstring)."""

    state: str
    """One of :data:`BIOMETRY_STATES`."""
    detail: str | None = None
    """Why it is not ``available``: ``clamshell``, ``lockout``, ``disconnected``,
    ``not_available``, ``not_enrolled``, ``no_sensor``, ``no_passcode`` or ``error``."""
    domain_state: str | None = None
    """The enrolled fingerprint set as a sha256 (:func:`state_hash`), when ``available``."""
    clamshell: bool | None = None
    """The lid is closed (``None``: unknown, or a Mac without a lid)."""

    @property
    def exists(self) -> bool:
        """The Mac has Touch ID with enrolled fingers, usable now or not."""
        return self.state != "none"


@runtime_checkable
class LocalAuthFactor(Protocol):
    def biometry(self) -> Biometry:
        """Touch ID's state; never shows a prompt, never raises."""
        ...

    def authenticate(
        self,
        policy: str,
        reason: str,
        *,
        timeout: float = LA_TIMEOUT,
        domain_state: str | None = None,
    ) -> str:
        """Ask the owner; one of :data:`OUTCOMES`. With :data:`BIOMETRICS` and a
        ``domain_state``, a different fingerprint set answers ``changed``. Never raises."""
        ...


def verdict_reason(outcome: str) -> str:
    """The verdict reason of a LocalAuthentication outcome other than ``ok``."""
    return "touch_id_unavailable" if outcome == "unavailable" else "touch_id_failed"


def state_hash(data: Any) -> str | None:
    """A ``domainState`` (``NSData``) as a sha256 hex string; ``None`` without one."""
    if data is None:
        return None
    try:
        raw = bytes(data)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(raw).hexdigest() if raw else None


def clamshell_closed(run: Callable[..., Any] = subprocess.run) -> bool | None:
    """Whether the lid is closed (IOKit's ``AppleClamshellState`` through ``ioreg``); ``None``
    when it cannot be read or the Mac has no lid."""
    try:
        out = run(IOREG, capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = _CLAMSHELL.search(out or "")
    return None if match is None else match.group(1) == "Yes"


def _code(error: Any) -> int | None:
    if error is None:
        return None
    try:
        return int(error.code())
    except Exception:
        return None


def _biometry_type(context: Any) -> int:
    try:
        return int(context.biometryType())
    except Exception:
        return 0


def _domain_state(context: Any) -> str | None:
    """The context's fingerprint set: ``domainState.biometry.stateHash`` (macOS 15), else
    ``evaluatedPolicyDomainState``."""
    data = None
    with suppress(Exception):
        data = context.domainState().biometry().stateHash()
    if data is None:
        with suppress(Exception):
            data = context.evaluatedPolicyDomainState()
    return state_hash(data)


def _invalidate(context: Any) -> None:
    with suppress(Exception):
        context.invalidate()


def _classify(
    can: bool, kind: int, code: int | None, lid: bool | None, state: str | None
) -> Biometry:
    no_sensor = not can and code in (_NOT_AVAILABLE, _NOT_PAIRED) and kind != TOUCH_ID
    if no_sensor:  # a Mac without Touch ID, whatever the lid does
        return Biometry("none", "no_sensor", clamshell=lid)
    if lid is True:
        return Biometry("unavailable", "clamshell", clamshell=True)
    if can:
        return Biometry("available", None, state, lid)
    if code == _NOT_ENROLLED:
        return Biometry("none", "not_enrolled", clamshell=lid)
    if code == _LOCKOUT:
        return Biometry("unavailable", "lockout", clamshell=lid)
    if code == _DISCONNECTED:
        return Biometry("unavailable", "disconnected", clamshell=lid)
    if code in (_NOT_AVAILABLE, _NOT_PAIRED):
        return Biometry("unavailable", "not_available", clamshell=lid)
    if code == _PASSCODE_NOT_SET:
        return Biometry("unavailable", "no_passcode", clamshell=lid)
    return Biometry("unavailable", "error", clamshell=lid)


class MacLocalAuth:
    """:class:`LocalAuthFactor` through ``LAContext``. ``la`` is the pyobjc
    ``LocalAuthentication`` module (imported here when omitted) and ``clamshell`` the lid probe;
    tests pass fakes for both."""

    def __init__(
        self, la: Any | None = None, *, clamshell: Callable[[], bool | None] | None = None
    ) -> None:
        if la is None:
            import LocalAuthentication as la  # type: ignore[import-not-found,no-redef]
        self._la = la
        self._clamshell = clamshell or clamshell_closed

    def _lid(self) -> bool | None:
        try:
            return self._clamshell()
        except Exception:
            return None

    def _context(self) -> Any:
        context = self._la.LAContext.alloc().init()
        with suppress(Exception):  # the default is 0 too; set it so nothing can widen it
            context.setTouchIDAuthenticationAllowableReuseDuration_(0.0)
        return context

    def biometry(self) -> Biometry:
        lid = self._lid()
        try:
            context = self._context()
        except Exception:
            return Biometry("unavailable", "error", clamshell=lid)
        try:
            can, error = context.canEvaluatePolicy_error_(_POLICY_IDS[BIOMETRICS], None)
            kind = _biometry_type(context)
            state = _domain_state(context) if can else None
            return _classify(bool(can), kind, _code(error), lid, state)
        except Exception:
            return Biometry("unavailable", "error", clamshell=lid)
        finally:
            _invalidate(context)

    def authenticate(
        self,
        policy: str,
        reason: str,
        *,
        timeout: float = LA_TIMEOUT,
        domain_state: str | None = None,
    ) -> str:
        policy_id = _POLICY_IDS.get(policy)
        if policy_id is None:
            return "unavailable"
        biometric = policy == BIOMETRICS
        if biometric and self._lid() is True:
            return "unavailable"  # the built-in sensor is off with the lid closed
        try:
            context = self._context()
        except Exception:
            return "unavailable"
        done = threading.Event()
        box: dict[str, Any] = {}

        def reply(success: bool, error: Any) -> None:
            box["ok"] = bool(success)
            box["code"] = _code(error)
            done.set()

        try:
            if biometric:
                with suppress(Exception):
                    context.setLocalizedFallbackTitle_("")  # no "Use Password…" button
            try:
                can, _error = context.canEvaluatePolicy_error_(policy_id, None)
            except Exception:
                return "unavailable"
            if not can:
                return "unavailable"
            if biometric and domain_state is not None and _domain_state(context) != domain_state:
                return "changed"
            try:
                context.evaluatePolicy_localizedReason_reply_(policy_id, reason, reply)
            except Exception:
                return "unavailable"
            if not done.wait(max(0.0, min(float(timeout), LA_TIMEOUT))):
                return "timeout"
            if not box.get("ok"):
                code = box.get("code")
                if code in (_USER_CANCEL, _SYSTEM_CANCEL, _APP_CANCEL):
                    return "cancelled"
                return "unavailable" if code in (_NOT_AVAILABLE, _DISCONNECTED) else "failed"
            if biometric and domain_state is not None and _domain_state(context) != domain_state:
                return "changed"  # the set changed while the prompt was up
            return "ok"
        finally:
            _invalidate(context)  # after an answer, after 30 s, and at once on a cancel
