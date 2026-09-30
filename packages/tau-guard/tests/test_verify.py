"""Quality gates, the second-face rule, the 3-of-5 match, thresholds and the check a request
asks for, over synthetic YuNet rows and embeddings."""

from __future__ import annotations

import random

import pytest
from tau_guard.camera import Frame
from tau_guard.config import SettingsError, parse_settings
from tau_guard.engine import Face
from tau_guard.liveness import Calibration
from tau_guard.testing import (
    OWNER,
    STRANGER,
    FakeEngine,
    FakeFrameSource,
    Scene,
    SimulatedUser,
    face_row,
    variant,
)
from tau_guard.verify import (
    HINT_SETTLE,
    MIN_SCORE,
    HintTracker,
    Matcher,
    Policy,
    PolicyError,
    Progress,
    counts_as_second,
    observe,
    policy_for,
    run_check,
)

CAL = Calibration(1, 0.45, 0.45)


def scene(
    rows: list[list[float]] | None = None,
    *,
    embeddings: list | None = None,
    brightness: float = 120.0,
    sharpness: float = 150.0,
) -> Scene:
    rows = rows if rows is not None else [face_row()]
    embeddings = embeddings or [variant(OWNER, i) for i in range(len(rows))]
    return Scene(rows, embeddings, brightness, sharpness)


def look(image: Scene, **kw):
    return observe(FakeEngine(), image, 0.0, template=OWNER, **kw)


# -- quality gates -------------------------------------------------------------------------------


def test_a_good_frame_is_a_quality_frame() -> None:
    obs = look(scene())
    assert obs.quality and obs.hint is None and obs.similarity is not None
    assert obs.similarity > 0.8


def test_the_detector_score_gate() -> None:
    assert not look(scene([face_row(score=MIN_SCORE - 0.01)])).quality
    assert look(scene([face_row(score=MIN_SCORE)])).quality
    assert look(scene([face_row(score=0.8)]), min_score=0.75, embed=True).quality


def test_a_small_face_hints_face_too_small() -> None:
    obs = look(scene([face_row(iod=39)]))
    assert not obs.quality and obs.hint == "face_too_small"
    assert look(scene([face_row(iod=40)])).quality


def test_a_dark_frame_hints_too_dark() -> None:
    obs = look(scene(brightness=59))
    assert not obs.quality and obs.hint == "too_dark"
    assert look(scene(brightness=60)).quality
    empty = look(scene([], brightness=30))
    assert empty.primary is None and empty.hint == "too_dark"
    assert look(scene([], brightness=100)).hint is None


def test_a_blurred_frame_is_no_quality_frame() -> None:
    obs = look(scene(sharpness=29))
    assert not obs.quality and obs.sharpness == 29 and obs.embedding is None
    assert look(scene(sharpness=30)).quality


def test_nothing_is_embedded_when_embedding_is_not_wanted() -> None:
    engine = FakeEngine()
    obs = observe(engine, scene(), 0.0, template=OWNER, embed=False)
    assert not obs.quality and engine.embedded == 0


# -- second faces --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("primary_iod", "second_iod", "counted"),
    [
        (80, 30, False),  # 37 % of the primary
        (80, 36, False),  # 45 % but below 40 px
        (80, 40, True),  # 50 % and 40 px
        (120, 50, False),  # 42 %: a face on a poster behind
        (120, 54, True),  # 45 %
        (60, 45, True),
        (200, 80, False),  # close owner, person far behind
    ],
)
def test_the_second_face_rule_at_several_scales(
    primary_iod: float, second_iod: float, counted: bool
) -> None:
    primary = face_row(cx=320, iod=primary_iod)
    second = face_row(cx=80, cy=150, iod=second_iod)
    assert counts_as_second(Face.from_row(primary), Face.from_row(second)) is counted
    obs = look(scene([second, primary]))  # the order of detection does not matter
    assert obs.crowd is counted
    assert obs.primary is not None and obs.primary.iod == pytest.approx(primary_iod)
    assert (obs.hint == "multiple_faces") is counted


def frames(images: list[Scene], start: float = 100.0, fps: float = 30.0) -> list[Frame]:
    return [Frame(image, start + i / fps) for i, image in enumerate(images)]


def check(images: list[Scene], policy: Policy, *, template=OWNER) -> tuple:
    published: list[Progress] = []
    result = run_check(
        policy,
        template,
        CAL,
        FakeEngine(),
        FakeFrameSource(frames(images)),
        rng=random.Random(1),
        emit=published.append,
    )
    return result, published


PASSIVE = Policy("recheck", 0.55, 0, timeout=5)


def test_a_counted_second_face_aborts_with_multiple_faces() -> None:
    images = [scene()] * 2 + [scene([face_row(), face_row(cx=90, cy=160, iod=60)])]
    result, _ = check(images, PASSIVE)
    assert result.reason == "multiple_faces" and not result.ok


def test_background_small_faces_are_ignored() -> None:
    images = [scene([face_row(), face_row(cx=60, cy=100, iod=24)])] * 10
    result, _ = check(images, PASSIVE)
    assert result.ok and result.liveness == "passive"


# -- the match -----------------------------------------------------------------------------------


def with_similarity(target: float, seed: int) -> tuple[float, ...]:
    """An embedding whose cosine with OWNER is ``target``."""
    import math

    from tau_guard.engine import cosine, normalise

    overlap = cosine(STRANGER, OWNER)
    orth = normalise(a - overlap * b for a, b in zip(STRANGER, OWNER, strict=True))
    sin = math.sqrt(max(0.0, 1 - target * target))
    return normalise(target * o + sin * p for o, p in zip(OWNER, orth, strict=True))


def sims(values: list[float]) -> list[Scene]:
    return [scene(embeddings=[with_similarity(v, i)]) for i, v in enumerate(values)]


def test_three_of_the_last_five_quality_frames() -> None:
    result, _ = check(sims([0.6, 0.3, 0.6, 0.3, 0.6]), PASSIVE)
    assert result.ok and result.score == pytest.approx(0.6)
    result, _ = check(sims([0.6, 0.3, 0.3, 0.3, 0.6, 0.3, 0.6] + [0.3] * 200), PASSIVE)
    assert not result.ok and result.reason == "no_match"  # never 3 within 5
    result, _ = check(sims([0.6, 0.3, 0.3, 0.3, 0.6, 0.6, 0.6]), PASSIVE)
    assert result.ok


def test_the_threshold_is_inclusive() -> None:
    assert check(sims([0.55] * 3), PASSIVE)[0].ok
    assert check(sims([0.549] * 200), PASSIVE)[0].reason == "no_match"


def test_a_stranger_does_not_match() -> None:
    images = [scene(embeddings=[variant(STRANGER, i)]) for i in range(200)]
    result, published = check(images, PASSIVE)
    assert result.reason == "no_match"
    assert published[0].step == "look" and published[0].deadline == pytest.approx(105.0)


def test_failure_reasons_when_no_frame_passes() -> None:
    assert check([scene([], brightness=100)] * 200, PASSIVE)[0].reason == "no_face"
    assert check([scene([], brightness=20)] * 200, PASSIVE)[0].reason == "too_dark"
    assert check([scene([face_row(iod=30)])] * 200, PASSIVE)[0].reason == "face_too_small"
    assert check([scene(brightness=40)] * 200, PASSIVE)[0].reason == "too_dark"
    assert check([scene(sharpness=5)] * 200, PASSIVE)[0].reason == "timeout"
    assert check([], PASSIVE)[0].reason == "camera_busy"
    assert check([scene([], brightness=100)] * 10, PASSIVE)[0].reason == "no_face"


def test_a_box_jump_before_the_match_starts_over() -> None:
    left = [scene([face_row(cx=200)], embeddings=[variant(OWNER, i)]) for i in range(2)]
    right = [scene([face_row(cx=500)], embeddings=[variant(OWNER, i + 9)]) for i in range(3)]
    result, _ = check(left + right, PASSIVE)
    assert result.ok  # matched on the three frames after the jump, not across it
    result, _ = check(left + right[:2], PASSIVE)
    assert not result.ok


def test_hints_are_published_once_they_settle() -> None:
    images = [scene(brightness=30)] * 30 + [scene()] * 3
    result, published = check(images, Policy("unlock", 0.5, 0, timeout=5))
    assert result.ok
    hints = [p.hint for p in published]
    assert hints[0] is None and "too_dark" in hints
    assert all(p.step == "look" for p in published)
    tracker = HintTracker()
    assert not tracker.update(0.0, "too_dark")
    assert tracker.update(HINT_SETTLE, "too_dark") and tracker.published == "too_dark"
    assert not tracker.update(HINT_SETTLE + 0.1, None)


def test_the_matcher() -> None:
    matcher = Matcher(0.5)
    assert not matcher.feed(0.9) and not matcher.feed(0.9)
    assert matcher.feed(0.2) is False and matcher.feed(0.7) is True
    assert matcher.score == pytest.approx(0.9)
    matcher.reset()
    assert matcher.score is None


# -- which check -------------------------------------------------------------------------------


def request(kind: str, **extra) -> dict:
    return {"kind": kind, "settings": extra.pop("settings", {}), "policy": {}, **extra}


def test_the_check_each_kind_gets() -> None:
    unlock = policy_for(request("unlock"))
    assert (unlock.threshold, unlock.steps, unlock.liveness) == (0.5, 2, "challenge")
    passive = policy_for({**request("unlock"), "policy": {"unlock_liveness": "none"}})
    assert (passive.steps, passive.liveness) == (0, "passive")
    recheck = policy_for(request("recheck"))
    assert (recheck.threshold, recheck.steps) == (0.55, 0)
    step_up = policy_for(request("step_up"))
    assert (step_up.threshold, step_up.steps) == (0.55, 3)
    fresh = policy_for(request("step_up", challenge_fresh=True))
    assert (fresh.threshold, fresh.steps) == (0.55, 0)
    none = policy_for({**request("step_up"), "policy": {"step_up": "none"}})
    assert none.steps == 0
    with pytest.raises(PolicyError) as touch:
        policy_for({**request("step_up"), "policy": {"step_up": "touch_id"}})
    assert touch.value.reason == "touch_id_unavailable"
    timed = policy_for(request("unlock", settings={"verify_timeout_seconds": 20}))
    assert timed.timeout == 20


def test_thresholds_below_the_floor_are_refused() -> None:
    with pytest.raises(PolicyError) as caught:
        policy_for(request("unlock", settings={"unlock_threshold": 0.44}))
    assert caught.value.reason == "error"
    with pytest.raises(PolicyError):
        policy_for(request("step_up", settings={"step_up_threshold": 0.3}))
    with pytest.raises(PolicyError):
        policy_for(request("unlock", settings={"unlock_threshold": "0.5"}))
    assert policy_for(request("unlock", settings={"unlock_threshold": 0.45})).threshold == 0.45
    with pytest.raises(SettingsError):
        parse_settings({"unlock_threshold": 0.44})
    with pytest.raises(PolicyError):
        policy_for(request("dance"))


def test_a_recheck_is_a_quick_passive_strict_match() -> None:
    user = SimulatedUser(duration=5)
    result = run_check(
        policy_for(request("recheck")),
        OWNER,
        CAL,
        FakeEngine(),
        user.source(),
        rng=random.Random(1),
        emit=user.on_progress,
    )
    assert result.ok and result.liveness == "passive"
    assert user.now() - user.start < 0.2  # three frames at 30 fps


# -- the camera's time limit -----------------------------------------------------------------------


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _Capture:
    """A ``cv2.VideoCapture`` over :class:`Frame` values: each read moves the camera's clock to
    the frame's time (warm-up reads come first)."""

    def __init__(self, clock: _Clock, frames) -> None:
        self.clock = clock
        self.frames = iter(frames)
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 (cv2's name)
        return True

    def read(self):
        frame = next(self.frames, None)
        if frame is None:
            return False, None
        self.clock.t = frame.at
        return True, frame.image

    def set(self, *args) -> bool:
        return True

    def release(self) -> None:
        self.released = True


class _Devices:
    def devices(self) -> list:
        from tau_guard.camera import BUILTIN_TYPE, Device

        return [Device("47B4B64B-0000-4000-8000-000000000001", "Camera", BUILTIN_TYPE, "bltn")]


class _Allowed:
    def status(self) -> int:
        return 3

    def request(self) -> None:
        raise AssertionError("no permission request when access is allowed")


def capped_camera(frames, *, start: float = 100.0):
    """The real :class:`~tau_guard.camera.AVFoundationCamera` (its 20 s cap included) over
    synthetic frames from ``start`` on."""
    from tau_guard.camera import AVFoundationCamera

    clock = _Clock(start)
    capture = _Capture(clock, frames)
    camera = AVFoundationCamera(
        devices=_Devices(), permission=_Allowed(), capture=lambda index: capture, clock=clock
    )
    return camera, capture


def endless(image_at, *, start: float = 100.0, fps: float = 30.0, seconds: float = 90.0):
    return (Frame(image_at(i), start + (i + 1) / fps) for i in range(int(seconds * fps)))


@pytest.mark.parametrize("kind", ["recheck", "unlock", "step_up"])
@pytest.mark.parametrize("timeout", [15, 30, 60])
def test_a_verify_timeout_beyond_the_camera_cap_still_counts_a_stranger(
    kind: str, timeout: int
) -> None:
    from tau_guard.camera import MAX_OPEN_SECONDS

    camera, capture = capped_camera(endless(lambda i: scene(embeddings=[variant(STRANGER, i)])))
    policy = policy_for(request(kind, settings={"verify_timeout_seconds": timeout}))
    published: list[Progress] = []
    result = run_check(
        policy, OWNER, CAL, FakeEngine(), camera, rng=random.Random(1), emit=published.append
    )
    assert result.reason == "no_match" and not result.ok  # counted, whatever the timeout
    assert camera.open_seconds is not None
    assert camera.open_seconds <= MAX_OPEN_SECONDS + 0.05 and capture.released
    assert published[0].deadline <= camera.stops_at  # the prompt shows the real end


def test_a_hint_survives_the_camera_cap() -> None:
    camera, _ = capped_camera(endless(lambda i: scene([face_row(iod=30)])))
    policy = policy_for(request("unlock", settings={"verify_timeout_seconds": 30}))
    result = run_check(policy, OWNER, CAL, FakeEngine(), camera, rng=random.Random(1), emit=print)
    assert result.reason == "face_too_small"
    camera, _ = capped_camera(endless(lambda i: scene(brightness=20)))
    result = run_check(policy, OWNER, CAL, FakeEngine(), camera, rng=random.Random(1), emit=print)
    assert result.reason == "too_dark"


def late_owner(match_after: float, **switches) -> SimulatedUser:
    """An owner the camera cannot see well (blurred) for ``match_after`` seconds."""

    class Late(SimulatedUser):
        def scene(self) -> Scene:
            image = super().scene()
            if self.t - self.start < match_after:
                image.sharpness = 5.0
            return image

    return Late(duration=40, **switches)


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize(
    ("match_after", "steps", "reason", "turns"),
    [
        (4.0, 3, "match", 3),
        (9.0, 3, "timeout", 2),  # the last step and the match after it would outlast the camera
        (13.0, 2, "timeout", 1),
        (16.5, 2, "timeout", 0),  # not even the first step fits
    ],
)
def test_no_prompt_is_published_that_the_camera_cap_would_cut(
    seed: int, match_after: float, steps: int, reason: str, turns: int
) -> None:
    user = late_owner(match_after)
    camera, _ = capped_camera(user.frames(), start=user.start - 0.2)
    published: list[Progress] = []

    def emit(progress: Progress) -> None:
        published.append(progress)
        user.on_progress(progress)

    policy = Policy("unlock" if steps == 2 else "step_up", 0.5, steps, timeout=30)
    result = run_check(policy, OWNER, CAL, FakeEngine(), camera, rng=random.Random(seed), emit=emit)
    assert result.reason == reason
    prompts = [p for p in published if p.step.startswith("turn_")]
    assert len(prompts) == turns
    assert all(p.deadline is not None and p.deadline <= camera.stops_at for p in prompts)


def test_a_quick_owner_passes_under_the_camera_cap() -> None:
    for steps in (2, 3):
        user = SimulatedUser(duration=40)
        camera, _ = capped_camera(user.frames(), start=user.start - 0.2)
        result = run_check(
            Policy("step_up" if steps == 3 else "unlock", 0.55, steps),
            OWNER,
            CAL,
            FakeEngine(),
            camera,
            rng=random.Random(4),
            emit=user.on_progress,
        )
        assert result.ok and result.liveness == "challenge"


def drive(user: SimulatedUser, policy: Policy, stop, *, seed: int = 3):
    """A :class:`Verification` of the owner's template, fed ``user``'s frames one by one like
    :func:`run_check`, ended with :meth:`Verification.end` as soon as ``stop(machine)`` holds
    (the frames stopped)."""
    from tau_guard.verify import Verification

    machine = Verification(policy, OWNER, CAL, random.Random(seed))
    engine = FakeEngine()
    for frame in user.frames():
        if stop(machine):
            return machine, machine.end()
        obs = observe(
            engine,
            frame.image,
            frame.at,
            template=machine.template,
            min_score=machine.min_score,
            embed=machine.embeds,
        )
        result = machine.feed(obs)
        for progress in machine.drain():
            user.on_progress(progress)
        if result is not None:
            return machine, result
    return machine, machine.end()


CHALLENGE = Policy("unlock", 0.5, 2)


def test_frames_that_stop_during_a_published_step_count_as_spoof() -> None:
    def pending(machine) -> bool:
        return machine.phase == "challenge" and machine.challenge.pending

    for index in (0, 1):
        machine, result = drive(
            SimulatedUser(),
            CHALLENGE,
            lambda m, index=index: pending(m) and m.challenge.index == index,
        )
        assert result.reason == "spoof"


def test_frames_that_stop_between_steps_or_after_them() -> None:
    def pause(machine) -> bool:
        challenge = machine.challenge
        return machine.phase == "challenge" and challenge.phase == "pause" and challenge.index == 1

    assert drive(SimulatedUser(), CHALLENGE, pause)[1].reason == "timeout"
    assert drive(SimulatedUser(), CHALLENGE, lambda m: m.phase == "after")[1].reason == "no_match"


def test_frames_that_stop_during_the_frontal_match() -> None:
    def quality(machine) -> bool:
        return machine.saw_quality

    owner = drive(SimulatedUser(), CHALLENGE, quality)[1]
    assert owner.reason == "timeout"  # every quality frame matched: nothing to count
    stranger = drive(SimulatedUser(embedding=STRANGER), CHALLENGE, quality)[1]
    assert stranger.reason == "no_match"  # counted, however early the frames stopped
    dark = drive(SimulatedUser(brightness=30), CHALLENGE, lambda m: m.frames >= 20)[1]
    assert dark.reason == "too_dark"
