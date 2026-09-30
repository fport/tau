"""``MacLocalAuth`` against a fake ``LocalAuthentication`` module (issue 114).

The fake speaks the pyobjc surface ``MacLocalAuth`` uses (``LAContext.alloc().init()``,
``canEvaluatePolicy_error_``, ``evaluatePolicy_localizedReason_reply_``, the domain state, the
biometry type, ``invalidate``), so the macOS implementation's decisions are tested on any
platform. No test imports pyobjc or shows a prompt.
"""

from __future__ import annotations

import hashlib
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from tau_guard.localauth import (
    BIOMETRICS,
    DEVICE_OWNER,
    LA_TIMEOUT,
    Biometry,
    LocalAuthFactor,
    MacLocalAuth,
    clamshell_closed,
    state_hash,
    verdict_reason,
)
from tau_guard.testing import FakeLocalAuth

SET_A = b"fingerprints-a"
SET_B = b"fingerprints-b"


class _Error:
    def __init__(self, code: int) -> None:
        self._code = code

    def code(self) -> int:
        return self._code


class FakeContext:
    """One ``LAContext``: ``la`` holds the Mac's state and records every context."""

    def __init__(self, la: FakeLA) -> None:
        self.la = la
        self.reuse: float | None = None
        self.fallback_title: str | None = None
        self.evaluated: list[tuple[int, str]] = []
        self.invalidated = False
        la.contexts.append(self)

    # pyobjc construction
    def init(self) -> FakeContext:
        return self

    # properties
    def setTouchIDAuthenticationAllowableReuseDuration_(self, seconds: float) -> None:
        self.reuse = seconds

    def setLocalizedFallbackTitle_(self, title: str) -> None:
        self.fallback_title = title

    def biometryType(self) -> int:
        return self.la.biometry_type

    def evaluatedPolicyDomainState(self) -> bytes | None:
        return self.la.domain_state

    def canEvaluatePolicy_error_(self, policy: int, error: Any) -> tuple[bool, Any]:
        if self.la.can_raises:
            raise RuntimeError("LocalAuthentication broke")
        code = self.la.can_codes.get(policy)
        return (code is None, None if code is None else _Error(code))

    def evaluatePolicy_localizedReason_reply_(self, policy: int, reason: str, reply: Any) -> None:
        self.evaluated.append((policy, reason))
        if self.la.during_evaluation is not None:
            self.la.during_evaluation()
        answer = self.la.answer
        if answer is None:
            return  # nobody touches the sensor
        ok, code = answer
        threading.Thread(target=reply, args=(ok, _Error(code) if code else None)).start()

    def invalidate(self) -> None:
        self.invalidated = True


class FakeLA:
    """The ``LocalAuthentication`` module of a Mac with Touch ID (by default)."""

    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.biometry_type = 1
        self.domain_state: bytes | None = SET_A
        self.can_codes: dict[int, int] = {}
        self.can_raises = False
        self.answer: tuple[bool, int] | None = (True, 0)
        self.during_evaluation: Any = None
        la = self

        class _LAContext:
            @staticmethod
            def alloc() -> FakeContext:
                return FakeContext(la)

        self.LAContext = _LAContext


def factor(la: FakeLA, *, lid: bool | None = False) -> MacLocalAuth:
    return MacLocalAuth(la, clamshell=lambda: lid)


def test_the_module_imports_no_pyobjc() -> None:
    code = (
        "import sys, tau_guard.localauth, tau_guard.runner, tau_guard.worker; "
        "print(sorted({'LocalAuthentication', 'objc'} & set(sys.modules)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    assert out.strip() == "[]"
    assert isinstance(factor(FakeLA()), LocalAuthFactor)
    assert isinstance(FakeLocalAuth(), LocalAuthFactor)
    assert LA_TIMEOUT == 30.0


def test_state_hash_and_verdict_reasons() -> None:
    assert state_hash(SET_A) == hashlib.sha256(SET_A).hexdigest()
    assert state_hash(None) is None and state_hash(b"") is None and state_hash(object()) is None
    assert verdict_reason("unavailable") == "touch_id_unavailable"
    for outcome in ("failed", "cancelled", "timeout", "changed", "anything"):
        assert verdict_reason(outcome) == "touch_id_failed"


# -- availability ----------------------------------------------------------------------------


def test_available_touch_id_reports_the_fingerprint_set_without_a_prompt() -> None:
    la = FakeLA()
    biometry = factor(la).biometry()
    assert biometry == Biometry("available", None, state_hash(SET_A), False)
    assert biometry.exists
    [context] = la.contexts
    assert context.evaluated == [] and context.invalidated and context.reuse == 0.0


@pytest.mark.parametrize(
    ("code", "kind", "lid", "state", "detail"),
    [
        (None, 1, True, "unavailable", "clamshell"),  # the built-in sensor is off
        (-6, 1, True, "unavailable", "clamshell"),
        (-4, 0, True, "unavailable", "clamshell"),  # "not available in closed clamshell mode"
        (-6, 0, True, "none", "no_sensor"),  # a laptop without Touch ID, lid closed
        (-12, 0, True, "none", "no_sensor"),
        (-7, 1, False, "none", "not_enrolled"),
        (-6, 1, False, "unavailable", "not_available"),
        (-6, 0, None, "none", "no_sensor"),
        (-12, 0, None, "none", "no_sensor"),
        (-8, 1, False, "unavailable", "lockout"),
        (-13, 1, None, "unavailable", "disconnected"),
        (-5, 1, False, "unavailable", "no_passcode"),
        (-1004, 1, False, "unavailable", "error"),
    ],
)
def test_availability_is_classified(
    code: int | None, kind: int, lid: bool | None, state: str, detail: str
) -> None:
    la = FakeLA()
    la.biometry_type = kind
    if code is not None:
        la.can_codes[1] = code
    biometry = factor(la, lid=lid).biometry()
    assert (biometry.state, biometry.detail) == (state, detail)
    assert biometry.domain_state is None
    assert biometry.exists is (state != "none")
    assert all(context.invalidated for context in la.contexts)


def test_a_broken_framework_is_unavailable_never_a_crash() -> None:
    la = FakeLA()
    la.can_raises = True
    assert factor(la).biometry().state == "unavailable"
    assert factor(la).authenticate(BIOMETRICS, "unlock tau") == "unavailable"
    broken = SimpleNamespace(LAContext=None)
    assert factor(broken).biometry() == Biometry("unavailable", "error", clamshell=False)  # type: ignore[arg-type]
    assert factor(broken).authenticate(DEVICE_OWNER, "x") == "unavailable"  # type: ignore[arg-type]
    assert factor(FakeLA()).authenticate("password", "x") == "unavailable"


# -- authenticate ----------------------------------------------------------------------------


def test_touch_id_only_hides_the_password_button_and_reuses_nothing() -> None:
    la = FakeLA()
    pin = state_hash(SET_A)
    assert factor(la).authenticate(BIOMETRICS, "unlock tau", domain_state=pin) == "ok"
    [context] = la.contexts
    assert context.evaluated == [(1, "unlock tau")]
    assert context.fallback_title == "" and context.reuse == 0.0 and context.invalidated


def test_the_device_owner_policy_keeps_the_password_and_ignores_the_pin() -> None:
    la = FakeLA()
    other = state_hash(SET_B)
    assert factor(la).authenticate(DEVICE_OWNER, "enroll", domain_state=other) == "ok"
    [context] = la.contexts
    assert context.evaluated == [(2, "enroll")] and context.fallback_title is None


def test_a_changed_fingerprint_set_refuses_before_the_prompt() -> None:
    la = FakeLA()
    la.domain_state = SET_B  # someone added a finger
    outcome = factor(la).authenticate(BIOMETRICS, "unlock tau", domain_state=state_hash(SET_A))
    assert outcome == "changed"
    [context] = la.contexts
    assert context.evaluated == [] and context.invalidated


def test_a_fingerprint_set_that_changes_during_the_prompt_is_refused() -> None:
    la = FakeLA()

    def add_a_finger() -> None:
        la.domain_state = SET_B

    la.during_evaluation = add_a_finger
    outcome = factor(la).authenticate(BIOMETRICS, "unlock tau", domain_state=state_hash(SET_A))
    assert outcome == "changed"


def test_an_unreadable_fingerprint_set_never_matches_a_pin() -> None:
    la = FakeLA()
    la.domain_state = None
    outcome = factor(la).authenticate(BIOMETRICS, "x", domain_state=state_hash(SET_A))
    assert outcome == "changed" and la.contexts[0].evaluated == []


def test_a_closed_lid_makes_touch_id_only_unavailable_but_not_the_password() -> None:
    la = FakeLA()
    closed = factor(la, lid=True)
    assert closed.authenticate(BIOMETRICS, "x", domain_state=state_hash(SET_A)) == "unavailable"
    assert la.contexts == []  # no context, no prompt
    assert closed.authenticate(DEVICE_OWNER, "x") == "ok"  # touch_id_or_password: the opt-in


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        ((False, -1), "failed"),
        ((False, -2), "cancelled"),
        ((False, -4), "cancelled"),
        ((False, -9), "cancelled"),
        ((False, -8), "failed"),  # locked out after failed tries
        ((False, -6), "unavailable"),
        ((False, -13), "unavailable"),
        ((False, -1004), "unavailable"),  # no interface allowed: not a wrong finger
        ((False, 0), "failed"),
    ],
)
def test_answers_map_to_outcomes(answer: tuple[bool, int], outcome: str) -> None:
    la = FakeLA()
    la.answer = answer
    assert factor(la).authenticate(BIOMETRICS, "x", domain_state=state_hash(SET_A)) == outcome
    assert la.contexts[0].invalidated


def test_a_policy_that_cannot_be_evaluated_is_unavailable() -> None:
    la = FakeLA()
    la.can_codes[1] = -6
    assert factor(la).authenticate(BIOMETRICS, "x") == "unavailable"
    assert la.contexts[0].evaluated == [] and la.contexts[0].invalidated


def test_an_unanswered_prompt_is_invalidated_at_its_time_limit() -> None:
    la = FakeLA()
    la.answer = None
    started = time.monotonic()
    assert factor(la).authenticate(DEVICE_OWNER, "x", timeout=0.05) == "timeout"
    assert time.monotonic() - started < 5
    assert la.contexts[0].invalidated


def test_the_time_limit_is_never_longer_than_30_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float | None] = []

    def wait(self: threading.Event, timeout: float | None = None) -> bool:
        waits.append(timeout)
        return False

    monkeypatch.setattr(threading.Event, "wait", wait)
    la = FakeLA()
    la.answer = None
    assert factor(la).authenticate(DEVICE_OWNER, "x", timeout=600) == "timeout"
    assert waits == [30.0] and la.contexts[0].invalidated


class _Stop(BaseException):
    """What the worker's SIGTERM handler raises (``tau_guard.worker.Terminated``)."""


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="needs setitimer")
def test_a_cancelled_attempt_invalidates_the_context_at_once() -> None:
    la = FakeLA()
    la.answer = None  # the prompt stays up
    previous = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_Stop()))
    signal.setitimer(signal.ITIMER_REAL, 0.05)
    try:
        with pytest.raises(_Stop):
            factor(la).authenticate(BIOMETRICS, "x", domain_state=state_hash(SET_A))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    assert la.contexts[0].evaluated and la.contexts[0].invalidated


# -- the lid ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("out", "closed"),
    [
        ('  | |   "AppleClamshellState" = Yes\n', True),
        ('"AppleClamshellCausesSleep" = Yes\n"AppleClamshellState" = No\n', False),
        ("", None),  # a Mac without a lid
    ],
)
def test_the_lid_is_read_from_ioreg(out: str, closed: bool | None) -> None:
    calls: list[Any] = []

    def run(args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=out)

    assert clamshell_closed(run) is closed
    [(args, kwargs)] = calls
    assert args[0] == "/usr/sbin/ioreg" and "AppleClamshellState" in args
    assert kwargs["timeout"] <= 5 and kwargs["check"] is False


def test_an_unreadable_lid_is_unknown() -> None:
    def fails(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("ioreg", 2)

    assert clamshell_closed(fails) is None

    def broken() -> bool:
        raise RuntimeError("no IOKit")

    assert MacLocalAuth(FakeLA(), clamshell=broken).biometry().clamshell is None
