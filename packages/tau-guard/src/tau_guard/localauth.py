"""LocalAuthentication in the worker (ADR 0008 decisions 12 and 15).

On macOS enrollment and ``tau guard forget`` always run behind LocalAuthentication. This slice
(issue 112) uses the device-owner policy, :data:`DEVICE_OWNER` (Touch ID or the Mac password,
``LAPolicyDeviceOwnerAuthentication``), for both. Issue 114 adds :data:`BIOMETRICS`
(``LAPolicyDeviceOwnerAuthenticationWithBiometrics``) with ``domainState`` pinning for
re-enrollment and forget, the Touch ID unlock fallback and the Touch ID step-up.

:class:`LocalAuthFactor` is the seam. :class:`MacLocalAuth` runs ``LAContext`` inside the worker
(pyobjc imported lazily); tests pass ``tau_guard.testing.FakeLocalAuth``, so no test ever shows
a prompt. The reason text is UI chrome: the hub or the CLI puts it in the worker request in the
owner's language (``guard.cli.la.*``), and macOS shows it in its prompt.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "BIOMETRICS",
    "DEVICE_OWNER",
    "LA_TIMEOUT",
    "OUTCOMES",
    "LocalAuthFactor",
    "MacLocalAuth",
    "verdict_reason",
]

DEVICE_OWNER = "device_owner"
BIOMETRICS = "biometrics"
LA_TIMEOUT = 60.0
OUTCOMES = ("ok", "failed", "cancelled", "unavailable", "timeout")
_POLICY_IDS = {DEVICE_OWNER: 2, BIOMETRICS: 1}
"""``LAPolicyDeviceOwnerAuthentication`` and ``...WithBiometrics``."""


@runtime_checkable
class LocalAuthFactor(Protocol):
    def authenticate(self, policy: str, reason: str, *, timeout: float = LA_TIMEOUT) -> str:
        """Ask the owner; one of :data:`OUTCOMES`. Never raises."""
        ...


def verdict_reason(outcome: str) -> str:
    """The verdict reason of a LocalAuthentication outcome other than ``ok``."""
    return "touch_id_unavailable" if outcome == "unavailable" else "touch_id_failed"


class MacLocalAuth:
    """:class:`LocalAuthFactor` through ``LAContext`` (``la`` is the pyobjc module; tests never
    construct this class)."""

    def __init__(self, la: Any | None = None) -> None:
        if la is None:
            import LocalAuthentication as la  # type: ignore[import-not-found,no-redef]
        self._la = la

    def authenticate(self, policy: str, reason: str, *, timeout: float = LA_TIMEOUT) -> str:
        policy_id = _POLICY_IDS.get(policy)
        if policy_id is None:
            return "unavailable"
        try:
            context = self._la.LAContext.alloc().init()
            can, _error = context.canEvaluatePolicy_error_(policy_id, None)
        except Exception:
            return "unavailable"
        if not can:
            return "unavailable"
        done = threading.Event()
        box: dict[str, Any] = {}

        def reply(success: bool, error: Any) -> None:
            box["ok"] = bool(success)
            box["code"] = int(error.code()) if error is not None else None
            done.set()

        try:
            context.evaluatePolicy_localizedReason_reply_(policy_id, reason, reply)
        except Exception:
            return "unavailable"
        if not done.wait(timeout):
            try:
                context.invalidate()
            except Exception:
                pass
            return "timeout"
        if box.get("ok"):
            return "ok"
        # LAErrorUserCancel (-2), LAErrorSystemCancel (-4), LAErrorAppCancel (-9)
        return "cancelled" if box.get("code") in (-2, -4, -9) else "failed"
