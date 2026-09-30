"""The head-turn challenge in degrees over synthetic YuNet rows (the 3D head model projected
through the camera model): a simulated owner passes, also from a seat off to the side, with a
return swing, natural sway and detector noise; the wrong direction, an overshoot before the
target, a looping head shake, no hold, no return, a late step, a second face, a jump, a flat
photo and a face swapped in place all fail, each with its rule code."""

from __future__ import annotations

import math
import random
from typing import Any

import pytest
from tau_guard.camera import Frame
from tau_guard.engine import Face
from tau_guard.liveness import (
    DEFAULT_AMPLITUDE,
    FAILURES,
    HOLD_RANGE,
    IDLE_TOLERANCE,
    MAX_FIT,
    OPPOSITE_TOLERANCE,
    PAUSE_RANGE,
    RETURN_SWING,
    STEP_SECONDS,
    TURN_FLOOR,
    Calibration,
    Challenge,
    draw_directions,
    fit_limit,
)
from tau_guard.testing import (
    OWNER,
    STRANGER,
    FakeEngine,
    FakeFrameSource,
    Scene,
    SimulatedUser,
    face_row,
    project_head,
    variant,
)
from tau_guard.verify import STEP_MATCHES, Policy, Progress, Result, run_check

CAL = Calibration(sign=1, left=30.0, right=30.0)


def attempt(
    user: SimulatedUser,
    *,
    steps: int = 2,
    calibration: Calibration | None = None,
    seed: int = 3,
    threshold: float = 0.5,
) -> tuple[Result, list[tuple[float, Progress]]]:
    published: list[tuple[float, Progress]] = []

    def emit(progress: Progress) -> None:
        published.append((user.now(), progress))
        user.on_progress(progress)

    cal = calibration or Calibration(user.sign, 30.0, 30.0)
    result = run_check(
        Policy("unlock" if steps == 2 else "step_up", threshold, steps),
        user.embedding,
        cal,
        FakeEngine(),
        user.source(),
        rng=random.Random(seed),
        emit=emit,
    )
    return result, published


def failed(result: Result, rule: str) -> bool:
    return not result.ok and result.reason == "spoof" and result.liveness == rule


@pytest.mark.parametrize("seed", range(8))
def test_a_simulated_owner_passes_the_unlock_challenge(seed: int) -> None:
    result, published = attempt(SimulatedUser(), seed=seed)
    assert result.ok and result.reason == "match" and result.liveness == "challenge"
    turns = [p.step for _, p in published if p.step.startswith("turn_")]
    assert len(turns) == 2
    assert result.score is not None and result.score >= 0.5


def test_step_up_asks_for_three_steps_and_all_eight_sequences_occur() -> None:
    seen = set()
    for seed in range(40):
        result, published = attempt(SimulatedUser(), steps=3, seed=seed)
        assert result.ok, seed
        seen.add(tuple(p.step for _, p in published if p.step.startswith("turn_")))
    assert all(len(sequence) == 3 for sequence in seen) and len(seen) == 8


@pytest.mark.parametrize("sign", [1, -1])
def test_the_calibrated_sign_decides_what_left_means(sign: int) -> None:
    assert attempt(SimulatedUser(sign=sign))[0].ok
    wrong = attempt(SimulatedUser(sign=sign), calibration=Calibration(-sign, 30.0, 30.0))[0]
    assert failed(wrong, "overshoot_before_target")


@pytest.mark.parametrize("frontal", [15.0, -15.0, 25.0])
def test_the_baseline_is_relative_to_the_frontal_frames(frontal: float) -> None:
    assert attempt(SimulatedUser(frontal=frontal))[0].ok


@pytest.mark.parametrize("seed", range(6))
def test_a_natural_owner_passes_with_a_return_swing_sway_and_noise(seed: int) -> None:
    """The return swings 8 degrees past the centre before it settles, the head sways a little
    all the time and the detector jitters by a pixel: none of it is a spoof."""
    user = SimulatedUser(
        amplitude=20.0, overshoot=8.0, sway=2.5, jitter=1.0, iod=60, frame_seed=seed
    )
    result, _ = attempt(user, seed=seed)
    assert result.ok, result
    result, _ = attempt(
        SimulatedUser(amplitude=20.0, overshoot=8.0, sway=2.5, jitter=1.0, frame_seed=seed),
        steps=3,
        seed=seed,
    )
    assert result.ok, result


def test_prompts_carry_a_deadline_four_seconds_after_publication() -> None:
    _, published = attempt(SimulatedUser())
    assert STEP_SECONDS == 4.0
    for at, progress in published:
        if progress.step.startswith("turn_"):
            assert progress.deadline == pytest.approx(at + STEP_SECONDS)


def test_a_random_pause_comes_before_each_prompt() -> None:
    challenge = Challenge(["turn_left", "turn_right"], CAL, 0.0, random.Random(5), 10.0)
    assert PAUSE_RANGE[0] <= challenge.resume - 10.0 <= PAUSE_RANGE[1]
    pauses = set()
    for seed in range(20):
        c = Challenge(["turn_left"], CAL, 0.0, random.Random(seed), 0.0)
        pauses.add(round(c.resume, 3))
    assert len(pauses) > 10


# -- one step, frame by frame --------------------------------------------------------------------


def head(yaw: float = 0.0, **kw: Any) -> Face:
    return Face.from_row(face_row(yaw=yaw, **kw))


def run_frames(challenge: Challenge, yaws: list[float], *, start: float, fps: float = 30.0):
    t = start
    for yaw in yaws:
        outcome = challenge.feed(t, head(yaw))
        if outcome is not None:
            return outcome, t
        t += 1 / fps
    return None, t


def pause_frames(challenge: Challenge, yaw: float = 0.0) -> list[float]:
    return [yaw] * (math.ceil(challenge.resume * 30) + 1)


def test_a_step_passes_after_reach_hold_and_return() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = pause_frames(challenge) + [20.0] * 30 + [0.0] * 5
    outcome, _ = run_frames(challenge, yaws, start=0.0)
    assert outcome == "passed"
    assert HOLD_RANGE == (0.3, 0.6) and HOLD_RANGE[0] <= challenge.holds[-1] <= HOLD_RANGE[1]


def test_the_reach_is_the_larger_of_the_floor_and_half_the_calibrated_turn() -> None:
    assert CAL.reach("turn_left") == pytest.approx(15.0)
    assert Calibration(1, 20.0, 20.0).reach("turn_right") == TURN_FLOOR == 12.0
    assert Calibration.default().reach("turn_left") == TURN_FLOOR
    wide = Calibration(1, 40.0, 40.0)  # needs 20: an 17 degree turn never reaches
    challenge = Challenge(["turn_left"], wide, 0.0, random.Random(1), 0.0)
    outcome, _ = run_frames(challenge, pause_frames(challenge) + [17.0] * 200, start=0.0)
    assert outcome == "no_turn"


def test_a_turn_that_sags_a_little_keeps_its_hold() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    wobble = [16.0, 13.5, 15.0, 13.0, 16.0, 14.0] * 5  # dips below 15 but not below 12
    outcome, _ = run_frames(challenge, pause_frames(challenge) + wobble + [0.0] * 3, start=0.0)
    assert outcome == "passed"


def test_moving_the_other_way_before_the_target_aborts_at_once() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = pause_frames(challenge) + [-(OPPOSITE_TOLERANCE + 1)] * 3
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "overshoot_before_target" and t < challenge.deadline


def test_a_small_wrong_way_turn_fails_at_the_deadline_as_no_turn() -> None:
    challenge = Challenge(["turn_right"], CAL, 0.0, random.Random(1), 0.0)
    yaws = pause_frames(challenge) + [5.0] * 200  # right is negative here; +5 is the wrong way
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "no_turn" and t > challenge.deadline


def test_swinging_past_the_centre_on_the_way_back_is_expected() -> None:
    """The failure of the 2026-09-30 try: coming back from a turn, a real head swings past the
    baseline. That ends the step (it came back) and the swing may go on in the pause."""
    challenge = Challenge(["turn_right", "turn_left"], CAL, 0.0, random.Random(2), 0.0)
    swing = [-20.0] * 25 + [-8.0, 4.0, 12.0, 16.0, 14.0, 9.0, 5.0, 2.0] + [0.0] * 10
    outcome, _ = run_frames(challenge, pause_frames(challenge) + swing, start=0.0)
    assert outcome is None and challenge.index == 1 and challenge.previous == "turn_right"
    for step in ("turn_right", "turn_left"):  # a direct Challenge each way
        single = Challenge([step], CAL, 0.0, random.Random(4), 0.0)
        sign = -1 if step == "turn_right" else 1
        yaws = pause_frames(single) + [sign * 22.0] * 25 + [-sign * 15.0] * 3
        assert run_frames(single, yaws, start=0.0)[0] == "passed"


def test_a_head_already_turned_when_the_prompt_appears_does_not_count() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    pause = math.ceil(challenge.resume * 30)
    # a small move in the pause (allowed), then already on the way (8, beyond the 6 degrees
    # that arm a step) when the prompt shows, then turned: the step never arms
    yaws = [0.0] * (pause - 3) + [8.0] * 3 + [8.0] + [25.0] * 300
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "no_turn" and challenge.deadline is not None and t > challenge.deadline


@pytest.mark.parametrize("yaw", [IDLE_TOLERANCE + 2, -(IDLE_TOLERANCE + 2)])
def test_moving_before_the_first_prompt_aborts(yaw: float) -> None:
    challenge = Challenge(["turn_left", "turn_right"], CAL, 0.0, random.Random(1), 0.0)
    outcome, _ = run_frames(challenge, [0.0, 3.0] + [yaw] * 3, start=0.0)
    assert outcome == "moved_between_prompts" and challenge.prompts == []


def test_small_natural_movement_while_waiting_is_fine() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    assert run_frames(challenge, [7.0, -7.0, 5.0, -6.0] * 4, start=0.0)[0] is None


def test_the_pause_after_a_step_allows_the_return_swing_but_not_a_new_turn() -> None:
    def after_a_left_step() -> tuple[Challenge, float]:
        challenge = Challenge(["turn_left", "turn_left"], CAL, 0.0, random.Random(2), 0.0)
        yaws = pause_frames(challenge) + [20.0] * 25 + [0.0] * 2
        outcome, t = run_frames(challenge, yaws, start=0.0)
        assert outcome is None and challenge.phase == "pause" and challenge.index == 1
        assert challenge.resume - t > 0.2  # the frames below all come before the next prompt
        return challenge, t

    def pause(challenge: Challenge, t: float, yaw: float) -> str | None:
        return run_frames(challenge, [yaw] * 5, start=t + 1 / 30)[0]

    assert pause(*after_a_left_step(), -(RETURN_SWING - 2)) is None  # the swing past the centre
    assert pause(*after_a_left_step(), -(RETURN_SWING + 3)) == "moved_between_prompts"
    # a clip that turns left again before the next prompt
    assert pause(*after_a_left_step(), IDLE_TOLERANCE + 5) == "moved_between_prompts"


def test_turning_back_and_forth_within_one_step_is_an_oscillation() -> None:
    wide = Calibration(1, 40.0, 40.0)  # the target is 20; the clip only touches it
    challenge = Challenge(["turn_left"], wide, 0.0, random.Random(1), 0.0)
    shake = ([0.0] * 2 + [14.0] * 2 + [22.0] * 2 + [14.0] * 2) * 4
    outcome, t = run_frames(challenge, pause_frames(challenge) + shake, start=0.0)
    assert outcome == "oscillation" and t < challenge.deadline


def test_a_hold_that_ends_before_its_time_is_too_slow() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = pause_frames(challenge) + [20.0] * 5 + [9.0] * 300  # reached, then sagged for good
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "too_slow" and t > challenge.deadline


def test_no_return_after_the_hold() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = pause_frames(challenge) + [20.0] * 300
    outcome, _ = run_frames(challenge, yaws, start=0.0)
    assert outcome == "no_return" and challenge.phase == "return"


def test_frames_whose_landmarks_do_not_fit_a_head_count_for_nothing() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0, limit=MAX_FIT)
    t = 0.0
    for _ in range(pause_frames(challenge).__len__()):
        assert challenge.feed(t, head(0.0)) is None
        t += 1 / 30
    photo = Face.from_row(face_row(yaw=65.0, flat=True))  # reads a big yaw, fits no head
    assert photo.pose.fit > MAX_FIT and abs(photo.pose.yaw) > TURN_FLOOR
    outcome = None
    while outcome is None:
        outcome = challenge.feed(t, photo)
        t += 1 / 30
    assert outcome == "no_turn"


def test_the_fit_limit_follows_a_face_that_fits_the_model_less_well() -> None:
    assert fit_limit([]) == MAX_FIT
    assert fit_limit([0.01, 0.02, 0.03]) == MAX_FIT
    assert fit_limit([0.08, 0.09, 0.1]) == pytest.approx(0.135)
    assert fit_limit([math.inf]) == MAX_FIT


def test_directions_come_from_the_rng() -> None:
    assert draw_directions(random.Random(1), 3) == draw_directions(random.Random(1), 3)
    assert {tuple(draw_directions(random.Random(s), 2)) for s in range(30)} == {
        ("turn_left", "turn_left"),
        ("turn_left", "turn_right"),
        ("turn_right", "turn_left"),
        ("turn_right", "turn_right"),
    }


# -- whole checks ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("switches", "reason", "rule"),
    [
        ({"wrong_way": True}, "spoof", "overshoot_before_target"),
        ({"hold": False}, "spoof", "too_slow"),
        ({"returns": False}, "spoof", "no_return"),
        ({"turn": False}, "spoof", "no_turn"),
        ({"amplitude": 8.0}, "spoof", "no_turn"),
        ({"reaction": STEP_SECONDS + 0.2}, "spoof", "no_turn"),
        ({"photo": True, "amplitude": 45.0}, "spoof", "no_turn"),
        ({"second_face": (102.0, 120.0)}, "multiple_faces", None),
        ({"jump_at": 102.5}, "spoof", "face_lost"),
        ({"stranger_after_centers": 1}, "spoof", "step_identity"),  # someone else turns
        ({"stranger_after_centers": 2}, "no_match", None),  # ... or is there after the steps
        ({"stranger_after_centers": 3}, "no_match", None),
    ],
)
def test_the_challenge_fails(switches: dict, reason: str, rule: str | None) -> None:
    result, _ = attempt(SimulatedUser(**switches))
    assert not result.ok and result.reason == reason and result.liveness == rule, result
    assert rule is None or rule in FAILURES


def test_a_head_shaking_clip_fails() -> None:
    class Shaking(SimulatedUser):
        def _move(self, dt: float) -> None:
            self.yaw = 30.0 * math.sin(2 * math.pi * 0.5 * (self.t - self.start) + self.phase)

    for seed in range(40):
        user = Shaking(frame_seed=seed)
        user.phase = seed  # type: ignore[attr-defined]
        result, _ = attempt(user, seed=seed)
        assert not result.ok and result.reason == "spoof", seed


def looping_clip(seed: int, *, hold: float = 1.0, amplitude: float = 25.0):
    """A phone replaying a clip of the owner: centre 0.9 s, a turn left and right with ``hold``
    seconds at ``amplitude`` degrees, again and again, from a random point of the loop."""
    segments = [("c", 0.9), ("L", 0.25), ("Lh", hold), ("Lb", 0.25)]
    segments += [("c", 0.9), ("R", 0.25), ("Rh", hold), ("Rb", 0.25)]
    total = sum(length for _, length in segments)
    offset = random.Random(seed).uniform(0, total)

    def yaw(t: float) -> float:
        t = (t + offset) % total
        for name, length in segments:
            if t < length:
                side = amplitude if name[0] == "L" else -amplitude
                ease = 0.5 - 0.5 * math.cos(math.pi * t / length)
                if name == "c":
                    return 0.0
                if name.endswith("h"):
                    return side
                return side * (ease if len(name) == 1 else 1 - ease)
            t -= length
        return 0.0

    def frames():
        for i in range(int(20 * 30)):
            t = i / 30
            row = face_row(yaw=yaw(t), iod=60)
            yield Frame(Scene([row], [variant(OWNER, seed * 100003 + i)]), 100.0 + t)

    return frames


def test_a_looping_clip_of_natural_turns_passes_only_a_few_unlocks() -> None:
    """The documented limit (ADR 0008, decision 23): a clip of natural turns passes when the
    random prompts happen to match it. Measured over 400 runs it passes about 10 % of the 2-step
    unlocks; this keeps it from creeping up."""
    passed = 0
    for seed in range(60):
        result = run_check(
            Policy("unlock", 0.5, 2),
            OWNER,
            CAL,
            FakeEngine(),
            FakeFrameSource(looping_clip(seed)),
            rng=random.Random(seed),
            emit=lambda progress: None,
        )
        passed += result.ok
        assert result.ok or result.reason == "spoof"
    assert passed <= 12


def first_prompt_at(seed: int = 3) -> float:
    _, published = attempt(SimulatedUser(), seed=seed)
    return next(at for at, p in published if p.step.startswith("turn_"))


@pytest.mark.parametrize(("offset", "length", "ok"), [(0.4, 0.1, True), (0.4, 0.3, False)])
def test_a_face_may_vanish_only_briefly_during_the_challenge(
    offset: float, length: float, ok: bool
) -> None:
    start = first_prompt_at() + offset  # while the head turns for the first step
    result, _ = attempt(SimulatedUser(gap=(start, start + length)))
    assert result.ok is ok and (ok or failed(result, "face_lost")), result


def test_a_gap_before_the_frontal_match_only_starts_it_over() -> None:
    result, _ = attempt(SimulatedUser(gap=(100.05, 100.4)))
    assert result.ok


class PhotoThenStranger(SimulatedUser):
    """The owner's photo for the frontal checks, swapped in place for a live stranger who
    follows the prompts, and back to the photo for the frontal match after the steps."""

    def scene(self):  # type: ignore[no-untyped-def]
        image = super().scene()
        turns = any(step.startswith("turn_") for _, step in self.steps)
        centers = sum(1 for _, step in self.steps if step == "center")
        photo = not turns or (centers >= 3 and abs(self.yaw - self.frontal) < 3.0)
        person = self.embedding if photo else STRANGER
        image.embeddings[0] = variant(person, self.frame_seed * 100003 + self.index)
        return image


@pytest.mark.parametrize("seed", range(12))
def test_a_photo_for_the_frontal_checks_and_someone_else_turning_fails(seed: int) -> None:
    for steps in (2, 3):
        result, _ = attempt(PhotoThenStranger(frame_seed=seed), steps=steps, seed=seed)
        assert failed(result, "step_identity"), (seed, steps, result)


def test_the_owner_s_frames_near_the_baseline_are_checked_during_the_steps() -> None:
    engine = FakeEngine()
    user = SimulatedUser()
    result = run_check(
        Policy("unlock", 0.5, 2),
        OWNER,
        CAL,
        engine,
        user.source(),
        rng=random.Random(3),
        emit=user.on_progress,
    )
    assert result.ok
    frames = int((user.now() - user.start) * user.fps)
    assert 3 + STEP_MATCHES * 2 + 3 <= engine.embedded < frames  # turned frames are skipped


@pytest.mark.parametrize("amplitude", [30.0, 45.0, 60.0])
def test_a_flat_photo_turned_about_the_vertical_axis_fails_the_challenge(amplitude: float):
    """Someone turns a printed photo by the asked angle and back: it barely reads as a turn,
    and turned far enough it stops fitting a head at all."""
    for steps in (2, 3):
        result, _ = attempt(SimulatedUser(photo=True, amplitude=amplitude), steps=steps)
        assert not result.ok and result.reason == "spoof", result
        assert result.liveness in ("no_turn", "overshoot_before_target", "too_slow"), result


def test_a_small_background_face_does_not_disturb_the_challenge() -> None:
    result, _ = attempt(SimulatedUser(second_face=(100.0, 130.0), second_iod=30.0))
    assert result.ok
    result, _ = attempt(SimulatedUser(second_face=(100.0, 130.0), second_iod=35.0))
    assert result.ok  # 35 px is 44 % of 80 px and below 40 px


# -- the owner's try of 2026-09-30 -----------------------------------------------------------------


def old_proxy(face: Face) -> float:
    """The yaw proxy the challenge used before issue 127."""
    eye_mid = (face.right_eye[0] + face.left_eye[0]) / 2
    return (face.nose[0] - eye_mid) / face.iod


OWNER_SEAT = {"frontal": 12.0, "iod": 50.0}
"""The owner's seat on 2026-09-30 (``verify --explain``): eyes 44-58 px apart and a frontal
yaw proxy of about +0.13 (a seat a little to the side), which is 12 degrees with this head."""


def test_the_owner_s_seat_matches_the_recorded_numbers() -> None:
    face = Face.from_row(face_row(yaw=OWNER_SEAT["frontal"], iod=OWNER_SEAT["iod"]))
    assert old_proxy(face) == pytest.approx(0.13, abs=0.01)
    assert face.yaw == pytest.approx(12.0, abs=0.5)


@pytest.mark.parametrize(
    ("turn", "lean", "passes"),
    [
        (14.0, 8.0 / 14.0, True),  # a real turn made partly by tilting into it
        (6.5, 0.0, False),  # a small pure turn
    ],
)
def test_the_owner_s_recorded_turn(turn: float, lean: float, passes: bool) -> None:
    """The recorded "turn right" moved the old proxy by only about 0.07 (+0.14 to +0.07), far
    below its 0.20 rule. Two heads give exactly that dip: a real 14 degree turn with the head
    tilting 8 degrees into it (the proxy mixes the tilt into the yaw; the pose does not), and a
    small 6.5 degree pure turn. The head pose measures the first as the real turn it is (it
    passes) and the second as too small (``no_turn``: now the verdict says so)."""
    frontal = Face.from_row(face_row(yaw=OWNER_SEAT["frontal"], iod=50))
    turned = Face.from_row(face_row(yaw=OWNER_SEAT["frontal"] - turn, roll=-lean * turn, iod=50))
    assert old_proxy(turned) - old_proxy(frontal) == pytest.approx(-0.07, abs=0.01)
    assert turned.yaw - frontal.yaw == pytest.approx(-turn, abs=0.5)
    results = []
    for seed in range(6):
        user = SimulatedUser(
            **OWNER_SEAT, amplitude=turn, lean=lean, overshoot=5.0, jitter=0.6, frame_seed=seed
        )
        result, _ = attempt(user, seed=seed, calibration=Calibration.default())
        results.append(result)
    if passes:
        assert all(result.ok for result in results), results
    else:
        assert all(failed(result, "no_turn") for result in results), results


# -- calibration -----------------------------------------------------------------------------------


def test_calibration_json_and_measurement() -> None:
    assert Calibration.from_json(CAL.to_json()) == CAL
    assert CAL.to_json() == {
        "unit": "deg",
        "sign": 1,
        "left": 30.0,
        "right": 30.0,
        "measured": True,
    }
    for bad in (
        None,
        {},
        {"unit": "deg", "sign": 2, "left": 30, "right": 30},
        {"unit": "deg", "sign": 1, "left": "x", "right": 30},
        {"unit": "deg", "sign": 1, "left": 0.5, "right": 30},  # below 1 degree
        {"unit": "deg", "sign": 1, "left": 120, "right": 30},
        {"unit": "deg", "sign": 1, "left": 30, "right": 30, "measured": "yes"},
        {"unit": "rad", "sign": 1, "left": 0.5, "right": 0.5},
    ):
        assert Calibration.from_json(bad) is None, bad
    measured = Calibration.measure([24.0, 26.0, 25.0], [-18.0, -20.0])
    assert measured == Calibration(1, 25.0, pytest.approx(19.0))
    flipped = Calibration.measure([-24.0], [21.0])
    assert flipped is not None and flipped.sign == -1
    assert Calibration.measure([24.0], [20.0]) is None  # both sides the same way
    assert Calibration.measure([24.0], []) is None
    assert Calibration.measure([8.0], [-24.0]) is None  # too small to use
    assert Calibration.measure([70.0], [-24.0]) is None  # not a head turn


def test_a_calibration_from_before_degrees_keeps_its_sign_and_uses_defaults() -> None:
    """Templates stored with the yaw proxy keep working: no re-enrollment is forced."""
    for sign in (1, -1):
        old = Calibration.from_json({"sign": sign, "left": 0.42, "right": 0.38})
        assert old == Calibration(sign, DEFAULT_AMPLITUDE, DEFAULT_AMPLITUDE, measured=False)
        assert old is not None and old.reach("turn_left") == TURN_FLOOR
        assert Calibration.from_json(old.to_json()) == old
    assert Calibration.from_json({"sign": 1, "left": 0.01, "right": 0.3}) is None
    assert Calibration.from_json({"sign": 1, "left": 25.0, "right": 25.0}) is None


def test_the_camera_model_is_the_one_the_pose_uses() -> None:
    points = project_head(yaw=0.0, iod=80.0)
    assert math.dist(points[0], points[1]) == pytest.approx(80.0)
    assert points[2] == pytest.approx((320.0, 240.0))
