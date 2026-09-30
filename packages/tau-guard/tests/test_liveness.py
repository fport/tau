"""The head-turn challenge over synthetic YuNet rows: a simulated owner passes; the wrong
direction, an overshoot, no hold, no return, a late step, a second face, an IoU break, a
flat photo and a face swapped in place all fail."""

from __future__ import annotations

import random
from typing import Any

import pytest
from tau_guard.engine import Face
from tau_guard.liveness import (
    HOLD_RANGE,
    OVERSHOOT,
    PAUSE_RANGE,
    STEP_SECONDS,
    TURN_FLOOR,
    Calibration,
    Challenge,
    draw_directions,
)
from tau_guard.testing import FakeEngine, SimulatedUser, face_row
from tau_guard.verify import Policy, Progress, Result, run_check

CAL = Calibration(sign=1, left=0.45, right=0.45)


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

    cal = calibration or Calibration(user.sign, 0.45, 0.45)
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
    wrong = attempt(SimulatedUser(sign=sign), calibration=Calibration(-sign, 0.45, 0.45))[0]
    assert not wrong.ok and wrong.reason == "spoof"


def test_the_baseline_is_relative_to_the_frontal_frames() -> None:
    assert attempt(SimulatedUser(frontal=0.18))[0].ok
    assert attempt(SimulatedUser(frontal=-0.2))[0].ok


def test_prompts_carry_a_deadline_three_and_a_half_seconds_after_publication() -> None:
    _, published = attempt(SimulatedUser())
    for at, progress in published:
        if progress.step.startswith("turn_"):
            assert progress.deadline == pytest.approx(at + STEP_SECONDS)


def test_a_random_pause_comes_before_each_prompt() -> None:
    challenge = Challenge(["turn_left", "turn_right"], CAL, 0.0, random.Random(5), 10.0)
    assert PAUSE_RANGE[0] <= challenge.until - 10.0 <= PAUSE_RANGE[1]
    pauses = set()
    for seed in range(20):
        c = Challenge(["turn_left"], CAL, 0.0, random.Random(seed), 0.0)
        pauses.add(round(c.until, 3))
    assert len(pauses) > 10


def frontal(yaw: float = 0.0, **kw: Any) -> Face:
    return Face.from_row(face_row(yaw=yaw, **kw))


def run_frames(challenge: Challenge, yaws: list[float], *, start: float, fps: float = 30.0):
    t = start
    for yaw in yaws:
        outcome = challenge.feed(t, frontal(yaw))
        if outcome is not None:
            return outcome, t
        t += 1 / fps
    return None, t


def test_a_step_passes_after_reach_hold_and_return() -> None:
    rng = random.Random(1)
    challenge = Challenge(["turn_left"], CAL, 0.0, rng, 0.0)
    pause = challenge.until
    yaws = [0.0] * int(pause * 30 + 2) + [0.35] * 30 + [0.0] * 5
    outcome, _ = run_frames(challenge, yaws, start=0.0)
    assert outcome == "passed"
    assert HOLD_RANGE[0] <= challenge.holds[-1] <= HOLD_RANGE[1]


def test_the_reach_is_the_larger_of_the_floor_and_the_calibrated_share() -> None:
    assert CAL.reach("turn_left") == pytest.approx(0.27)
    assert Calibration(1, 0.2, 0.2).reach("turn_right") == TURN_FLOOR
    wide = Calibration(1, 0.6, 0.6)  # needs 0.36: a 0.30 turn never reaches
    challenge = Challenge(["turn_left"], wide, 0.0, random.Random(1), 0.0)
    yaws = [0.0] * 40 + [0.30] * 200
    outcome, _ = run_frames(challenge, yaws, start=0.0)
    assert outcome == "spoof"


def test_an_overshoot_the_other_way_aborts_at_once() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = [0.0] * 40 + [-(OVERSHOOT + 0.02)]
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "spoof" and t < challenge.deadline


def test_a_small_wrong_way_turn_fails_at_the_deadline() -> None:
    challenge = Challenge(["turn_right"], CAL, 0.0, random.Random(1), 0.0)
    yaws = [0.0] * 40 + [0.12] * 200  # right is negative here; +0.12 is the wrong way
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "spoof" and t > challenge.deadline


def test_swinging_past_the_centre_on_the_way_back_aborts() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = [0.0] * 40 + [0.35] * 30 + [-0.2]
    outcome, _ = run_frames(challenge, yaws, start=0.0)
    assert outcome == "spoof"


def test_a_head_already_turned_when_the_prompt_appears_does_not_count() -> None:
    challenge = Challenge(["turn_left"], CAL, 0.0, random.Random(1), 0.0)
    yaws = [0.4] * 300  # turned all along: the step never arms
    outcome, t = run_frames(challenge, yaws, start=0.0)
    assert outcome == "spoof" and t > challenge.deadline


def test_directions_come_from_the_rng() -> None:
    assert draw_directions(random.Random(1), 3) == draw_directions(random.Random(1), 3)
    assert {tuple(draw_directions(random.Random(s), 2)) for s in range(30)} == {
        ("turn_left", "turn_left"),
        ("turn_left", "turn_right"),
        ("turn_right", "turn_left"),
        ("turn_right", "turn_right"),
    }


@pytest.mark.parametrize(
    ("switches", "reason"),
    [
        ({"wrong_way": True}, "spoof"),
        ({"hold": False}, "spoof"),
        ({"returns": False}, "spoof"),
        ({"turn": False}, "spoof"),
        ({"reaction": STEP_SECONDS + 0.2}, "spoof"),
        ({"photo": True}, "spoof"),
        ({"second_face": (102.0, 120.0)}, "multiple_faces"),
        ({"jump_at": 102.5}, "spoof"),
        ({"stranger_after_centers": 3}, "no_match"),
    ],
)
def test_the_challenge_fails(switches: dict, reason: str) -> None:
    result, _ = attempt(SimulatedUser(**switches))
    assert not result.ok and result.reason == reason, result


def test_a_flat_photo_turned_about_the_vertical_axis_keeps_its_yaw_proxy() -> None:
    straight = Face.from_row(face_row(yaw=0.05))
    for scale in (0.9, 0.7, 0.5):
        turned = Face.from_row(face_row(yaw=0.05, scale_x=scale))
        assert turned.yaw == pytest.approx(straight.yaw)
    result, _ = attempt(SimulatedUser(photo=True, amplitude=0.6), steps=3)
    assert result.reason == "spoof"


def test_a_small_background_face_does_not_disturb_the_challenge() -> None:
    result, _ = attempt(SimulatedUser(second_face=(100.0, 130.0), second_iod=30.0))
    assert result.ok
    result, _ = attempt(SimulatedUser(second_face=(100.0, 130.0), second_iod=35.0))
    assert result.ok  # 35 px is 44 % of 80 px and below 40 px


def test_calibration_json_and_measurement() -> None:
    assert Calibration.from_json(CAL.to_json()) == CAL
    for bad in (None, {}, {"sign": 2, "left": 0.3, "right": 0.3}, {"sign": 1, "left": "x"}):
        assert Calibration.from_json(bad) is None
    assert Calibration.from_json({"sign": 1, "left": 0.01, "right": 0.3}) is None
    measured = Calibration.measure([0.4, 0.42, 0.38], [-0.3, -0.33])
    assert measured == Calibration(1, 0.4, pytest.approx(0.315))
    flipped = Calibration.measure([-0.4], [0.35])
    assert flipped is not None and flipped.sign == -1
    assert Calibration.measure([0.4], [0.3]) is None  # both sides the same way
    assert Calibration.measure([0.4], []) is None
    assert Calibration.measure([0.1], [-0.4]) is None  # too small to use
