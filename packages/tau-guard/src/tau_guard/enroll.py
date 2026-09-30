"""Guided enrollment (ADR 0008 decision 12): five poses, 10-20 samples, a yaw calibration.

The owner follows five prompts (tau-core's progress steps ``look``, ``turn_left``,
``turn_right``, ``look_up``, ``look_down``), about 15-20 s at most, with live hints through the
same progress lines: ``too_dark``, ``face_too_small`` (too far) and ``multiple_faces`` (one face
only) as hints, ``turn_more`` as a step when a turn is too small.

- **Samples.** A frame that passes the quality gates of :mod:`tau_guard.verify`, shows one face
  and is within 0.35 of the frontal yaw becomes a sample, unless its cosine similarity to a
  sample already kept is above 0.97 (too alike). At most 4 per pose, 10-20 in all.
- **Calibration.** The ``look`` pose sets the baseline (median yaw proxy of its samples). In the
  ``turn_left`` and ``turn_right`` poses, frames whose ``Δp`` reaches 0.20 are the turn (in the
  right pose only those on the other side of the left turn: the way back does not count), and a
  turn pose moves on once the turn was seen for 0.5 s; the medians of both sides give the sign
  and the amplitudes (:meth:`Calibration.measure`).
- **Consistency.** Each sample's cosine similarity to the renormalised mean of the others
  (leave-one-out) must be at least 0.55; otherwise the samples do not agree (another face, bad
  light) and the enrollment fails with ``no_match``.
- **Adding** (``tau guard enroll --add``, other light): the new samples must match the existing
  template (0.50), then they join the old ones (at most 40, the newest kept), the leave-one-out
  check runs over all of them, and the calibration is averaged with the old one.

Failures: ``no_face`` (no face ever), the last live hint when too few samples came
(``too_dark``, ``face_too_small``, ``multiple_faces``), ``timeout`` (too few samples, or no clear
turn to each side) and ``no_match`` (the leave-one-out check, or ``--add`` samples of someone
else). :class:`Enrollment` is a pure state machine over :class:`~tau_guard.verify.Observation`
values; :func:`run_enrollment` drives it. The worker runs it only after LocalAuthentication
passed, and stores the result (:mod:`tau_guard.store`).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from tau_guard.camera import FrameSource, opened
from tau_guard.engine import FaceEngine, cosine, mean_vector
from tau_guard.liveness import TURN_FLOOR, Calibration
from tau_guard.verify import HintTracker, Observation, Progress, observe

__all__ = [
    "DIVERSITY",
    "LOO_MIN",
    "MAX_SAMPLES",
    "MIN_SAMPLES",
    "POSES",
    "EnrollResult",
    "Enrollment",
    "leave_one_out",
    "run_enrollment",
]

POSES = ("look", "turn_left", "turn_right", "look_up", "look_down")
FIRST_POSE_SECONDS = 5.0
POSE_SECONDS = 3.0
POSE_SAMPLES = 4
MIN_SAMPLES = 10
MAX_SAMPLES = 20
MAX_TOTAL = 40
"""Samples kept after ``--add``."""
DIVERSITY = 0.97
LOO_MIN = 0.55
ADD_MATCH = 0.50
SAMPLE_GAP = 0.15
MAX_SAMPLE_TURN = 0.35
TURN_MORE_AFTER = 1.5
TURN_HOLD = 0.5
"""How long a turn pose must see the turn before it moves on."""


@dataclass(frozen=True)
class EnrollResult:
    ok: bool
    reason: str
    samples: tuple[tuple[float, ...], ...] = ()
    calibration: Calibration | None = None
    consistency: float | None = None
    """The lowest leave-one-out similarity."""


def leave_one_out(samples: Sequence[Sequence[float]]) -> list[float]:
    """Each sample's cosine similarity to the renormalised mean of the others."""
    scores = []
    for index, sample in enumerate(samples):
        others = [s for i, s in enumerate(samples) if i != index]
        scores.append(cosine(sample, mean_vector(others)) if others else 1.0)
    return scores


@dataclass
class _Pose:
    name: str
    started: float
    deadline: float
    samples: int = 0
    turned: list[float] = field(default_factory=list)
    turned_since: float | None = None
    turned_last: float | None = None
    nudged: bool = False


class Enrollment:
    """The guided capture. :meth:`feed` each observation (``observe(..., embed=True)``),
    publish :meth:`drain`; a :class:`EnrollResult` comes back when the last pose is over (or
    call :meth:`end` when the frames stop). ``existing`` is the template of an ``--add`` run
    (its vector, samples and calibration)."""

    def __init__(
        self,
        *,
        existing_vector: Sequence[float] | None = None,
        existing_samples: Sequence[Sequence[float]] = (),
        existing_calibration: Calibration | None = None,
    ) -> None:
        self.existing_vector = tuple(existing_vector) if existing_vector is not None else None
        self.existing_samples = [tuple(s) for s in existing_samples]
        self.existing_calibration = existing_calibration
        self.samples: list[tuple[float, ...]] = []
        self.baseline_yaws: list[float] = []
        self.baseline: float | None = None
        self.turns: dict[str, list[float]] = {"turn_left": [], "turn_right": []}
        self.pose_index = -1
        self.pose: _Pose | None = None
        self.hints = HintTracker()
        self.last_sample_at = -1e9
        self.saw_face = False
        self.last_hint: str | None = None
        self._outbox: list[Progress] = []

    def drain(self) -> list[Progress]:
        outbox, self._outbox = self._outbox, []
        return outbox

    def _next_pose(self, now: float) -> bool:
        """Start the next pose; ``False`` after the last one."""
        self.pose_index += 1
        if self.pose_index >= len(POSES):
            self.pose = None
            return False
        seconds = FIRST_POSE_SECONDS if self.pose_index == 0 else POSE_SECONDS
        self.pose = _Pose(POSES[self.pose_index], now, now + seconds)
        self.hints = HintTracker()
        self._outbox.append(Progress(self.pose.name, None, self.pose.deadline))
        return True

    def feed(self, obs: Observation) -> EnrollResult | None:
        now = obs.at
        if self.pose is None and self.pose_index < 0:
            self._next_pose(now)
        pose = self.pose
        assert pose is not None
        if obs.hint is not None:
            self.last_hint = obs.hint
        if self.hints.update(now, obs.hint):
            self._outbox.append(Progress(pose.name, self.hints.published, pose.deadline))
        face = obs.primary
        self.saw_face = self.saw_face or face is not None
        if face is not None and not obs.crowd:
            if pose.name in self.turns and self.baseline is not None:
                self._turn(now, pose, face.yaw - self.baseline)
            if obs.quality and obs.embedding is not None:
                self._sample(now, pose, face.yaw, obs.embedding)
        if self._pose_done(now, pose):
            if pose.name == "look" and self.baseline is None:
                return self.finish()  # nothing to measure the turns against
            if not self._next_pose(now):
                return self.finish()
        return None

    def _turn(self, now: float, pose: _Pose, delta: float) -> None:
        left = self.turns["turn_left"]
        if pose.name == "turn_right" and left and (delta > 0) == (statistics.median(left) > 0):
            return  # still on the way back from the left turn
        if abs(delta) >= TURN_FLOOR:
            pose.turned.append(delta)
            self.turns[pose.name].append(delta)
            if pose.turned_since is None:
                pose.turned_since = now
            pose.turned_last = now
        elif not pose.nudged and now - pose.started >= TURN_MORE_AFTER and not pose.turned:
            pose.nudged = True
            self._outbox.append(Progress("turn_more", None, pose.deadline))

    def _sample(self, now: float, pose: _Pose, yaw: float, embedding: Sequence[float]) -> None:
        if pose.name == "look":
            self.baseline_yaws.append(yaw)
            self.baseline = statistics.median(self.baseline_yaws)
        if self.baseline is None or abs(yaw - self.baseline) > MAX_SAMPLE_TURN:
            return
        if pose.samples >= POSE_SAMPLES or len(self.samples) >= MAX_SAMPLES:
            return
        if now - self.last_sample_at < SAMPLE_GAP:
            return
        vector = tuple(embedding)
        if any(cosine(vector, kept) > DIVERSITY for kept in self.samples):
            return
        self.samples.append(vector)
        pose.samples += 1
        self.last_sample_at = now

    def _pose_done(self, now: float, pose: _Pose) -> bool:
        if now >= pose.deadline:
            return True
        if pose.name in self.turns:
            since, last = pose.turned_since, pose.turned_last
            return since is not None and last is not None and last - since >= TURN_HOLD
        return pose.samples >= POSE_SAMPLES

    def end(self) -> EnrollResult:
        """The frames stopped before the last pose was over."""
        return self.finish()

    def _short(self) -> str:
        if not self.saw_face:
            return "no_face"
        if self.last_hint in ("too_dark", "face_too_small", "multiple_faces"):
            return self.last_hint
        return "timeout"

    def finish(self) -> EnrollResult:
        if len(self.samples) < MIN_SAMPLES:
            return EnrollResult(False, self._short())
        measured = Calibration.measure(self.turns["turn_left"], self.turns["turn_right"])
        calibration = self._calibration(measured)
        if calibration is None:
            return EnrollResult(False, "timeout")
        samples = list(self.samples)
        if self.existing_vector is not None:
            if cosine(mean_vector(samples), self.existing_vector) < ADD_MATCH:
                return EnrollResult(False, "no_match")
            samples = (self.existing_samples + samples)[-MAX_TOTAL:]
        scores = leave_one_out(samples)
        if min(scores) < LOO_MIN:
            return EnrollResult(False, "no_match", consistency=min(scores))
        return EnrollResult(True, "match", tuple(samples), calibration, min(scores))

    def _calibration(self, measured: Calibration | None) -> Calibration | None:
        old = self.existing_calibration
        if old is None:
            return measured
        if measured is None:
            return old
        if measured.sign != old.sign:
            return None
        left, right = (old.left + measured.left) / 2, (old.right + measured.right) / 2
        return Calibration(old.sign, left, right)


def run_enrollment(
    engine: FaceEngine,
    source: FrameSource,
    *,
    emit: Callable[[Progress], None],
    machine: Enrollment | None = None,
) -> EnrollResult:
    """Open ``source``, run the guided capture over its frames and close it again."""
    machine = machine or Enrollment()
    result: EnrollResult | None = None
    with opened(source) as frames:
        for frame in frames:
            obs = observe(engine, frame.image, frame.at, embed=True)
            del frame
            result = machine.feed(obs)
            for progress in machine.drain():
                emit(progress)
            if result is not None:
                break
        if result is None:
            result = machine.end()
    return result
