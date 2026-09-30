"""One face check (ADR 0008 decision 12): quality gates, the 3-of-5 match, the challenge.

**Quality gates.** A frame counts for identity when the detector score is at least 0.90 (0.75
is enough to follow the face on challenge frames), the eye distance at least 40 px (else the
live hint ``face_too_small``), the mean brightness of the face at least 60 (else ``too_dark``;
also without any face when the whole frame is that dark) and the sharpness (variance of the
Laplacian of the aligned face) at least 30. Only such a frame is embedded.

**Second faces.** A second face counts only when its eye distance is at least 45 % of the
primary face's and at least 40 px, so a photo on the wall or a person far behind does not
block. A counted second face aborts the check with ``multiple_faces``.

**Match.** Each embedding is compared with the template by cosine similarity; the check passes
when at least 3 of the last 5 quality frames reach the threshold, within
``verify_timeout_seconds`` (15). An unlock uses ``unlock_threshold`` (0.50; nothing below the
floor of 0.45 is accepted), a presence recheck and a step-up the stricter
``step_up_threshold`` (0.55).

**Which check** (:func:`policy_for`, from the worker request):

- ``unlock``: the head-turn challenge with 2 steps, unless ``unlock_liveness`` is ``none``
  (a passive match, reported as ``liveness: "passive"``);
- ``recheck``: always a passive strict match, no challenge (about 1-1.5 s);
- ``step_up``: the challenge with 3 steps, or a strict passive match when the hub says a check
  passed the challenge within ``step_up_challenge_fresh_seconds`` (``challenge_fresh``) or when
  ``step_up`` is ``none``; ``step_up = "touch_id"`` has no face part (Touch ID is issue 114).

**With the challenge** the frontal match comes first; the median yaw proxy of its frames is the
baseline. Then the steps of :class:`tau_guard.liveness.Challenge`, then a second frontal match
(3 of the last 5 frontal quality frames within 3.5 s). From the frontal match to the end
exactly one face stays in view: a counted second face aborts (``multiple_faces``), and a box
whose IoU with the previous frame's is 0.3 or less, or a face gone for more than 0.5 s, aborts
with ``spoof``. Before the first match such a jump only starts the match over.

**Verdicts.** ``match`` (with ``score``, the median of the matching similarities, and
``liveness``), ``no_match`` (quality frames but no match), ``too_dark`` or ``face_too_small``
(the last hint, when no frame ever passed the gates), ``no_face``, ``multiple_faces``,
``spoof`` or ``timeout`` (the camera stopped delivering frames before the end).

:class:`Verification` is a pure state machine over :class:`Observation` values; :func:`run_check`
drives it with a frame source and a face engine. Frames are dropped as soon as they are
analysed, and nothing here writes anything anywhere.
"""

from __future__ import annotations

import random
import statistics
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tau_guard.camera import FrameSource, opened
from tau_guard.engine import Face, FaceEngine, cosine, iou
from tau_guard.liveness import (
    STEP_UP_STEPS,
    UNLOCK_STEPS,
    Calibration,
    Challenge,
    draw_directions,
)

__all__ = [
    "MIN_BRIGHTNESS",
    "MIN_IOD",
    "MIN_SCORE",
    "MIN_SCORE_CHALLENGE",
    "MIN_SHARPNESS",
    "SECOND_FACE_RATIO",
    "STEP_UP_THRESHOLD",
    "THRESHOLD_FLOOR",
    "UNLOCK_THRESHOLD",
    "HintTracker",
    "Matcher",
    "Observation",
    "Policy",
    "PolicyError",
    "Progress",
    "Result",
    "Verification",
    "counts_as_second",
    "observe",
    "policy_for",
    "run_check",
]

MIN_SCORE = 0.90
MIN_SCORE_CHALLENGE = 0.75
MIN_IOD = 40.0
MIN_BRIGHTNESS = 60.0
MIN_SHARPNESS = 30.0
SECOND_FACE_RATIO = 0.45
NEED = 3
WINDOW = 5
UNLOCK_THRESHOLD = 0.50
STEP_UP_THRESHOLD = 0.55
THRESHOLD_FLOOR = 0.45
THRESHOLD_CEILING = 0.95
VERIFY_TIMEOUT = 15.0
TIMEOUT_RANGE = (5.0, 60.0)
MIN_IOU = 0.3
MAX_GAP = 0.5
FRONTAL = 0.15
"""How far from the baseline (``|Δp|``) a frame after the steps may be to count as frontal."""
AFTER_SECONDS = 3.5
HINT_SETTLE = 0.3
"""A live hint is published once it held for this long (no flicker on the owner's screen)."""


class PolicyError(ValueError):
    """The request asks for a check this worker refuses; ``reason`` is a verdict reason."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        super().__init__(detail)


@dataclass(frozen=True)
class Policy:
    kind: str
    threshold: float
    steps: int
    """Challenge steps; 0 for a passive match."""
    timeout: float = VERIFY_TIMEOUT

    @property
    def liveness(self) -> str:
        return "challenge" if self.steps else "passive"


def _threshold(settings: Mapping[str, Any], key: str, default: float) -> float:
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PolicyError("error", f"{key} must be a number")
    if not THRESHOLD_FLOOR <= float(value) <= THRESHOLD_CEILING:
        raise PolicyError(
            "error",
            f"{key} {value!r} is outside {THRESHOLD_FLOOR:g}-{THRESHOLD_CEILING:g}; refused",
        )
    return float(value)


def policy_for(request: Mapping[str, Any]) -> Policy:
    """The check a worker request asks for; raises :class:`PolicyError`."""
    kind = request.get("kind")
    settings = request.get("settings") or {}
    policy = request.get("policy") or {}
    if not isinstance(settings, Mapping) or not isinstance(policy, Mapping):
        raise PolicyError("error", "settings and policy must be objects")
    timeout = settings.get("verify_timeout_seconds", VERIFY_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise PolicyError("error", "verify_timeout_seconds must be a number")
    if not TIMEOUT_RANGE[0] <= float(timeout) <= TIMEOUT_RANGE[1]:
        raise PolicyError("error", "verify_timeout_seconds is out of range")
    unlock = _threshold(settings, "unlock_threshold", UNLOCK_THRESHOLD)
    strict = _threshold(settings, "step_up_threshold", STEP_UP_THRESHOLD)
    if kind == "unlock":
        steps = 0 if policy.get("unlock_liveness") == "none" else UNLOCK_STEPS
        return Policy("unlock", unlock, steps, float(timeout))
    if kind == "recheck":
        return Policy("recheck", strict, 0, float(timeout))
    if kind == "step_up":
        mode = policy.get("step_up", "face")
        if mode == "touch_id":
            raise PolicyError("touch_id_unavailable", "step_up = touch_id has no face part")
        passive = request.get("challenge_fresh") is True or mode == "none"
        return Policy("step_up", strict, 0 if passive else STEP_UP_STEPS, float(timeout))
    raise PolicyError("error", f"unknown check kind {kind!r}")


# -- one frame -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """What one frame showed. It holds numbers and, for a quality frame, the embedding;
    never the frame."""

    at: float
    primary: Face | None
    faces: int
    crowd: bool
    """A counted second face."""
    brightness: float
    sharpness: float | None = None
    embedding: tuple[float, ...] | None = None
    similarity: float | None = None
    hint: str | None = None
    quality: bool = False


def counts_as_second(primary: Face, other: Face) -> bool:
    """A second face counts when its eye distance is at least 45 % of the primary's and at
    least 40 px."""
    return other.iod >= SECOND_FACE_RATIO * primary.iod and other.iod >= MIN_IOD


def observe(
    engine: FaceEngine,
    image: Any,
    at: float,
    *,
    template: Sequence[float] | None = None,
    min_score: float = MIN_SCORE,
    embed: bool = True,
) -> Observation:
    """Detect, apply the quality gates and (for a quality frame, when ``embed``) embed; with a
    ``template`` the similarity is computed too."""
    faces = sorted(engine.detect(image), key=lambda face: face.iod, reverse=True)
    primary = faces[0] if faces else None
    crowd = primary is not None and any(counts_as_second(primary, f) for f in faces[1:])
    brightness = float(engine.brightness(image, primary))
    if primary is None:
        hint = "too_dark" if brightness < MIN_BRIGHTNESS else None
        return Observation(at, None, 0, False, brightness, hint=hint)
    if crowd:
        return Observation(at, primary, len(faces), True, brightness, hint="multiple_faces")
    if primary.score < min_score:
        return Observation(at, primary, len(faces), False, brightness)
    if primary.iod < MIN_IOD:
        return Observation(at, primary, len(faces), False, brightness, hint="face_too_small")
    if brightness < MIN_BRIGHTNESS:
        return Observation(at, primary, len(faces), False, brightness, hint="too_dark")
    if not embed:
        return Observation(at, primary, len(faces), False, brightness)
    crop = engine.crop(image, primary)
    sharpness = float(engine.sharpness(crop))
    if sharpness < MIN_SHARPNESS:
        return Observation(at, primary, len(faces), False, brightness, sharpness)
    embedding = engine.embed(crop)
    similarity = cosine(template, embedding) if template is not None else None
    return Observation(
        at, primary, len(faces), False, brightness, sharpness, embedding, similarity, None, True
    )


# -- building blocks -----------------------------------------------------------------------------


class Matcher:
    """At least ``need`` of the last ``window`` similarities reach ``threshold``."""

    def __init__(self, threshold: float, *, need: int = NEED, window: int = WINDOW) -> None:
        self.threshold = threshold
        self.need = need
        self.recent: deque[float] = deque(maxlen=window)

    def feed(self, similarity: float) -> bool:
        self.recent.append(similarity)
        return self.passed

    @property
    def passed(self) -> bool:
        return sum(1 for s in self.recent if s >= self.threshold) >= self.need

    @property
    def score(self) -> float | None:
        """The median of the similarities in the window that reach the threshold."""
        good = [s for s in self.recent if s >= self.threshold]
        return statistics.median(good) if good else None

    def reset(self) -> None:
        self.recent.clear()


class HintTracker:
    """Debounces live hints: a hint (or its absence) is published after it held for
    :data:`HINT_SETTLE` seconds."""

    def __init__(self) -> None:
        self.published: str | None = None
        self.candidate: str | None = None
        self.since = 0.0

    def update(self, now: float, hint: str | None) -> bool:
        """``True`` when :attr:`published` changed."""
        if hint != self.candidate:
            self.candidate, self.since = hint, now
        if self.candidate != self.published and now - self.since >= HINT_SETTLE:
            self.published = self.candidate
            return True
        return False


@dataclass(frozen=True)
class Progress:
    """A progress line for the hub: ``step`` (tau-core's ``PROGRESS_STEPS``), ``hint`` (a
    verdict reason) and ``deadline`` in monotonic seconds."""

    step: str
    hint: str | None
    deadline: float | None


@dataclass(frozen=True)
class Result:
    ok: bool
    reason: str
    score: float | None = None
    liveness: str | None = None


# -- the check -----------------------------------------------------------------------------------


class Verification:
    """One check as a state machine: :meth:`feed` each :class:`Observation`, publish
    :meth:`drain`, stop at the first :class:`Result` (or call :meth:`end` when the frames stop).
    The phases are ``look`` (the frontal match), ``challenge`` and ``after`` (the second
    frontal match)."""

    def __init__(
        self,
        policy: Policy,
        template: Sequence[float],
        calibration: Calibration,
        rng: random.Random,
    ) -> None:
        self.policy = policy
        self.template = tuple(template)
        self.calibration = calibration
        self.rng = rng
        self.phase = "look"
        self.start: float | None = None
        self.deadline = 0.0
        self.matcher = Matcher(policy.threshold)
        self.yaws: list[float] = []
        self.baseline = 0.0
        self.before: float | None = None
        self.challenge: Challenge | None = None
        self.after: Matcher | None = None
        self.hints = HintTracker()
        self.step = "look"
        self.last_face: Face | None = None
        self.last_face_at = 0.0
        self.frames = 0
        self.saw_face = False
        self.saw_quality = False
        self.last_hint: str | None = None
        self.directions: list[str] = []
        self._outbox: list[Progress] = []

    @property
    def min_score(self) -> float:
        return MIN_SCORE_CHALLENGE if self.phase == "challenge" else MIN_SCORE

    @property
    def wants_embedding(self) -> bool:
        return self.phase in ("look", "after")

    def drain(self) -> list[Progress]:
        outbox, self._outbox = self._outbox, []
        return outbox

    def _publish(self, step: str, deadline: float | None, hint: str | None = None) -> None:
        self.step = step
        self._outbox.append(Progress(step, hint, deadline))

    def _begin(self, now: float) -> None:
        self.start = now
        self.deadline = now + self.policy.timeout
        self._publish("look", self.deadline)

    def feed(self, obs: Observation) -> Result | None:
        now = obs.at
        if self.start is None:
            self._begin(now)
        self.frames += 1
        if obs.hint is not None:
            self.last_hint = obs.hint
        if obs.crowd:
            return Result(False, "multiple_faces")
        face = obs.primary
        if face is not None and self.phase == "challenge" and face.score < MIN_SCORE_CHALLENGE:
            face = None
        broken = self._continuity(now, face)
        if broken is not None:
            return broken
        if self.phase == "look":
            return self._look(now, obs, face)
        if self.phase == "challenge":
            return self._challenge(now, face)
        return self._after(now, obs, face)

    def _continuity(self, now: float, face: Face | None) -> Result | None:
        """Exactly one face, and the same one, from the frontal match on; before it a jump
        only starts the match over."""
        previous, previous_at = self.last_face, self.last_face_at
        if face is not None:
            self.saw_face = True
            self.last_face, self.last_face_at = face, now
        if previous is None:
            return None
        broken = now - previous_at > MAX_GAP
        if face is not None and iou(previous, face) <= MIN_IOU:
            broken = True
        if not broken:
            return None
        if self.phase == "look":
            self.matcher.reset()
            self.yaws.clear()
            return None
        return Result(False, "spoof")

    def _look(self, now: float, obs: Observation, face: Face | None) -> Result | None:
        if self.hints.update(now, obs.hint):
            self._publish("look", self.deadline, self.hints.published)
        if obs.quality and face is not None and obs.similarity is not None:
            self.saw_quality = True
            self.yaws.append(face.yaw)
            if self.matcher.feed(obs.similarity):
                self.before = self.matcher.score
                if not self.policy.steps:
                    return Result(True, "match", self.before, "passive")
                self.baseline = statistics.median(self.yaws[-WINDOW:])
                self.directions = draw_directions(self.rng, self.policy.steps)
                self.challenge = Challenge(
                    self.directions, self.calibration, self.baseline, self.rng, now
                )
                self.phase = "challenge"
                return None
        if now >= self.deadline:
            return Result(False, self._look_failure())
        return None

    def _look_failure(self) -> str:
        if self.saw_quality:
            return "no_match"
        if self.last_hint in ("too_dark", "face_too_small"):
            return self.last_hint
        return "timeout" if self.saw_face else "no_face"

    def _challenge(self, now: float, face: Face | None) -> Result | None:
        assert self.challenge is not None
        outcome = self.challenge.feed(now, face)
        for prompt in self.challenge.drain():
            self._publish(prompt.step, prompt.deadline)
        if outcome == "spoof":
            return Result(False, "spoof")
        if outcome == "passed":
            self.phase = "after"
            self.deadline = now + AFTER_SECONDS
            self.after = Matcher(self.policy.threshold)
            self._publish("center", self.deadline)
        return None

    def _after(self, now: float, obs: Observation, face: Face | None) -> Result | None:
        assert self.after is not None
        frontal = face is not None and abs(face.yaw - self.baseline) <= FRONTAL
        if obs.quality and frontal and obs.similarity is not None:
            if self.after.feed(obs.similarity):
                scores = [s for s in (self.before, self.after.score) if s is not None]
                return Result(True, "match", min(scores) if scores else None, "challenge")
        if now >= self.deadline:
            return Result(False, "no_match")
        return None

    def end(self) -> Result:
        """The frames stopped (the camera's time limit or a read failure) before a verdict."""
        if self.frames == 0:
            return Result(False, "camera_busy")
        if self.phase == "look" and not self.saw_face:
            return Result(False, self.last_hint if self.last_hint == "too_dark" else "no_face")
        return Result(False, "timeout")


Explain = Callable[[Observation, str, "Verification"], None]


def run_check(
    policy: Policy,
    template: Sequence[float],
    calibration: Calibration,
    engine: FaceEngine,
    source: FrameSource,
    *,
    rng: random.Random,
    emit: Callable[[Progress], None],
    explain: Explain | None = None,
) -> Result:
    """Open ``source``, run one :class:`Verification` over its frames and close it again."""
    machine = Verification(policy, template, calibration, rng)
    result: Result | None = None
    with opened(source) as frames:
        for frame in frames:
            obs = observe(
                engine,
                frame.image,
                frame.at,
                template=machine.template,
                min_score=machine.min_score,
                embed=machine.wants_embedding,
            )
            del frame
            phase = machine.phase
            result = machine.feed(obs)
            if explain is not None:
                explain(obs, phase, machine)
            for progress in machine.drain():
                emit(progress)
            if result is not None:
                break
        if result is None:
            result = machine.end()
    return result
