"""Presence sources (a fake Quartz module, never the real one) and ``[component.guard]``."""

from __future__ import annotations

import math
import sys
from typing import Any

import pytest
from tau_guard.config import (
    DEFAULTS,
    GuardSettings,
    SettingsError,
    parse_settings,
    stricter_policy,
)
from tau_guard.presence import PresenceSource, PresenceUnavailable, QuartzPresence
from tau_guard.state import Reading
from tau_guard.testing import FakePresence


class FakeQuartz:
    kCGEventSourceStateHIDSystemState = 1
    kCGAnyInputEventType = 0xFFFFFFFF

    def __init__(self, idle: Any = 12.5, session: Any = None) -> None:
        self.idle = idle
        self.session = session
        self.calls: list[tuple[Any, ...]] = []

    def CGEventSourceSecondsSinceLastEventType(self, state: int, event: int) -> float:  # noqa: N802
        self.calls.append((state, event))
        if isinstance(self.idle, Exception):
            raise self.idle
        return self.idle

    def CGSessionCopyCurrentDictionary(self) -> Any:  # noqa: N802
        if isinstance(self.session, Exception):
            raise self.session
        return self.session


def test_quartz_presence_reads_idle_and_the_screen_lock() -> None:
    quartz = FakeQuartz(idle=42.0, session={"CGSSessionScreenIsLocked": True})
    source = QuartzPresence(quartz)
    assert isinstance(source, PresenceSource)
    assert source.read() == Reading(42.0, True)
    assert quartz.calls == [(1, 0xFFFFFFFF)]  # HID system state, any input event
    quartz.session = {"kCGSSessionOnConsoleKey": True}  # the key is absent while unlocked
    assert source.read() == Reading(42.0, False)


def test_quartz_presence_reads_a_missing_session_as_unknown() -> None:
    source = QuartzPresence(FakeQuartz(idle=3.0, session=None))  # a hub started over SSH
    assert source.read() == Reading(3.0, None)


def test_quartz_presence_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    quartz = FakeQuartz(idle=RuntimeError("no HID"), session=RuntimeError("no session"))
    source = QuartzPresence(quartz)
    assert source.read() == Reading(None, None)
    assert source.read() == Reading(None, None)
    assert len([r for r in caplog.records if "could not be read" in r.message]) == 1


def test_quartz_presence_without_quartz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "Quartz", None)  # import Quartz raises ImportError
    with pytest.raises(PresenceUnavailable):
        QuartzPresence()


def test_fake_presence_is_a_presence_source() -> None:
    fake = FakePresence(idle_seconds=None, screen_locked=None)
    assert isinstance(fake, PresenceSource)
    assert fake.read() == Reading(None, None) and fake.reads == 1


# -- settings ------------------------------------------------------------------------------------


def test_defaults() -> None:
    settings = parse_settings({"enabled": True})
    assert isinstance(settings, GuardSettings)
    limits = settings.limits()
    assert limits.max_unlock == 8 * 3600 and limits.idle_lock == 600
    assert limits.recheck_after_idle == 180 and limits.presence_recheck == 1800
    assert limits.attempt_timeout == 30 and limits.challenge_fresh == 120
    assert limits.unlock_fallback == "touch_id"
    assert parse_settings(
        {"enabled": True, "unlock_fallback": "none"}
    ).limits().unlock_fallback == ("none")
    assert settings.policy() == {"step_up": "face", "unlock_liveness": "challenge"}
    assert settings.worker()["unlock_threshold"] == 0.5
    assert settings.camera == DEFAULTS["camera"] == "builtin"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_unlock_hours", 0),
        ("max_unlock_hours", 25),
        ("max_unlock_hours", "8"),
        ("max_unlock_hours", True),
        ("idle_lock_minutes", 0),
        ("idle_lock_minutes", 241),
        ("idle_lock_minutes", math.nan),
        ("recheck_after_idle_minutes", 0),
        ("presence_recheck_minutes", 2000),
        ("verify_timeout_seconds", 1),
        ("unlock_threshold", 0.44),
        ("step_up_threshold", 1.2),
        ("unlock_liveness", "passive"),
        ("step_up", "faces"),
        ("unlock_fallback", "pin"),
        ("camera", ""),
        ("camera", 3),
        ("enabled", "yes"),
        ("enable", True),
    ],
)
def test_bad_knobs_are_refused_never_weakened(key: str, value: Any) -> None:
    with pytest.raises(SettingsError) as caught:
        parse_settings({"enabled": True, key: value})
    assert caught.value.problems


def test_every_problem_is_listed() -> None:
    with pytest.raises(SettingsError) as caught:
        parse_settings({"idle_lock_minutes": 0, "max_unlock_hours": 99, "step_up": "x"})
    assert len(caught.value.problems) == 3


def test_edges_of_the_ranges_are_accepted() -> None:
    settings = parse_settings(
        {"max_unlock_hours": 24, "idle_lock_minutes": 1, "unlock_threshold": 0.45}
    )
    assert settings.max_unlock_hours == 24 and settings.idle_lock_minutes == 1


def test_a_client_policy_can_only_make_the_check_stricter() -> None:
    hub = {"step_up": "face_or_touch_id", "unlock_liveness": "none"}
    assert stricter_policy(hub, {"step_up": "face", "unlock_liveness": "challenge"}) == {
        "step_up": "face",
        "unlock_liveness": "challenge",
    }
    strict = {"step_up": "face", "unlock_liveness": "challenge"}
    assert stricter_policy(strict, {"step_up": "none", "unlock_liveness": "none"}) == strict
    assert stricter_policy(strict, {"step_up": "touch_id"}) == strict  # same rank: the hub's
    assert stricter_policy(strict, {"step_up": "bogus"}) == strict
    assert stricter_policy(strict, None) == strict
    both_none = {"step_up": "none", "unlock_liveness": "none"}
    assert stricter_policy(both_none, both_none) == both_none  # none only when both agree
