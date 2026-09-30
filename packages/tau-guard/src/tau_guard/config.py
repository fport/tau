"""``[component.guard]``: the guard's knobs, validated strictly (ADR 0008 decisions 4, 10, 12).

tau-core's :func:`tau_core.guard.config_problem` already locks the guard for a non-bool
``enabled`` or an unknown key. Here every known knob is checked too: a value out of range or of
the wrong type makes the service ``unavailable`` (reason ``config``, which ``/status`` and
``tau doctor`` show) with each problem in the hub log; it never falls back to a weaker value.

| key | default | range or values |
|---|---|---|
| ``max_unlock_hours`` | 8 | 1–24 |
| ``idle_lock_minutes`` | 10 | 1–240 |
| ``recheck_after_idle_minutes`` | 3 | 1–240 |
| ``presence_recheck_minutes`` | 30 | 1–1440 |
| ``verify_timeout_seconds`` | 15 | 5–60 |
| ``step_up_challenge_fresh_seconds`` | 120 | 0–600 |
| ``unlock_threshold`` | 0.50 | 0.45–0.95 |
| ``step_up_threshold`` | 0.55 | 0.45–0.95 |
| ``unlock_liveness`` | ``challenge`` | ``challenge``, ``none`` |
| ``step_up`` | ``face`` | ``face``, ``face_or_touch_id``, ``touch_id``, ``none`` |
| ``unlock_fallback`` | ``touch_id`` | ``touch_id``, ``touch_id_or_password``, ``none`` |
| ``camera`` | ``builtin`` | ``builtin`` or a camera id |
| ``window`` | ``true`` | ``true``, ``false``: the guard window during a check (issue 126) |

``verify_timeout_seconds`` bounds the frontal match; the camera stays on for at most 20 s
whatever it says (:data:`tau_guard.camera.MAX_OPEN_SECONDS`), so above about 19 s the camera's
limit ends the match first, with the same verdict (:mod:`tau_guard.verify`).

A client sends its own ``step_up``, ``unlock_liveness`` and ``unlock_fallback`` with every
verification; :func:`stricter_policy` keeps the stricter of the hub's and the client's value,
and reads a knob the client leaves out as the client's default.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tau_core.guard import config_problem
from tau_core.i18n import DEFAULT_LANGUAGE, t

from tau_guard.state import STRICTNESS, Limits

__all__ = [
    "ATTEMPT_GRACE",
    "CHOICES",
    "DEFAULTS",
    "RANGES",
    "GuardSettings",
    "SettingsError",
    "parse_settings",
    "stricter_policy",
]

DEFAULTS: dict[str, Any] = {
    "max_unlock_hours": 8,
    "idle_lock_minutes": 10,
    "recheck_after_idle_minutes": 3,
    "presence_recheck_minutes": 30,
    "verify_timeout_seconds": 15,
    "step_up_challenge_fresh_seconds": 120,
    "unlock_threshold": 0.50,
    "step_up_threshold": 0.55,
    "unlock_liveness": "challenge",
    "step_up": "face",
    "unlock_fallback": "touch_id",
    "camera": "builtin",
    "window": True,
}
RANGES: dict[str, tuple[float, float]] = {
    "max_unlock_hours": (1, 24),
    "idle_lock_minutes": (1, 240),
    "recheck_after_idle_minutes": (1, 240),
    "presence_recheck_minutes": (1, 1440),
    "verify_timeout_seconds": (5, 60),
    "step_up_challenge_fresh_seconds": (0, 600),
    "unlock_threshold": (0.45, 0.95),
    "step_up_threshold": (0.45, 0.95),
}
CHOICES: dict[str, tuple[str, ...]] = {
    "unlock_liveness": ("challenge", "none"),
    "step_up": ("face", "face_or_touch_id", "touch_id", "none"),
    "unlock_fallback": ("touch_id", "touch_id_or_password", "none"),
}
ATTEMPT_GRACE = 15.0
"""Seconds a worker gets beyond ``verify_timeout_seconds`` (start-up, camera warm-up)."""
MAX_CAMERA_ID = 256


class SettingsError(ValueError):
    """``[component.guard]`` holds a value the guard refuses; ``problems`` lists each one."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class GuardSettings:
    max_unlock_hours: float
    idle_lock_minutes: float
    recheck_after_idle_minutes: float
    presence_recheck_minutes: float
    verify_timeout_seconds: float
    step_up_challenge_fresh_seconds: float
    unlock_threshold: float
    step_up_threshold: float
    unlock_liveness: str
    step_up: str
    unlock_fallback: str
    camera: str
    window: bool = True
    """Whether the hub's workers show the guard window (a display, so it never changes a
    verdict; the worker still runs headless without a GUI session)."""

    @property
    def attempt_timeout(self) -> float:
        """How long a worker may run before the service kills it."""
        return self.verify_timeout_seconds + ATTEMPT_GRACE

    def limits(self) -> Limits:
        return Limits(
            max_unlock=self.max_unlock_hours * 3600.0,
            idle_lock=self.idle_lock_minutes * 60.0,
            recheck_after_idle=self.recheck_after_idle_minutes * 60.0,
            presence_recheck=self.presence_recheck_minutes * 60.0,
            attempt_timeout=self.attempt_timeout,
            challenge_fresh=self.step_up_challenge_fresh_seconds,
            unlock_fallback=self.unlock_fallback,
        )

    def policy(self) -> dict[str, str]:
        return {
            "step_up": self.step_up,
            "unlock_liveness": self.unlock_liveness,
            "unlock_fallback": self.unlock_fallback,
        }

    def worker(self) -> dict[str, Any]:
        """The knobs a worker needs (thresholds, timeout, camera, fallback)."""
        return {
            "camera": self.camera,
            "unlock_threshold": self.unlock_threshold,
            "step_up_threshold": self.step_up_threshold,
            "verify_timeout_seconds": self.verify_timeout_seconds,
            "unlock_fallback": self.unlock_fallback,
        }


def _number(key: str, value: Any, problems: list[str]) -> float:
    low, high = RANGES[key]
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        problems.append(f"{key} must be a number between {low:g} and {high:g}, not {value!r}")
        return float(DEFAULTS[key])
    if not low <= value <= high:
        problems.append(f"{key} must be between {low:g} and {high:g}, not {value!r}")
    return float(value)


def _choice(key: str, value: Any, problems: list[str]) -> str:
    allowed = CHOICES[key]
    if value not in allowed:
        problems.append(f"{key} must be one of {', '.join(allowed)}, not {value!r}")
        return str(DEFAULTS[key])
    return str(value)


def parse_settings(table: Mapping[str, Any]) -> GuardSettings:
    """Validate ``[component.guard]``; raises :class:`SettingsError` listing every problem."""
    problems: list[str] = []
    problem = config_problem(table)
    if problem is not None:
        key, kwargs = problem
        problems.append(t(key, DEFAULT_LANGUAGE, **kwargs))
    merged = {**DEFAULTS, **{k: v for k, v in table.items() if k in DEFAULTS}}
    numbers = {key: _number(key, merged[key], problems) for key in RANGES}
    choices = {key: _choice(key, merged[key], problems) for key in CHOICES}
    camera = merged["camera"]
    if not isinstance(camera, str) or not camera.strip() or len(camera) > MAX_CAMERA_ID:
        problems.append(f"camera must be 'builtin' or a camera id, not {camera!r}")
        camera = DEFAULTS["camera"]
    window = merged["window"]
    if not isinstance(window, bool):
        problems.append(f"window must be true or false, not {window!r}")
        window = DEFAULTS["window"]
    if problems:
        raise SettingsError(problems)
    return GuardSettings(**numbers, **choices, camera=camera, window=window)


def stricter_policy(hub: Mapping[str, str], client: Mapping[str, str] | None) -> dict[str, str]:
    """For each weakening-sensitive knob, the stricter of the hub's and the client's value.

    ``client`` is ``None`` only for an in-hub caller, which has no configuration of its own:
    the hub's values apply alone. A client's mapping that leaves a knob out, or names an
    unknown value, counts as the client's default (:data:`DEFAULTS`, the same as
    :data:`tau_core.guard.POLICY_DEFAULTS`), never as agreement with a weaker hub value:
    ``none`` applies only when the hub and the client both say it. A weaker client value is
    ignored, and of two different values with the same rank (``face`` and ``touch_id``) the
    hub's stays."""
    merged = dict(hub)
    if client is None:
        return merged
    for key, ranks in STRICTNESS.items():
        theirs = client.get(key)
        if theirs not in ranks:
            theirs = DEFAULTS[key]
        mine = merged.get(key)
        if mine not in ranks or ranks[theirs] > ranks[mine]:
            merged[key] = theirs
    return merged
