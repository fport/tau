"""Touch ID in the worker (issue 114, ADR 0008 decision 15), run in-process with fakes.

Enrollment and forget: the device-owner policy for a first enrollment, Touch ID only with the
pinned fingerprint set once enrolled (a changed set refuses), the password policy on a Mac
without Touch ID. The ``touch_id`` op: the unlock fallback, the recheck and the step-up, which
never open the camera. The ``face_or_touch_id`` step-up asks Touch ID only after a face check
that could not work. ``FakeLocalAuth`` never shows a prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tau_guard.camera import CameraError
from tau_guard.engine import SFACE_SHA256
from tau_guard.localauth import BIOMETRICS, DEVICE_OWNER, Biometry
from tau_guard.runner import Malformed, parse_line
from tau_guard.store import MARKER_FILE, TEMPLATE_FILE, load_template, read_pin
from tau_guard.testing import (
    FINGERPRINTS,
    OTHER_FINGERPRINTS,
    STRANGER,
    FakeFrameSource,
    FakeLocalAuth,
    SimulatedUser,
)
from test_worker_ops import Session, accepted_by_the_hub

NO_SENSOR = Biometry("none", "no_sensor")
CLAMSHELL = Biometry("unavailable", "clamshell", clamshell=True)
ADDED_A_FINGER = Biometry("available", domain_state=OTHER_FINGERPRINTS)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(tmp_path)


def guard_dir(session: Session) -> Path:
    return session.data_dir / "guard"


def touch_request(session: Session, kind: str = "unlock", **extra: Any) -> dict[str, Any]:
    return session.request("touch_id", kind, reason_text="unlock tau", **extra)


# -- enrollment and forget -----------------------------------------------------------------------


def test_the_first_enrollment_uses_the_device_owner_policy_and_pins_the_fingerprints(
    session: Session,
) -> None:
    answer = session.enroll()
    assert answer["ok"] is True and answer["first"] is True
    assert [policy for policy, _ in session.auth.calls] == [DEVICE_OWNER]
    assert session.auth.pins == [None]
    assert answer["local_auth"]["policy"] == DEVICE_OWNER
    assert answer["local_auth"]["outcome"] == "ok"
    outcome = accepted_by_the_hub("enroll", session.lines, answer)
    assert outcome.local_auth is not None and outcome.local_auth[:2] == (DEVICE_OWNER, "ok")
    template = load_template(guard_dir(session), session.keys, SFACE_SHA256)
    assert template.domain_state == FINGERPRINTS
    assert read_pin(guard_dir(session), session.keys) == FINGERPRINTS


def test_a_re_enrollment_needs_touch_id_with_the_pinned_fingerprints(session: Session) -> None:
    session.enroll()
    again = session.enroll()
    assert again["ok"] is True and again["first"] is False
    assert session.auth.calls[-1][0] == BIOMETRICS and session.auth.pins[-1] == FINGERPRINTS
    assert again["local_auth"]["policy"] == BIOMETRICS


def test_a_changed_fingerprint_set_refuses_a_re_enrollment_before_the_camera(
    session: Session,
) -> None:
    session.enroll()
    before = (guard_dir(session) / TEMPLATE_FILE).read_bytes()
    changed = FakeLocalAuth(biometry=ADDED_A_FINGER)
    source = FakeFrameSource([])
    answer = session.run("enroll", session.request("enroll"), local_auth=changed, source=source)
    assert answer["ok"] is False and answer["reason"] == "touch_id_failed"
    assert answer["local_auth"] == {"policy": BIOMETRICS, "outcome": "changed", "ms": 0}
    assert changed.prompts == 0 and not source.opened  # no prompt, the camera stays off
    assert (guard_dir(session) / TEMPLATE_FILE).read_bytes() == before
    accepted_by_the_hub("enroll", session.lines, answer)


def test_a_re_enrollment_while_touch_id_cannot_be_used_is_refused(session: Session) -> None:
    session.enroll()
    closed = FakeLocalAuth(biometry=CLAMSHELL)
    source = FakeFrameSource([])
    answer = session.run("enroll", session.request("enroll"), local_auth=closed, source=source)
    assert answer["reason"] == "touch_id_unavailable"
    assert closed.calls == [] and not source.opened  # never the password instead


def test_a_mac_without_touch_id_uses_the_password_policy_and_pins_nothing(
    session: Session,
) -> None:
    session.auth = FakeLocalAuth(biometry=NO_SENSOR)
    session.enroll()
    again = session.enroll()
    assert again["ok"] is True
    assert [policy for policy, _ in session.auth.calls] == [DEVICE_OWNER, DEVICE_OWNER]
    assert read_pin(guard_dir(session), session.keys) is None


def test_an_enrollment_without_a_pin_can_be_redone_with_touch_id_and_pins_it(
    session: Session,
) -> None:
    session.auth = FakeLocalAuth(biometry=CLAMSHELL)  # set up with the lid closed
    session.enroll()
    assert read_pin(guard_dir(session), session.keys) is None
    session.auth = FakeLocalAuth()  # the lid is open again
    answer = session.enroll(add=True)
    assert answer["ok"] is True and session.auth.calls[-1][0] == BIOMETRICS
    assert session.auth.pins[-1] is None  # nothing to compare yet
    assert read_pin(guard_dir(session), session.keys) == FINGERPRINTS


@pytest.mark.parametrize(
    ("biometry", "policy", "pin"),
    [(None, BIOMETRICS, FINGERPRINTS), (NO_SENSOR, DEVICE_OWNER, None)],
)
def test_forget_follows_the_same_policy(
    session: Session, biometry: Biometry | None, policy: str, pin: str | None
) -> None:
    session.auth = FakeLocalAuth(biometry=biometry)
    session.enroll()
    answer = session.run("forget", session.request("forget", reason_text="remove it"))
    assert answer["ok"] is True and session.auth.calls[-1] == (policy, "remove it")
    assert session.auth.pins[-1] == pin
    assert answer["local_auth"]["policy"] == policy
    parse_line(json.dumps(answer).encode(), op="selftest")


@pytest.mark.parametrize(
    ("auth", "reason"),
    [
        (FakeLocalAuth(biometry=ADDED_A_FINGER), "touch_id_failed"),
        (FakeLocalAuth(biometry=CLAMSHELL), "touch_id_unavailable"),
    ],
)
def test_forget_is_refused_when_touch_id_does_not_confirm_the_owner(
    session: Session, auth: FakeLocalAuth, reason: str
) -> None:
    session.enroll()
    answer = session.run("forget", session.request("forget"), local_auth=auth)
    assert answer["ok"] is False and answer["reason"] == reason and auth.prompts == 0
    assert (guard_dir(session) / MARKER_FILE).exists() and session.keys.key is not None


NO_FINGERS = Biometry("none", "not_enrolled")


@pytest.mark.parametrize(
    ("biometry", "reason", "outcome"),
    [
        (NO_FINGERS, "touch_id_failed", "changed"),  # every pinned finger was removed
        (NO_SENSOR, "touch_id_unavailable", "unavailable"),  # the Touch ID keyboard is gone
    ],
)
@pytest.mark.parametrize("op", ["enroll", "forget"])
def test_a_pinned_enrollment_never_falls_back_to_the_password(
    session: Session, biometry: Biometry, reason: str, outcome: str, op: str
) -> None:
    session.enroll()  # pinned with FINGERPRINTS
    before = (guard_dir(session) / TEMPLATE_FILE).read_bytes()
    auth = FakeLocalAuth(biometry=biometry)
    source = FakeFrameSource([])
    answer = session.run(op, session.request(op), local_auth=auth, source=source)
    assert answer["ok"] is False and answer["reason"] == reason
    assert answer["local_auth"] == {"policy": BIOMETRICS, "outcome": outcome, "ms": 0}
    assert auth.calls == [] and not source.opened  # no prompt, no password, no camera
    assert (guard_dir(session) / TEMPLATE_FILE).read_bytes() == before
    assert (guard_dir(session) / MARKER_FILE).exists() and session.keys.key is not None
    accepted_by_the_hub(op if op == "enroll" else "selftest", session.lines, answer)


def test_an_enrollment_that_never_pinned_keeps_the_password_without_fingers(
    session: Session,
) -> None:
    session.auth = FakeLocalAuth(biometry=NO_FINGERS)  # a Touch ID Mac with no finger enrolled
    session.enroll()
    assert read_pin(guard_dir(session), session.keys) is None
    again = session.enroll()
    assert again["ok"] is True and session.auth.calls[-1][0] == DEVICE_OWNER


def break_template(session: Session, how: str) -> None:
    path = guard_dir(session) / (MARKER_FILE if how == "no_marker" else TEMPLATE_FILE)
    if how == "corrupt":
        path.write_bytes(b"TAUG1" + b"\0" * 40)
    else:
        path.unlink()


@pytest.mark.parametrize("how", ["corrupt", "deleted", "no_marker"])
@pytest.mark.parametrize("op", ["enroll", "forget"])
def test_a_pin_that_cannot_be_read_refuses_touch_id_only(
    session: Session, how: str, op: str
) -> None:
    session.enroll()
    break_template(session, how)
    auth = FakeLocalAuth(biometry=ADDED_A_FINGER)  # a finger was added meanwhile
    source = FakeFrameSource([])
    answer = session.run(op, session.request(op), local_auth=auth, source=source)
    assert answer["ok"] is False and answer["reason"] == "touch_id_failed"
    assert answer["local_auth"]["outcome"] == "changed" and auth.calls == []
    assert not source.opened and session.keys.key is not None
    unavailable = FakeLocalAuth(biometry=CLAMSHELL)
    closed = session.run(op, session.request(op), local_auth=unavailable)
    assert closed["reason"] == "touch_id_unavailable" and unavailable.calls == []


@pytest.mark.parametrize("op", ["enroll", "forget"])
def test_a_mac_without_a_sensor_repairs_an_unreadable_enrollment_with_the_password(
    session: Session, op: str
) -> None:
    session.auth = FakeLocalAuth(biometry=NO_SENSOR)
    session.enroll()
    break_template(session, "corrupt")
    answer = session.run(op, session.request(op))
    assert answer["ok"] is True and session.auth.calls[-1][0] == DEVICE_OWNER


def test_a_key_left_behind_by_forget_can_still_be_removed(session: Session) -> None:
    session.enroll()
    for name in (TEMPLATE_FILE, MARKER_FILE):  # forget removed both, the Keychain kept the key
        (guard_dir(session) / name).unlink()
    answer = session.run("forget", session.request("forget"))
    assert answer["ok"] is True and answer["removed"] == ["key"]
    assert session.auth.calls[-1][0] == BIOMETRICS and session.auth.pins[-1] is None


def test_a_keychain_that_does_not_answer_refuses_before_any_prompt(session: Session) -> None:
    from tau_guard.store import MemoryKeyStore

    session.enroll()
    auth = FakeLocalAuth()
    answer = session.run(
        "forget", session.request("forget"), local_auth=auth, keys=MemoryKeyStore(fail=True)
    )
    assert answer["ok"] is False and answer["reason"] == "key_unavailable"
    assert auth.calls == [] and (guard_dir(session) / MARKER_FILE).exists()


# -- the touch_id op -----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["unlock", "recheck"])
def test_the_touch_id_fallback_passes_with_the_pinned_fingerprints(
    session: Session, kind: str
) -> None:
    session.enroll()
    count = len(session.sources)
    request = touch_request(session, kind, settings={"unlock_fallback": "touch_id"})
    answer = session.run("touch_id", request)
    assert answer["ok"] is True and answer["reason"] == "match"
    assert answer["method"] == "touch_id"
    assert session.auth.calls[-1] == (BIOMETRICS, "unlock tau")
    assert session.auth.pins[-1] == FINGERPRINTS and session.auth.timeouts[-1] == 30.0
    assert [line["step"] for line in session.progress()] == ["touch_id"]
    assert len(session.sources) == count  # the camera was never asked for
    outcome = accepted_by_the_hub("touch_id", session.lines, answer)
    assert outcome.method == "touch_id" and outcome.local_auth == (BIOMETRICS, "ok", 0)


def test_the_default_fallback_is_touch_id_only(session: Session) -> None:
    session.enroll()
    answer = session.run("touch_id", touch_request(session))  # no settings: the default
    assert answer["reason"] == "touch_id_unavailable"  # the hub always sends its settings
    fallback = session.run("touch_id", touch_request(session, settings={"unlock_fallback": "x"}))
    assert fallback["reason"] == "touch_id_unavailable"
    assert session.auth.calls[1:] == []  # only the enrollment asked


def test_touch_id_or_password_uses_the_device_owner_policy(session: Session) -> None:
    session.enroll()
    closed = FakeLocalAuth(biometry=CLAMSHELL)  # the opt-in for a closed lid
    request = touch_request(session, settings={"unlock_fallback": "touch_id_or_password"})
    answer = session.run("touch_id", request, local_auth=closed)
    assert answer["ok"] is True and closed.calls == [(DEVICE_OWNER, "unlock tau")]
    assert closed.pins == [None]


@pytest.mark.parametrize(
    ("hub", "merged", "policy"),
    [
        ("touch_id_or_password", "touch_id_or_password", DEVICE_OWNER),
        ("touch_id_or_password", "touch_id", BIOMETRICS),  # the client refuses the password
        ("touch_id", "touch_id_or_password", BIOMETRICS),  # a weaker policy never widens it
        ("touch_id_or_password", "none", None),
        ("touch_id_or_password", "bogus", None),
    ],
)
def test_the_stricter_of_the_settings_and_the_merged_policy_picks_the_prompt(
    session: Session, hub: str, merged: str, policy: str | None
) -> None:
    session.enroll()
    auth = FakeLocalAuth()
    request = touch_request(
        session, settings={"unlock_fallback": hub}, policy={"unlock_fallback": merged}
    )
    answer = session.run("touch_id", request, local_auth=auth)
    if policy is None:
        assert answer["reason"] == "touch_id_unavailable" and auth.calls == []
    else:
        assert answer["ok"] is True and auth.calls == [(policy, "unlock tau")]


@pytest.mark.parametrize(
    ("auth", "reason", "prompts"),
    [
        (FakeLocalAuth(biometry=ADDED_A_FINGER), "touch_id_failed", 0),
        (FakeLocalAuth(biometry=CLAMSHELL), "touch_id_unavailable", 0),
        (FakeLocalAuth(biometry=NO_SENSOR), "touch_id_unavailable", 0),
        (FakeLocalAuth("failed"), "touch_id_failed", 1),
        (FakeLocalAuth("cancelled"), "touch_id_failed", 1),
        (FakeLocalAuth("timeout"), "touch_id_failed", 1),
        (FakeLocalAuth("unavailable"), "touch_id_unavailable", 1),
    ],
)
def test_the_touch_id_fallback_fails_closed(
    session: Session, auth: FakeLocalAuth, reason: str, prompts: int
) -> None:
    session.enroll()
    request = touch_request(session, settings={"unlock_fallback": "touch_id"})
    answer = session.run("touch_id", request, local_auth=auth)
    assert answer["ok"] is False and answer["reason"] == reason and answer["method"] is None
    assert auth.prompts == prompts
    accepted_by_the_hub("touch_id", session.lines, answer)


def test_an_enrollment_without_a_pin_never_passes_touch_id_only(session: Session) -> None:
    session.auth = FakeLocalAuth(biometry=NO_SENSOR)
    session.enroll()
    auth = FakeLocalAuth()  # a Touch ID keyboard appeared since
    request = touch_request(session, settings={"unlock_fallback": "touch_id"})
    answer = session.run("touch_id", request, local_auth=auth)
    assert answer["reason"] == "touch_id_failed" and auth.calls == []


@pytest.mark.parametrize("fallback", ["touch_id", "touch_id_or_password"])
def test_touch_id_needs_an_enrollment_and_a_readable_template(
    session: Session, fallback: str
) -> None:
    request = touch_request(session, settings={"unlock_fallback": fallback})
    assert session.run("touch_id", request)["reason"] == "not_enrolled"
    session.enroll()
    (guard_dir(session) / TEMPLATE_FILE).write_bytes(b"TAUG1" + b"\0" * 40)
    assert session.run("touch_id", request)["reason"] == "template_invalid"
    from tau_guard.store import MemoryKeyStore

    failing = MemoryKeyStore(fail=True)
    assert session.run("touch_id", request, keys=failing)["reason"] == "key_unavailable"
    assert session.auth.calls[1:] == []  # no prompt for a broken enrollment


@pytest.mark.parametrize(
    ("step_up", "reason"),
    [
        ("touch_id", "match"),
        ("face_or_touch_id", "match"),
        ("face", "touch_id_unavailable"),
        ("none", "touch_id_unavailable"),
    ],
)
def test_the_touch_id_step_up_never_opens_the_camera(
    session: Session, step_up: str, reason: str
) -> None:
    session.enroll()
    count = len(session.sources)
    request = session.request(
        "touch_id", "step_up", policy={"step_up": step_up}, reason_text="run lamp"
    )
    answer = session.run("touch_id", request)
    assert answer["reason"] == reason and len(session.sources) == count
    if reason == "match":
        assert answer["method"] == "touch_id"
        assert session.auth.calls[-1] == (BIOMETRICS, "run lamp")


# -- face_or_touch_id: Touch ID after a face check that could not work ---------------------------


class _RecordingAuth(FakeLocalAuth):
    """Notes whether the camera was already released when the prompt came."""

    def __init__(self, session: Session, *outcomes: str) -> None:
        super().__init__(*outcomes)
        self.session = session
        self.camera_closed: list[bool] = []

    def authenticate(self, policy: str, reason: str, **kwargs: Any) -> str:
        source = self.session.sources[-1] if self.session.sources else None
        self.camera_closed.append(source is None or source.closed)
        return super().authenticate(policy, reason, **kwargs)


def step_up_request(session: Session, mode: str) -> dict[str, Any]:
    return session.request("verify", "step_up", policy={"step_up": mode}, reason_text="run lamp")


def test_a_dark_room_falls_back_to_touch_id_after_the_camera_is_released(
    session: Session,
) -> None:
    session.enroll()
    auth = _RecordingAuth(session)
    dark = SimulatedUser(brightness=30.0)
    request = step_up_request(session, "face_or_touch_id")
    answer = session.run("verify", request, user=dark, local_auth=auth)
    assert answer["ok"] is True and answer["method"] == "touch_id"
    assert auth.calls == [(BIOMETRICS, "run lamp")] and auth.pins == [FINGERPRINTS]
    assert auth.camera_closed == [True]
    steps = [line["step"] for line in session.progress()]
    assert steps[0] == "starting" and steps[-1] == "touch_id"
    outcome = accepted_by_the_hub("verify", session.lines, answer)
    assert outcome.method == "touch_id" and isinstance(outcome.camera_ms, int)


@pytest.mark.parametrize("reason", ["camera_busy", "camera_unavailable", "camera_denied"])
def test_a_camera_verdict_falls_back_to_touch_id(session: Session, reason: str) -> None:
    session.enroll()
    source = FakeFrameSource(open_error=CameraError(reason, "the camera cannot be used"))
    answer = session.run("verify", step_up_request(session, "face_or_touch_id"), source=source)
    assert answer["ok"] is True and answer["method"] == "touch_id"


@pytest.mark.parametrize(("mode", "falls_back"), [("face_or_touch_id", True), ("face", False)])
def test_a_missing_face_model_falls_back_to_touch_id(
    session: Session, mode: str, falls_back: bool
) -> None:
    from tau_guard import worker
    from tau_guard.engine import ModelError
    from tau_guard.testing import fake_deps

    session.enroll()

    def no_model(data_dir: Path) -> Any:
        raise ModelError("missing", "SFace is not installed")

    auth = FakeLocalAuth()
    built = fake_deps(keys=session.keys, local_auth=auth)
    built.engine = no_model
    answer = worker.run("verify", step_up_request(session, mode), deps=built)
    if falls_back:
        assert answer["ok"] is True and answer["method"] == "touch_id"
        assert auth.calls == [(BIOMETRICS, "run lamp")] and auth.pins == [FINGERPRINTS]
    else:
        assert answer["reason"] == "unavailable" and auth.calls == []


@pytest.mark.parametrize(("mode", "falls_back"), [("face_or_touch_id", True), ("face", False)])
def test_a_changed_face_model_falls_back_to_touch_id_with_the_old_pin(
    session: Session, monkeypatch: pytest.MonkeyPatch, mode: str, falls_back: bool
) -> None:
    session.enroll()
    monkeypatch.setattr("tau_guard.engine.SFACE_SHA256", "1" * 64)  # a newer SFace since
    auth = FakeLocalAuth()
    answer = session.run("verify", step_up_request(session, mode), local_auth=auth)
    if falls_back:
        assert answer["ok"] is True and answer["method"] == "touch_id"
        assert auth.pins == [FINGERPRINTS]  # read with the model the enrollment was made with
        accepted_by_the_hub("verify", session.lines, answer)
    else:
        assert answer["reason"] == "model_changed" and auth.calls == []


def test_a_changed_face_model_with_no_pin_refuses_touch_id(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.auth = FakeLocalAuth(biometry=CLAMSHELL)  # enrolled with the lid closed: no pin
    session.enroll()
    monkeypatch.setattr("tau_guard.engine.SFACE_SHA256", "1" * 64)
    auth = FakeLocalAuth()
    answer = session.run("verify", step_up_request(session, "face_or_touch_id"), local_auth=auth)
    assert answer["reason"] == "touch_id_failed" and auth.calls == []


def test_a_counted_face_failure_never_falls_back(session: Session) -> None:
    session.enroll()
    auth = FakeLocalAuth()
    stranger = SimulatedUser(embedding=STRANGER)
    answer = session.run(
        "verify", step_up_request(session, "face_or_touch_id"), user=stranger, local_auth=auth
    )
    assert answer["ok"] is False and answer["reason"] == "no_match" and auth.calls == []


@pytest.mark.parametrize("mode", ["face", "none"])
def test_other_step_up_modes_never_ask_touch_id_after_the_face(session: Session, mode: str) -> None:
    session.enroll()
    auth = FakeLocalAuth()
    dark = SimulatedUser(brightness=30.0)
    answer = session.run("verify", step_up_request(session, mode), user=dark, local_auth=auth)
    assert answer["ok"] is False and answer["reason"] == "too_dark" and auth.calls == []


def test_a_failed_touch_id_after_the_face_keeps_the_touch_id_reason(session: Session) -> None:
    session.enroll()
    auth = FakeLocalAuth("failed")
    dark = SimulatedUser(brightness=30.0)
    answer = session.run(
        "verify", step_up_request(session, "face_or_touch_id"), user=dark, local_auth=auth
    )
    assert answer["ok"] is False and answer["reason"] == "touch_id_failed"
    assert answer["local_auth"]["outcome"] == "failed"


def test_the_step_up_policy_for_a_face_check_of_touch_id_only_is_refused(
    session: Session,
) -> None:
    session.enroll()
    answer = session.run("verify", step_up_request(session, "touch_id"))
    assert answer["reason"] == "touch_id_unavailable"  # the hub runs the touch_id op instead


# -- the hub reads what the worker says about LocalAuthentication --------------------------------


@pytest.mark.parametrize(
    "local_auth",
    [
        None,
        {"policy": BIOMETRICS, "outcome": "failed", "ms": 10},
        {"policy": "password", "outcome": "ok", "ms": 10},
        {"policy": BIOMETRICS, "outcome": "ok", "ms": -1},
        {"policy": BIOMETRICS, "outcome": "ok", "ms": True},
        ["biometrics", "ok", 1],
    ],
)
def test_a_touch_id_success_needs_a_passed_prompt(local_auth: Any) -> None:
    verdict: dict[str, Any] = {
        "type": "verdict",
        "ok": True,
        "reason": "match",
        "method": "touch_id",
    }
    if local_auth is not None:
        verdict["local_auth"] = local_auth
    with pytest.raises(Malformed):
        parse_line(json.dumps(verdict).encode(), op="touch_id")


def test_a_local_auth_record_on_a_failure_is_read() -> None:
    verdict = {
        "type": "verdict",
        "ok": False,
        "reason": "touch_id_failed",
        "method": None,
        "local_auth": {"policy": DEVICE_OWNER, "outcome": "cancelled", "ms": 1200},
    }
    outcome = parse_line(json.dumps(verdict).encode(), op="touch_id")
    assert outcome.local_auth == (DEVICE_OWNER, "cancelled", 1200)
