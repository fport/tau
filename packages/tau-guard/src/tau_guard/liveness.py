"""The head-turn challenge (ADR 0008 decision 12), against a printed photo or a phone clip.

**The signal.** The yaw proxy ``p = (nose_x - eye_mid_x) / eye distance``
(:attr:`tau_guard.engine.Face.yaw`). A real head turn moves the nose out of the eyes' plane and
changes ``p``; a flat photo turned about the vertical axis scales every x distance alike and
leaves ``p`` where it was. Everything is measured relative to a **baseline**, the median ``p``
of the attempt's frontal frames, so a camera that sees the owner a little from the side still
works. Enrollment calibrates the sign of a left turn and the owner's amplitude to each side
(:class:`Calibration`).

**A step** (``turn_left`` or ``turn_right``, drawn at random; unlock asks for 2, step-up for 3):

1. A random pause of 0.3-0.9 s, then the prompt is published with its deadline: 3.5 s from the
   publication.
2. The step arms on the first frame near the baseline (``|Δp| <= 0.10``), so a head that is
   already turned when the prompt appears (a clip that happens to be turned) does not count.
3. ``Δp`` in the asked direction reaches ``max(0.20, 0.6 x the calibrated amplitude)`` and stays
   there for a random 0.4-0.8 s (a dip below starts the hold again). Then ``center`` is published.
4. The head returns within 0.10 of the baseline: the step passed.

**Failing.** ``Δp`` more than 0.15 the other way at any time in a step (the wrong direction, or
swinging past the centre on the way back) aborts at once with ``spoof``; so does a step that is
not done by its deadline (no turn, no hold, no return, too late). Every challenge failure is a
counted failure (and so is abandoning a published step: :mod:`tau_guard.state`), so a looping
clip cannot skip the prompts it does not fit.

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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from tau_guard.engine import Face

__all__ = [
    "DIRECTIONS",
    "HOLD_RANGE",
    "OVERSHOOT",
    "PAUSE_RANGE",
    "RETURN_TOLERANCE",
    "STEP_SECONDS",
    "STEP_UP_STEPS",
    "TURN_FACTOR",
    "TURN_FLOOR",
    "UNLOCK_STEPS",
    "Calibration",
    "Challenge",
    "Prompt",
    "draw_directions",
]

TURN_FLOOR = 0.20
TURN_FACTOR = 0.6
RETURN_TOLERANCE = 0.10
OVERSHOOT = 0.15
HOLD_RANGE = (0.4, 0.8)
PAUSE_RANGE = (0.3, 0.9)
STEP_SECONDS = 3.5
UNLOCK_STEPS = 2
STEP_UP_STEPS = 3
DIRECTIONS = ("turn_left", "turn_right")
MIN_AMPLITUDE = 0.05
MAX_AMPLITUDE = 3.0


@dataclass(frozen=True)
class Calibration:
    """How the owner's head turns: ``sign`` is the sign of ``Δp`` when they turn left (+1 or
    -1; it depends on the camera's orientation), ``left`` and ``right`` the size of ``|Δp|``
    of each enrollment turn."""

    sign: int
    left: float
    right: float

    def amplitude(self, direction: str) -> float:
        return self.left if direction == "turn_left" else self.right

    def reach(self, direction: str) -> float:
        """The ``Δp`` a step in ``direction`` must reach."""
        return max(TURN_FLOOR, TURN_FACTOR * self.amplitude(direction))

    def toward(self, direction: str, delta: float) -> float:
        """``delta`` measured in ``direction`` (positive: turned that way)."""
        return (self.sign if direction == "turn_left" else -self.sign) * delta

    def to_json(self) -> dict[str, Any]:
        return {"sign": self.sign, "left": round(self.left, 4), "right": round(self.right, 4)}

    @classmethod
    def from_json(cls, data: Any) -> Calibration | None:
        if not isinstance(data, dict) or data.get("sign") not in (1, -1):
            return None
        amplitudes = []
        for key in ("left", "right"):
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            if not math.isfinite(value) or not MIN_AMPLITUDE <= value <= MAX_AMPLITUDE:
                return None
            amplitudes.append(float(value))
        return cls(int(data["sign"]), amplitudes[0], amplitudes[1])

    @classmethod
    def measure(cls, left: Sequence[float], right: Sequence[float]) -> Calibration | None:
        """From the ``Δp`` of the turned frames of each enrollment pose; ``None`` when a side is
        missing, the two sides do not point opposite ways, or a turn is too small to use."""
        if not left or not right:
            return None
        left_median, right_median = statistics.median(left), statistics.median(right)
        if left_median == 0 or right_median == 0 or (left_median > 0) == (right_median > 0):
            return None
        amplitudes = (abs(left_median), abs(right_median))
        if min(amplitudes) < TURN_FLOOR or max(amplitudes) > MAX_AMPLITUDE:
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
    ``"passed"``, ``"spoof"`` or ``"out_of_time"`` (the next prompt would outlast ``until``);
    :attr:`prompts` collects what to publish."""

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
    ) -> None:
        if not directions or any(d not in DIRECTIONS for d in directions):
            raise ValueError("a challenge needs turn_left or turn_right steps")
        self.directions = list(directions)
        self.calibration = calibration
        self.baseline = baseline
        self.rng = rng
        self.until = until
        self.reserve = reserve
        self.index = 0
        self.prompts: list[Prompt] = []
        self.published_at: list[float] = []
        self.holds: list[float] = []
        self._pause(now)

    @property
    def direction(self) -> str:
        return self.directions[self.index]

    @property
    def pending(self) -> bool:
        """A published step is not done yet (its prompt is on the owner's screen)."""
        return self.phase in ("step", "return")

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
        self.reached_at: float | None = None
        self.hold = 0.0

    def _publish(self, now: float) -> None:
        self.phase = "step"
        self.deadline = now + STEP_SECONDS
        self.published_at.append(now)
        self.prompts.append(Prompt(self.direction, self.deadline))

    def drain(self) -> list[Prompt]:
        prompts, self.prompts = self.prompts, []
        return prompts

    def feed(self, now: float, face: Face | None) -> str | None:
        if self.phase == "pause":
            if now < self.resume:
                return None
            if not self._fits(now):
                return "out_of_time"
            self._publish(now)
        assert self.deadline is not None
        if now > self.deadline:
            return "spoof"
        if face is None:
            return None
        delta = face.yaw - self.baseline
        toward = self.calibration.toward(self.direction, delta)
        if toward < -OVERSHOOT:
            return "spoof"
        if self.phase == "step":
            return self._step(now, delta, toward)
        if abs(delta) <= RETURN_TOLERANCE:  # phase "return"
            self.index += 1
            if self.index == len(self.directions):
                return "passed"
            self._pause(now)
        return None

    def _step(self, now: float, delta: float, toward: float) -> None:
        if not self.armed:
            if abs(delta) > RETURN_TOLERANCE:
                return None
            self.armed = True
        if toward < self.calibration.reach(self.direction):
            self.reached_at = None
            return None
        if self.reached_at is None:
            self.reached_at = now
            self.hold = self.rng.uniform(*HOLD_RANGE)
            self.holds.append(self.hold)
        if now - self.reached_at >= self.hold:
            self.phase = "return"
            self.prompts.append(Prompt("center", self.deadline))
        return None
