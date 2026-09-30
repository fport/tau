"""Guided enrollment over a simulated owner: poses, samples, diversity, leave-one-out,
calibration, hints and ``--add``."""

from __future__ import annotations

import pytest
from tau_guard.camera import Frame
from tau_guard.engine import cosine
from tau_guard.enroll import (
    DIVERSITY,
    LOO_MIN,
    MAX_SAMPLES,
    MIN_SAMPLES,
    POSES,
    Enrollment,
    leave_one_out,
    run_enrollment,
)
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
from tau_guard.verify import Progress


def enroll(user: SimulatedUser, machine: Enrollment | None = None):
    published: list[Progress] = []

    def emit(progress: Progress) -> None:
        published.append(progress)
        user.on_progress(progress)

    result = run_enrollment(FakeEngine(), user.source(), emit=emit, machine=machine)
    return result, published


def test_a_simulated_owner_enrolls() -> None:
    user = SimulatedUser(duration=25)
    result, published = enroll(user)
    assert result.ok and result.reason == "match"
    assert MIN_SAMPLES <= len(result.samples) <= MAX_SAMPLES
    steps = [p.step for p in published if p.hint is None]
    assert [s for s in steps if s in POSES] == list(POSES)
    assert result.calibration is not None and result.calibration.sign == 1
    assert result.calibration.left == pytest.approx(0.45, abs=0.05)
    assert result.calibration.right == pytest.approx(0.45, abs=0.05)
    assert result.consistency is not None and result.consistency >= LOO_MIN
    assert user.now() - user.start < 20  # guided capture within the camera's 20 s
    for i, a in enumerate(result.samples):
        for b in result.samples[i + 1 :]:
            assert cosine(a, b) <= DIVERSITY


def test_the_calibration_follows_the_camera() -> None:
    result, _ = enroll(SimulatedUser(sign=-1, amplitude=0.6, duration=25))
    assert result.ok and result.calibration is not None
    assert result.calibration.sign == -1 and result.calibration.left == pytest.approx(0.6, abs=0.05)


def test_a_small_turn_gets_turn_more_and_then_fails_without_a_calibration() -> None:
    result, published = enroll(SimulatedUser(amplitude=0.1, duration=25))
    assert "turn_more" in [p.step for p in published]
    assert not result.ok and result.reason == "timeout"


def test_turn_more_is_heeded() -> None:
    # 0.15 is too small; the user turns 1.5 x further when nudged, which reaches the floor
    result, published = enroll(SimulatedUser(amplitude=0.15, duration=25))
    assert "turn_more" in [p.step for p in published]
    assert result.ok and result.calibration is not None


def test_inconsistent_samples_are_rejected() -> None:
    # someone else takes over for the last poses: leave-one-out falls below 0.55
    user = SimulatedUser(duration=25)
    machine = Enrollment()
    samples: list[tuple[float, ...]] = []

    def emit(progress: Progress) -> None:
        user.on_progress(progress)
        if progress.step == "look_up":
            user.embedding = STRANGER

    result = run_enrollment(FakeEngine(), user.source(), emit=emit, machine=machine)
    samples = list(machine.samples)
    assert not result.ok and result.reason == "no_match"
    assert result.consistency is not None and result.consistency < LOO_MIN
    assert min(leave_one_out(samples)) < LOO_MIN


def test_leave_one_out() -> None:
    same = [variant(OWNER, i) for i in range(10)]
    assert min(leave_one_out(same)) > 0.8
    mixed = same + [variant(STRANGER, 99)]
    scores = leave_one_out(mixed)
    assert scores[-1] < 0.2 and min(scores[:-1]) > 0.7


def frames(images: list[Scene], fps: float = 30.0) -> list[Frame]:
    return [Frame(image, 100.0 + i / fps) for i, image in enumerate(images)]


def test_samples_that_are_too_alike_are_skipped() -> None:
    frozen = [Scene([face_row()], [OWNER])] * 600  # the same embedding in every frame
    machine = Enrollment()
    source = FakeFrameSource(frames(frozen))
    result = run_enrollment(FakeEngine(), source, emit=lambda p: None, machine=machine)
    assert len(machine.samples) == 1 and not result.ok


@pytest.mark.parametrize(
    ("image", "reason"),
    [
        (Scene([], [], brightness=100), "no_face"),
        (Scene([], [], brightness=20), "no_face"),
        (Scene([face_row()], [OWNER], brightness=20), "too_dark"),
        (Scene([face_row(iod=25)], [OWNER]), "face_too_small"),
        (
            Scene([face_row(), face_row(cx=80, iod=60)], [OWNER, STRANGER]),
            "multiple_faces",
        ),
    ],
)
def test_live_hints_and_failures(image: Scene, reason: str) -> None:
    published: list[Progress] = []
    result = run_enrollment(
        FakeEngine(), FakeFrameSource(frames([image] * 600)), emit=published.append
    )
    assert not result.ok and result.reason == reason
    if reason in ("too_dark", "face_too_small", "multiple_faces"):
        assert reason in [p.hint for p in published]


def test_adding_samples_under_other_light() -> None:
    old = [variant(OWNER, 1000 + i) for i in range(12)]
    from tau_guard.engine import mean_vector

    machine = Enrollment(
        existing_vector=mean_vector(old),
        existing_samples=old,
        existing_calibration=Calibration(1, 0.5, 0.3),
    )
    result, _ = enroll(SimulatedUser(duration=25), machine)
    assert result.ok and len(result.samples) > len(old)
    assert result.samples[: len(old)] == tuple(old)
    assert result.calibration is not None
    assert result.calibration.left == pytest.approx(0.475, abs=0.03)


def test_adding_someone_elses_samples_is_refused() -> None:
    old = [variant(STRANGER, i) for i in range(12)]
    from tau_guard.engine import mean_vector

    machine = Enrollment(existing_vector=mean_vector(old), existing_samples=old)
    result, _ = enroll(SimulatedUser(duration=25), machine)
    assert not result.ok and result.reason == "no_match"


def test_adding_with_a_flipped_turn_is_refused() -> None:
    old = [variant(OWNER, 1000 + i) for i in range(12)]
    from tau_guard.engine import mean_vector

    machine = Enrollment(
        existing_vector=mean_vector(old),
        existing_samples=old,
        existing_calibration=Calibration(-1, 0.4, 0.4),
    )
    result, _ = enroll(SimulatedUser(duration=25), machine)
    assert not result.ok and result.reason == "timeout"
