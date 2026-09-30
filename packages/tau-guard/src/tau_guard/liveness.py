"""The head-turn challenge (ADR 0008 decision 12), against a printed photo or a phone clip.

**The signal.** The head's yaw in degrees (:attr:`tau_guard.engine.Face.pose`: YuNet's five
landmarks fitted to a generic 3D head with ``cv2.solvePnP``). A real head turn moves the nose
out of the plane of the eyes and the mouth, and the fit follows it. A flat photo turned about
the vertical axis only squeezes its landmarks: up to about 40 degrees the fit reads a few
degrees at most, and beyond that the landmarks stop fitting a head. So a frame counts only when
its fit error (:attr:`~tau_guard.engine.HeadPose.fit`) is at most :func:`fit_limit` of the
attempt's frontal frames: 0.10 eye distances, or 1.5 times the frontal frames' median error
when a face fits the generic head less well. Frames are smoothed: each step sees the median of
the last 3 frames that fit.

Everything is measured in degrees relative to the **baseline**, the median yaw of the attempt's
frontal frames, so a seat a little to the side still works. Enrollment calibrates the sign of a
left turn and the owner's amplitude to each side (:class:`Calibration`). A calibration stored
before issue 127 (in units of the old yaw proxy ``(nose_x - eye_mid_x) / eye distance``) keeps
its sign and uses :data:`DEFAULT_AMPLITUDE` on both sides; ``tau guard enroll`` measures the
owner's own again.

**A step** (``turn_left`` or ``turn_right``, drawn at random; unlock asks for 2, step-up for 3):

1. A random pause of 0.3-0.9 s, then the prompt is published with its deadline: 4.0 s from the
   publication.
2. The step arms on the first frame within :data:`RETURN_TOLERANCE` (6 degrees) of the
   baseline, so a head that is already turned when the prompt appears (a clip that happens to
   be turned) does not count.
3. The turn in the asked direction reaches ``max(12, 0.5 x the calibrated amplitude)`` degrees
   and holds for a random 0.3-0.6 s; the hold goes on while the turn stays within
   :data:`HOLD_SLACK` (3 degrees) of that. Then ``center`` is published.
4. The head comes back within 6 degrees of the baseline, or swings past it (a real head does):
   the step passed.

**Failing.** Every rule below ends the check as ``spoof``, and the rule's code travels in the
verdict's ``liveness`` field to the audit log (:data:`FAILURES`):

- ``overshoot_before_target``: after the step armed and before its hold is done, the head moves
  :data:`OPPOSITE_TOLERANCE` (8 degrees) or more the other way, beyond the baseline and beyond
  where it armed (the wrong direction, or a clip swinging through; a return swing of the step
  before that is still settling when the step arms does not count);
- ``oscillation``: more than :data:`MAX_REVERSALS` (3) reversals of direction, each of at least
  :data:`SWING` (6 degrees), within one step (a turn, a hesitation and the return are 3): a
  looping head shake;
- ``moved_between_prompts``: while no prompt is up, the head is more than
  :data:`IDLE_TOLERANCE` (10 degrees) from the baseline, except on the side opposite the step
  just done, where the return swing may reach :data:`RETURN_SWING` (20 degrees). A person waits
  facing the camera; a clip keeps moving;
- ``no_turn``: the deadline passed and the turn never reached its target;
- ``too_slow``: the turn reached its target but the hold was not done by the deadline;
- ``no_return``: the hold was done but the head did not come back by the deadline.

A step whose frames stop (the camera's limit, a closed lid) fails as it would at its deadline.
``face_lost`` (the face gone for more than 0.2 s, or a jump of the box) and ``step_identity``
(the frames near the baseline around a step were not the owner's) come from
:mod:`tau_guard.verify`; ``abandoned`` (a cancel or a lock at a prompt) from the hub
(:mod:`tau_guard.state`). Every challenge failure is a counted failure, so a looping clip
cannot skip the prompts it does not fit.

**The camera's time limit.** Given ``until`` (when the frames stop), a prompt is published only
when its step can end before then (the last one with ``reserve`` seconds more, for the frontal
match after the steps); otherwise :meth:`Challenge.feed` answers ``"out_of_time"`` before the
prompt, so the camera never cuts a published step short and the check ends as ``timeout``
without having shown anything.

The continuity rules (exactly one face, box IoU above 0.3 from frame to frame, no gap), the
frontal identity match before and after the steps and the identity of the frames near the
baseline between them live in :mod:`tau_guard.verify`, which feeds this machine. Time is the
frames' monotonic timestamps; randomness comes from the ``rng`` the caller passes
(``random.SystemRandom`` in the worker, a seeded one in tests).
"""

from __future__ import annotations

import math
import random
import statistics
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from tau_guard.engine import Face

__all__ = [
    "DEFAULT_AMPLITUDE",
    "DIRECTIONS",
    "FAILURES",
    "FIT_SLACK",
    "HOLD_RANGE",
    "HOLD_SLACK",
    "IDLE_TOLERANCE",
    "MAX_FIT",
    "MAX_REVERSALS",
    "OPPOSITE_TOLERANCE",
    "PAUSE_RANGE",
    "RETURN_SWING",
    "RETURN_TOLERANCE",
    "STEP_SECONDS",
    "STEP_UP_STEPS",
    "SWING",
    "TURN_FACTOR",
    "TURN_FLOOR",
    "UNLOCK_STEPS",
    "Calibration",
    "Challenge",
    "Prompt",
    "draw_directions",
    "fit_limit",
]

TURN_FLOOR = 12.0
"""Degrees: the smallest turn a step asks for."""
TURN_FACTOR = 0.5
"""The share of the calibrated amplitude a step asks for, when that is more than the floor."""
RETURN_TOLERANCE = 6.0
"""Degrees from the baseline that count as back (and arm a step)."""
HOLD_RANGE = (0.3, 0.6)
HOLD_SLACK = 3.0
"""Degrees the turn may sag below its target while the hold goes on."""
PAUSE_RANGE = (0.3, 0.9)
STEP_SECONDS = 4.0
IDLE_TOLERANCE = 10.0
"""Degrees from the baseline a head may move while no prompt is up."""
RETURN_SWING = 20.0
"""Degrees past the baseline, on the side opposite the step just done, that the return swing
may reach while no prompt is up."""
OPPOSITE_TOLERANCE = 8.0
"""Degrees the wrong way that abort a step before its hold is done."""
SWING = 6.0
"""Degrees back from the last extreme that count as a reversal of direction."""
MAX_REVERSALS = 3
SMOOTHING = 3
"""Frames in the running median."""
MAX_FIT = 0.10
"""Eye distances: the largest fit error of a frame that counts (see :func:`fit_limit`)."""
FIT_SLACK = 1.5
DEFAULT_AMPLITUDE = 24.0
"""Degrees to each side for a calibration from before issue 127 (the target is then 12)."""
UNLOCK_STEPS = 2
STEP_UP_STEPS = 3
DIRECTIONS = ("turn_left", "turn_right")
MIN_AMPLITUDE = 1.0
MAX_AMPLITUDE = 90.0
"""The range a stored calibration may hold; :meth:`Calibration.measure` keeps 12-60."""
MAX_MEASURED = 60.0
LEGACY_RANGE = (0.05, 3.0)
"""The range of a calibration stored in units of the old yaw proxy."""
FAILURES = (
    "overshoot_before_target",
    "oscillation",
    "moved_between_prompts",
    "no_turn",
    "too_slow",
    "no_return",
    "face_lost",
    "step_identity",
    "abandoned",
)
"""The liveness rule codes a failed check reports (the verdict's and the audit's ``liveness``
field): the first six from :class:`Challenge`, ``face_lost`` and ``step_identity`` from
:mod:`tau_guard.verify`, ``abandoned`` from the hub."""


def fit_limit(fits: Sequence[float]) -> float:
    """The largest fit error a challenge frame may have: :data:`MAX_FIT`, or :data:`FIT_SLACK`
    times the median of the frontal frames' ``fits`` when that is larger (a face the generic
    head fits less well; a flat photo held frontally fits it closely)."""
    finite = [fit for fit in fits if math.isfinite(fit)]
    if not finite:
        return MAX_FIT
    return max(MAX_FIT, FIT_SLACK * statistics.median(finite))


@dataclass(frozen=True)
class Calibration:
    """How the owner's head turns: ``sign`` is the sign of the yaw change when they turn left
    (+1 or -1; it depends on the camera's orientation), ``left`` and ``right`` the size in
    degrees of each enrollment turn. ``measured`` is false for a calibration from before
    issue 127, whose amplitudes are :data:`DEFAULT_AMPLITUDE`."""

    sign: int
    left: float
    right: float
    measured: bool = True

    def amplitude(self, direction: str) -> float:
        return self.left if direction == "turn_left" else self.right

    def reach(self, direction: str) -> float:
        """The turn in degrees a step in ``direction`` must reach."""
        return max(TURN_FLOOR, TURN_FACTOR * self.amplitude(direction))

    def toward(self, direction: str, delta: float) -> float:
        """``delta`` measured in ``direction`` (positive: turned that way)."""
        return (self.sign if direction == "turn_left" else -self.sign) * delta

    def to_json(self) -> dict[str, Any]:
        return {
            "unit": "deg",
            "sign": self.sign,
            "left": round(self.left, 2),
            "right": round(self.right, 2),
            "measured": self.measured,
        }

    @classmethod
    def from_json(cls, data: Any) -> Calibration | None:
        """A stored calibration: degrees (``"unit": "deg"``), or a calibration from before issue
        127 in units of the yaw proxy, which keeps its sign and gets the default amplitudes;
        ``None`` for anything else."""
        if not isinstance(data, dict) or data.get("sign") not in (1, -1):
            return None
        degrees = data.get("unit") == "deg"
        if "unit" in data and not degrees:
            return None
        low, high = (MIN_AMPLITUDE, MAX_AMPLITUDE) if degrees else LEGACY_RANGE
        amplitudes = []
        for key in ("left", "right"):
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            if not math.isfinite(value) or not low <= value <= high:
                return None
            amplitudes.append(float(value))
        sign = int(data["sign"])
        if not degrees:
            return cls.default(sign)
        measured = data.get("measured", True)
        if not isinstance(measured, bool):
            return None
        return cls(sign, amplitudes[0], amplitudes[1], measured)

    @classmethod
    def default(cls, sign: int = 1) -> Calibration:
        """:data:`DEFAULT_AMPLITUDE` to each side (``measured`` false)."""
        return cls(sign, DEFAULT_AMPLITUDE, DEFAULT_AMPLITUDE, measured=False)

    @classmethod
    def measure(cls, left: Sequence[float], right: Sequence[float]) -> Calibration | None:
        """From the yaw changes (degrees) of the turned frames of each enrollment pose; ``None``
        when a side is missing, the two sides do not point opposite ways, or a turn is smaller
        than :data:`TURN_FLOOR` or larger than 60 degrees."""
        if not left or not right:
            return None
        left_median, right_median = statistics.median(left), statistics.median(right)
        if left_median == 0 or right_median == 0 or (left_median > 0) == (right_median > 0):
            return None
        amplitudes = (abs(left_median), abs(right_median))
        if min(amplitudes) < TURN_FLOOR or max(amplitudes) > MAX_MEASURED:
            return None
        return cls(1 if left_median > 0 else -1, amplitudes[0], amplitudes[1])


@dataclass(frozen=True)
class Prompt:
    """A progress event to publish: ``step`` and its ``deadline`` (monotonic seconds)."""

    step: str
    deadline: float | None


def draw_directions(rng: random.Random, steps: int) -> list[str]:
    return [rng.choice(DIRECTIONS) for _ in range(steps)]


class Challenge:
    """The steps after the frontal match. :meth:`feed` takes each frame's time and the one
    face in view (``None`` for a frame without one) and answers ``None`` (going on),
    ``"passed"``, ``"out_of_time"`` (the next prompt would outlast ``until``) or the code of the
    rule that failed (one of :data:`FAILURES`); :attr:`prompts` collects what to publish.
    ``baseline`` is the frontal yaw in degrees, ``limit`` the largest fit error of a frame that
    counts (:func:`fit_limit`)."""

    def __init__(
        self,
        directions: Sequence[str],
        calibration: Calibration,
        baseline: float,
        rng: random.Random,
        now: float,
        *,
        until: float | None = None,
        reserve: float = 0.0,
        limit: float = MAX_FIT,
    ) -> None:
        if not directions or any(d not in DIRECTIONS for d in directions):
            raise ValueError("a challenge needs turn_left or turn_right steps")
        self.directions = list(directions)
        self.calibration = calibration
        self.baseline = baseline
        self.rng = rng
        self.until = until
        self.reserve = reserve
        self.limit = limit
        self.index = 0
        self.previous: str | None = None
        """The direction of the step just done (``None`` before the first)."""
        self.prompts: list[Prompt] = []
        self.published_at: list[float] = []
        self.holds: list[float] = []
        self.recent: deque[float] = deque(maxlen=SMOOTHING)
        self._pause(now)

    @property
    def direction(self) -> str:
        return self.directions[self.index]

    @property
    def pending(self) -> bool:
        """A published step is not done yet (its prompt is on the owner's screen)."""
        return self.phase in ("step", "return")

    def expired(self) -> str:
        """The rule code of a published step that ran out of time (its deadline passed, or the
        frames stopped): ``no_return`` after the hold, ``too_slow`` when the turn reached its
        target, else ``no_turn``."""
        if self.phase == "return":
            return "no_return"
        return "too_slow" if self.reached else "no_turn"

    def _fits(self, now: float) -> bool:
        if self.until is None:
            return True
        last = self.index == len(self.directions) - 1
        return now + STEP_SECONDS + (self.reserve if last else 0.0) <= self.until

    def _pause(self, now: float) -> None:
        self.phase = "pause"
        self.resume = now + self.rng.uniform(*PAUSE_RANGE)
        self.deadline: float | None = None
        self.armed = False
        self.armed_at = 0.0
        self.reached = False
        self.reached_at: float | None = None
        self.hold = 0.0
        self.extreme = 0.0
        self.trend = 0
        self.reversals = 0

    def _publish(self, now: float) -> None:
        self.phase = "step"
        self.deadline = now + STEP_SECONDS
        self.published_at.append(now)
        self.prompts.append(Prompt(self.direction, self.deadline))

    def drain(self) -> list[Prompt]:
        prompts, self.prompts = self.prompts, []
        return prompts

    def delta(self, face: Face | None) -> float | None:
        """The frame's smoothed yaw change from the baseline in degrees, ``None`` for a frame
        without a face or whose landmarks do not fit a head."""
        if face is None:
            return None
        pose = face.pose
        if not pose.fits(self.limit):
            return None
        self.recent.append(pose.yaw - self.baseline)
        return statistics.median(self.recent)

    def feed(self, now: float, face: Face | None) -> str | None:
        delta = self.delta(face)
        if self.phase == "pause":
            if delta is not None and self._moved(delta):
                return "moved_between_prompts"
            if now < self.resume:
                return None
            if not self._fits(now):
                return "out_of_time"
            self._publish(now)
        assert self.deadline is not None
        if now > self.deadline:
            return self.expired()
        if delta is None:
            return None
        toward = self.calibration.toward(self.direction, delta)
        if self.phase == "step":
            return self._step(now, delta, toward)
        return self._return(now, toward)

    def _moved(self, delta: float) -> bool:
        """A head away from the baseline while no prompt is up (the return swing past the
        baseline, away from the step just done, may go further)."""
        if self.previous is None:
            return abs(delta) > IDLE_TOLERANCE
        back = self.calibration.toward(self.previous, delta)
        return back > IDLE_TOLERANCE or back < -RETURN_SWING

    def _reversed(self, value: float) -> bool:
        """Counts reversals of direction of at least :data:`SWING` degrees; ``True`` once
        there are more than :data:`MAX_REVERSALS`."""
        if self.trend == 0:
            if abs(value - self.extreme) >= SWING:
                self.trend = 1 if value > self.extreme else -1
                self.extreme = value
            return False
        if (value - self.extreme) * self.trend >= 0:
            self.extreme = value
            return False
        if abs(value - self.extreme) >= SWING:
            self.trend = -self.trend
            self.extreme = value
            self.reversals += 1
        return self.reversals > MAX_REVERSALS

    def _step(self, now: float, delta: float, toward: float) -> str | None:
        if not self.armed:
            if abs(delta) > RETURN_TOLERANCE:
                return None
            self.armed = True
            self.armed_at = self.extreme = toward
        if self._reversed(toward):
            return "oscillation"
        if toward <= min(self.armed_at, 0.0) - OPPOSITE_TOLERANCE:
            return "overshoot_before_target"
        reach = self.calibration.reach(self.direction)
        if self.reached_at is None:
            if toward < reach:
                return None
            self.reached_at = now
            if not self.reached:
                self.reached = True
                self.hold = self.rng.uniform(*HOLD_RANGE)
                self.holds.append(self.hold)
        elif toward < reach - HOLD_SLACK:
            self.reached_at = None  # the hold starts again
            return None
        if now - self.reached_at >= self.hold:
            self.phase = "return"
            self.prompts.append(Prompt("center", self.deadline))
        return None

    def _return(self, now: float, toward: float) -> str | None:
        if self._reversed(toward):
            return "oscillation"
        if toward > RETURN_TOLERANCE:
            return None
        self.previous = self.direction
        self.index += 1
        if self.index == len(self.directions):
            return "passed"
        self._pause(now)
        return None
