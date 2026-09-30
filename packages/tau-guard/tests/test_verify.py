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
