"""The worker's operations run in-process with fakes: enroll, verify, forget and the deep
self-test, wired to the camera, the engine, the store and LocalAuthentication. Nothing opens a
camera, the Keychain or a prompt."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from guard_helpers import running_hub, until
from tau_core.guard import read_enrollment
from tau_guard import worker
from tau_guard.camera import CameraError
from tau_guard.engine import SFACE_SHA256, ModelError
from tau_guard.liveness import Calibration
from tau_guard.local import validate_explain
from tau_guard.localauth import BIOMETRICS, DEVICE_OWNER, Biometry
from tau_guard.runner import Progress, parse_line
from tau_guard.state import Outcome
from tau_guard.store import (
    MARKER_FILE,
    TEMPLATE_FILE,
    MemoryKeyStore,
    load_template,
    new_key,
    save_enrollment,
    template_from,
)
from tau_guard.testing import (
    FINGERPRINTS,
    OTHER_FINGERPRINTS,
    OWNER,
    STRANGER,
    FakeFrameSource,
    FakeLocalAuth,
    Scene,
    SimulatedUser,
    face_row,
    fake_deps,
    variant,
)


class Session:
    """A data dir, a key store, LocalAuthentication and a simulated user for each operation."""

    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.keys = MemoryKeyStore()
        self.auth = FakeLocalAuth()
        self.lines: list[dict[str, Any]] = []
        self.user = SimulatedUser()
        self.sources: list[Any] = []

    def request(self, op: str, kind: str | None = None, **extra: Any) -> dict[str, Any]:
        return {
            "v": 1,
            "op": op,
            "kind": kind or op,
            "attempt": "a1",
            "data_dir": str(self.data_dir),
            "policy": {},
            "settings": {},
            "challenge_fresh": False,
            **extra,
        }

    def run(self, op: str, request: dict[str, Any], *, user: SimulatedUser | None = None, **deps):
        self.user = user or SimulatedUser()
        self.lines = []

        given = deps.pop("source", None)

        def source(camera: str) -> Any:
            made = given or self.user.source()
            self.sources.append(made)
            return made

        def emit(message: dict[str, Any]) -> None:
            self.lines.append(message)
            if message["type"] == "progress":
                self.user.on_progress(message)

        built = fake_deps(
            source=source,
            keys=deps.pop("keys", self.keys),
            local_auth=deps.pop("local_auth", self.auth),
            rng=random.Random(deps.pop("seed", 11)),
            clock=self.user.now,
            **deps,
        )
        return worker.run(op, request, deps=built, emit=emit)

    def enroll(self, **extra: Any) -> dict[str, Any]:
        return self.run("enroll", self.request("enroll", **extra), user=SimulatedUser(duration=25))

    def progress(self) -> list[dict[str, Any]]:
        return [line for line in self.lines if line["type"] == "progress"]


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(tmp_path)


def accepted_by_the_hub(op: str, lines: list[dict[str, Any]], answer: dict[str, Any]) -> Outcome:
    for line in lines:
        if line["type"] == "progress":
            assert isinstance(parse_line(json.dumps(line).encode(), op=op), Progress)
    outcome = parse_line(json.dumps(answer).encode(), op=op)
    assert isinstance(outcome, Outcome)
    return outcome


# -- enroll, then verify -------------------------------------------------------------------------


def test_enroll_then_verify(session: Session) -> None:
    answer = session.enroll()
    assert answer["ok"] is True and answer["reason"] == "match" and answer["method"] == "face"
    assert answer["first"] is True and isinstance(answer["camera_ms"], int)
    outcome = accepted_by_the_hub("enroll", session.lines, answer)
    assert outcome.camera_ms == answer["camera_ms"]
    steps = [line["step"] for line in session.progress()]
    assert steps[:2] == ["touch_id", "starting"]
    assert {"look", "turn_left", "turn_right", "look_up", "look_down"} <= set(steps)
    assert session.auth.calls == [(DEVICE_OWNER, worker.DEFAULT_REASON_TEXT)]
    guard = session.data_dir / "guard"
    assert (guard / TEMPLATE_FILE).is_file() and (guard / MARKER_FILE).is_file()
    template = load_template(guard, session.keys, SFACE_SHA256)
    assert 10 <= len(template.samples) <= 20 and template.calibration.sign == 1

    answer = session.run("verify", session.request("verify", "unlock"))
    assert answer["ok"] is True and answer["liveness"] == "challenge"
    assert 0.5 <= answer["score"] <= 1.0
    outcome = accepted_by_the_hub("verify", session.lines, answer)
    assert outcome == Outcome(
        True, "match", "face", answer["score"], "challenge", outcome.camera_ms
    )
    turns = [line for line in session.progress() if line["step"].startswith("turn_")]
    assert len(turns) == 2 and all(line["deadline"].endswith("+00:00") for line in turns)


def test_the_enrollment_marker_is_what_tau_core_reads(session: Session) -> None:
    from tau_core.testing import test_config

    session.enroll()
    config = test_config(session.data_dir.parent / "cfg")
    config = config.with_overrides(data_dir=session.data_dir)
    marker = json.loads((session.data_dir / "guard" / MARKER_FILE).read_text())
    assert set(marker) == {"v", "enrollment", "model", "created"}
    assert read_enrollment(config) == marker["enrollment"] and marker["model"] == SFACE_SHA256


def test_a_stranger_does_not_pass(session: Session) -> None:
    session.enroll()
    answer = session.run(
        "verify", session.request("verify", "unlock"), user=SimulatedUser(embedding=STRANGER)
    )
    assert answer["ok"] is False and answer["reason"] == "no_match"


def test_verify_kinds(session: Session) -> None:
    session.enroll()
    recheck = session.run("verify", session.request("verify", "recheck"))
    assert recheck["ok"] and recheck["liveness"] == "passive"
    step_up = session.run("verify", session.request("verify", "step_up"))
    assert step_up["ok"] and step_up["liveness"] == "challenge"
    assert len([p for p in session.progress() if p["step"].startswith("turn_")]) == 3
    fresh = session.run("verify", session.request("verify", "step_up", challenge_fresh=True))
    assert fresh["ok"] and fresh["liveness"] == "passive"
    none = session.run(
        "verify", {**session.request("verify", "unlock"), "policy": {"unlock_liveness": "none"}}
    )
    assert none["ok"] and none["liveness"] == "passive"
    touch = session.run(
        "verify", {**session.request("verify", "step_up"), "policy": {"step_up": "touch_id"}}
    )
    assert touch["reason"] == "touch_id_unavailable" and session.sources[-1] is not None


def test_a_threshold_below_the_floor_is_refused(session: Session) -> None:
    session.enroll()
    request = session.request("verify", "unlock", settings={"unlock_threshold": 0.4})
    count = len(session.sources)
    assert session.run("verify", request)["reason"] == "error"
    assert len(session.sources) == count  # the camera was never asked for


# -- verify without a usable template, engine or camera ------------------------------------------


def test_verify_answers_before_the_camera(session: Session) -> None:
    assert session.run("verify", session.request("verify", "unlock"))["reason"] == "not_enrolled"
    session.enroll()
    guard = session.data_dir / "guard"
    count = len(session.sources)
    failing = MemoryKeyStore(fail=True)
    assert session.run("verify", session.request("verify", "unlock"), keys=failing)["reason"] == (
        "key_unavailable"
    )
    other = MemoryKeyStore(new_key())
    assert session.run("verify", session.request("verify", "unlock"), keys=other)["reason"] == (
        "template_invalid"
    )

    class NoModel:
        def __call__(self, data_dir: Path) -> Any:
            raise ModelError("missing", "SFace is not installed")

    request = session.request("verify", "unlock")
    built = fake_deps(keys=session.keys)
    built.engine = NoModel()
    assert worker.run("verify", request, deps=built)["reason"] == "unavailable"
    marker = json.loads((guard / MARKER_FILE).read_text())
    (guard / MARKER_FILE).write_text(json.dumps({**marker, "model": "0" * 64}))
    assert session.run("verify", request)["reason"] == "model_changed"
    assert len(session.sources) == count
    assert worker.run("verify", request, deps=fake_deps(platform="linux"))["reason"] == (
        "unsupported_platform"
    )


@pytest.mark.parametrize(
    "reason", ["permission_pending", "camera_denied", "camera_unavailable", "camera_busy"]
)
def test_camera_errors_become_verdicts(session: Session, reason: str) -> None:
    session.enroll()
    source = FakeFrameSource([], open_error=CameraError(reason))
    answer = session.run("verify", session.request("verify", "unlock"), source=source)
    assert answer["ok"] is False and answer["reason"] == reason
    assert source.closed
    accepted_by_the_hub("verify", session.lines, answer)


def test_the_template_is_read_again_for_every_verification(session: Session) -> None:
    session.enroll()
    assert session.run("verify", session.request("verify", "recheck"))["ok"]
    (session.data_dir / "guard" / TEMPLATE_FILE).unlink()
    assert session.run("verify", session.request("verify", "recheck"))["reason"] == "not_enrolled"


def test_explain_lines_hold_numbers_only(session: Session) -> None:
    session.enroll()
    answer = session.run("verify", session.request("verify", "unlock", explain=True))
    assert answer["ok"]
    rows = [line for line in session.lines if line["type"] == "explain"]
    assert len(rows) > 20
    for row in rows:
        clean = validate_explain(row)
        assert set(row) == {"type", *clean}
        assert all(not isinstance(value, list | dict) for value in row.values())
    assert {row["phase"] for row in rows} == {"look", "challenge", "after"}
    session.run("verify", session.request("verify", "unlock"))
    assert not [line for line in session.lines if line["type"] == "explain"]


def test_live_hints_reach_guard_status(session: Session, tmp_path: Path) -> None:
    """The real verify logic publishes too_dark and face_too_small as progress hints; the hub
    shows them on the attempt in /guard/status."""
    session.enroll()
    dark = [Scene([face_row()], [variant(OWNER, i)], brightness=30) for i in range(40)]
    small = [Scene([face_row(iod=30)], [variant(OWNER, i)]) for i in range(40)]
    frames = [
        __import__("tau_guard.camera", fromlist=["Frame"]).Frame(image, 100 + i / 30)
        for i, image in enumerate(dark + small)
    ]
    session.run("verify", session.request("verify", "unlock"), source=FakeFrameSource(frames))
    hints = [line["hint"] for line in session.progress() if line["hint"]]
    assert "too_dark" in hints and "face_too_small" in hints
    first = {}
    for line in session.progress():
        first.setdefault(line["hint"], line)
    script_steps: list[dict[str, Any]] = []
    for hint in ("too_dark", "face_too_small"):
        line = first[hint]
        script_steps += [
            {"progress": line["step"], "hint": hint, "deadline": line["deadline"]},
            {"sleep": 1.0},
        ]
    with running_hub(tmp_path / "hub", runs=[[*script_steps, {"hang": True}]]) as running:
        client = running.client
        started = client.post(
            "/guard/verify", {"channel": "tui", "client_id": "c1", "kind": "unlock"}, timeout=5
        )
        for hint in ("too_dark", "face_too_small"):

            def hinted(hint: str = hint) -> bool:
                query = {"attempt": started["attempt"]}
                status = client.get("/guard/status", timeout=5, query=query)
                return (status["attempt"] or {}).get("hint") == hint

            until(hinted)


# -- enroll behind LocalAuthentication -----------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("failed", "touch_id_failed"),
        ("cancelled", "touch_id_failed"),
        ("unavailable", "touch_id_unavailable"),
    ],
)
def test_enrollment_runs_only_after_local_authentication(
    session: Session, outcome: str, reason: str
) -> None:
    source = FakeFrameSource([])
    answer = session.run(
        "enroll", session.request("enroll"), local_auth=FakeLocalAuth(outcome), source=source
    )
    assert answer["ok"] is False and answer["reason"] == reason
    assert not source.opened and session.sources == []
    assert not (session.data_dir / "guard" / MARKER_FILE).exists()
    assert session.keys.key is None


class _Permission:
    def __init__(self, status: int) -> None:
        self._status = status
        self.requests = 0

    def status(self) -> int:
        return self._status

    def request(self) -> None:
        self.requests += 1


class _Devices:
    def __init__(self, *devices: Any) -> None:
        self.listed = list(devices)

    def devices(self) -> list[Any]:
        return list(self.listed)


@pytest.mark.parametrize(
    ("status", "listed", "reason"),
    [
        (0, "builtin", "permission_pending"),  # macOS asks for access, then the owner retries
        (2, "builtin", "camera_denied"),
        (3, "iphone", "camera_unavailable"),  # no built-in camera to use
    ],
)
def test_the_camera_is_checked_before_local_authentication(
    session: Session, status: int, listed: str, reason: str
) -> None:
    from tau_guard.camera import BUILTIN_TYPE, Device

    devices = {
        "builtin": Device("B", "MacBook Pro Camera", BUILTIN_TYPE, "bltn"),
        "iphone": Device("A", "iPhone", "AVCaptureDeviceTypeExternal", "othr"),
    }
    permission = _Permission(status)
    answer = session.run(
        "enroll",
        session.request("enroll"),
        permission=lambda: permission,
        devices=lambda: _Devices(devices[listed]),
    )
    assert answer["ok"] is False and answer["reason"] == reason
    assert session.auth.calls == []  # no Touch ID or password for nothing
    assert session.sources == [] and permission.requests == (1 if status == 0 else 0)
    allowed = session.run(
        "enroll",
        session.request("enroll"),
        user=SimulatedUser(duration=25),
        permission=lambda: _Permission(3),
        devices=lambda: _Devices(devices["builtin"]),
    )
    assert allowed["ok"] is True and len(session.auth.calls) == 1


def test_enrollment_is_refused_over_ssh(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSH_CONNECTION", "100.x.y.z 50000 100.x.y.z 22")
    assert session.enroll()["reason"] == "unavailable"
    assert session.auth.calls == []
    answer = session.run("forget", session.request("forget"))
    assert answer["reason"] == "unavailable" and session.auth.calls == []


def test_the_key_store_decides_first_enrollment(session: Session) -> None:
    assert session.enroll()["first"] is True
    key = session.keys.key
    (session.data_dir / "guard" / TEMPLATE_FILE).unlink()  # only the file goes
    again = session.enroll()
    assert again["ok"] and again["first"] is False and session.keys.key == key
    enrollment = read_enrollment_id(session)
    third = session.enroll()
    assert third["first"] is False and read_enrollment_id(session) != enrollment


def read_enrollment_id(session: Session) -> str:
    return json.loads((session.data_dir / "guard" / MARKER_FILE).read_text())["enrollment"]


def test_a_failing_key_store_never_counts_as_a_first_enrollment(session: Session) -> None:
    answer = session.run("enroll", session.request("enroll"), keys=MemoryKeyStore(fail=True))
    assert answer["reason"] == "key_unavailable" and session.auth.calls == []


def test_a_key_store_that_drops_writes_fails_the_enrollment(session: Session) -> None:
    """keyring's null backend (``PYTHON_KEYRING_BACKEND``) accepts a key and forgets it; the
    template must not be written with a key nobody can read back."""
    from tau_guard.store import KeychainKeyStore

    class NullKeyring:
        def get_password(self, service: str, account: str) -> None:
            return None

        def set_password(self, service: str, account: str, value: str) -> None:
            pass

        def delete_password(self, service: str, account: str) -> None:
            raise AssertionError("nothing to delete")

    keys = KeychainKeyStore(backend=NullKeyring())
    answer = session.run(
        "enroll", session.request("enroll"), keys=keys, user=SimulatedUser(duration=25)
    )
    assert answer["ok"] is False and answer["reason"] == "key_unavailable"
    guard = session.data_dir / "guard"
    assert not (guard / TEMPLATE_FILE).exists() and not (guard / MARKER_FILE).exists()


def test_enroll_and_forget_wait_longer_for_the_keychain() -> None:
    from tau_guard.store import KEY_TIMEOUT, KEY_TIMEOUT_AT_MAC

    assert worker.system_deps("verify").keys.timeout == KEY_TIMEOUT
    assert worker.system_deps("enroll").keys.timeout == KEY_TIMEOUT_AT_MAC
    assert worker.system_deps("forget").keys.timeout == KEY_TIMEOUT_AT_MAC > KEY_TIMEOUT


def test_adding_samples(session: Session) -> None:
    assert session.run("enroll", session.request("enroll", add=True))["reason"] == "not_enrolled"
    session.enroll()
    before = load_template(session.data_dir / "guard", session.keys, SFACE_SHA256)
    answer = session.run(
        "enroll", session.request("enroll", add=True), user=SimulatedUser(duration=25)
    )
    assert answer["ok"] and answer["first"] is False
    after = load_template(session.data_dir / "guard", session.keys, SFACE_SHA256)
    assert after.enrollment == before.enrollment and len(after.samples) > len(before.samples)


def test_a_bad_capture_stores_nothing(session: Session) -> None:
    answer = session.run(
        "enroll", session.request("enroll"), user=SimulatedUser(duration=25, amplitude=0.05)
    )
    assert answer["ok"] is False and answer["reason"] == "timeout"
    assert not (session.data_dir / "guard" / MARKER_FILE).exists() and session.keys.key is None


# -- forget --------------------------------------------------------------------------------------


def test_forget_behind_local_authentication(session: Session) -> None:
    session.enroll()
    refused = session.run("forget", session.request("forget"), local_auth=FakeLocalAuth("failed"))
    assert refused["reason"] == "touch_id_failed"
    assert (session.data_dir / "guard" / MARKER_FILE).exists() and session.keys.key is not None
    answer = session.run("forget", session.request("forget", reason_text="remove it"))
    assert answer["ok"] is True and answer["reason"] is None
    assert set(answer["removed"]) == {TEMPLATE_FILE, MARKER_FILE, "key"}
    assert session.auth.calls[-1] == (BIOMETRICS, "remove it")  # the Mac has Touch ID
    assert session.auth.pins[-1] == FINGERPRINTS  # pinned at enrollment
    assert session.keys.key is None
    parse_line(json.dumps(answer).encode(), op="selftest")  # the CLI reads it like a selftest


def test_forget_reports_what_went_when_the_key_cannot_go(session: Session) -> None:
    session.enroll()
    stuck = MemoryKeyStore(session.keys.key, fail=True)
    answer = session.run("forget", session.request("forget"), keys=stuck)
    assert answer["ok"] is False and answer["reason"] == "key_unavailable"
    assert set(answer["removed"]) == {TEMPLATE_FILE, MARKER_FILE}
    assert not (session.data_dir / "guard" / MARKER_FILE).exists()
    parse_line(json.dumps(answer).encode(), op="selftest")


def test_after_forget_a_running_hub_answers_not_enrolled(tmp_path: Path) -> None:
    import asyncio

    from guard_helpers import guard_config

    config = guard_config(tmp_path, enrolled=False)
    keys = MemoryKeyStore(new_key())
    template = template_from(
        [variant(OWNER, i) for i in range(10)],
        enrollment="e1",
        created="2026-09-30T12:00:00+00:00",
        model_sha=SFACE_SHA256,
        calibration=Calibration(1, 0.4, 0.4),
    )
    save_enrollment(config.data_dir / "guard", template, keys.key)
    from tau_guard.testing import match

    with running_hub(tmp_path, config=config, runs=[[match()], [match()]]) as running:
        assert asyncio.run(running.guard.unlock(channel="tui", client_id="c1")).ok
        answer = worker.run(
            "forget",
            {"v": 1, "data_dir": str(config.data_dir)},
            deps=fake_deps(keys=keys),
        )
        assert answer["ok"]
        verdict = asyncio.run(running.guard.unlock(channel="tui", client_id="c1"))
        assert (verdict.ok, verdict.reason) == (False, "not_enrolled")


# -- the deep self-test --------------------------------------------------------------------------


def test_the_deep_selftest_reports_everything_without_a_camera(session: Session) -> None:
    from tau_guard.camera import BUILTIN_TYPE, Device

    class Devices:
        def devices(self) -> list[Device]:
            return [
                Device("B", "MacBook Pro Camera", BUILTIN_TYPE, "bltn"),
                Device("A", "iPhone", "AVCaptureDeviceTypeExternal", "othr"),
            ]

    class Permission:
        def status(self) -> int:
            return 3

        def request(self) -> None:  # pragma: no cover - the self-test never asks
            raise AssertionError("the self-test must not ask for camera access")

    session.enroll()
    deps = fake_deps(keys=session.keys, devices=Devices, permission=Permission)
    answer = worker.selftest(
        "darwin", request={**session.request("selftest"), "deep": True}, deps=deps
    )
    details = answer["details"]
    assert details["yunet"] == "ok" and details["sface"] == "missing"
    assert details["keychain"] == "ok" and details["template"] == "ok"
    assert details["camera"] == {
        "device": "MacBook Pro Camera",
        "others": 1,
        "permission": 3,
        "builtin": True,
    }
    assert details["opencv"] and details["opencv_verified"] is True
    assert details["touch_id"] == {
        "biometry": "available",
        "detail": None,
        "clamshell": None,
        "pin": "ok",
    }
    plain = worker.selftest("darwin", request={"v": 1}, deps=deps)
    assert "details" not in plain

    from tau_guard.store import KeychainKeyStore

    class Junk:
        def get_password(self, service: str, account: str) -> str:
            return "not a key"

    deps = fake_deps(keys=KeychainKeyStore(backend=Junk()), devices=Devices, permission=Permission)
    answer = worker.selftest(
        "darwin", request={**session.request("selftest"), "deep": True}, deps=deps
    )
    assert answer["details"]["keychain"] == "invalid"
    deps = fake_deps(keys=MemoryKeyStore(fail=True), devices=Devices, permission=Permission)
    answer = worker.selftest(
        "darwin", request={**session.request("selftest"), "deep": True}, deps=deps
    )
    assert answer["details"]["keychain"] == "unavailable"


# -- hygiene -------------------------------------------------------------------------------------


def test_nothing_holds_an_embedding_but_the_encrypted_template(
    session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    session.enroll()
    session.run("verify", session.request("verify", "unlock", explain=True))
    session.run(
        "verify", session.request("verify", "unlock"), user=SimulatedUser(embedding=STRANGER)
    )
    template = load_template(session.data_dir / "guard", session.keys, SFACE_SHA256)
    needles = {f"{value:.6f}"[3:] for value in template.vector[:10]}
    needles |= {f"{value:.6f}"[3:] for value in OWNER[:10]}
    captured = capsys.readouterr()
    texts = [captured.out, captured.err, json.dumps(session.lines)]
    for path in (session.data_dir / "guard").rglob("*"):
        if path.is_file() and path.name != TEMPLATE_FILE:
            texts.append(path.read_bytes().decode("latin-1"))
    for text in texts:
        for needle in needles:
            assert needle not in text


@pytest.mark.parametrize(
    ("biometry", "pin"),
    [
        (Biometry("available", domain_state=OTHER_FINGERPRINTS), "changed"),
        (Biometry("unavailable", "clamshell", clamshell=True), "unknown"),
        (Biometry("available", domain_state=None), "unknown"),
        (Biometry("none", "no_sensor"), "unknown"),
    ],
)
def test_the_deep_selftest_compares_the_pinned_fingerprints_without_a_prompt(
    session: Session, biometry: Biometry, pin: str
) -> None:
    session.enroll()
    auth = FakeLocalAuth(biometry=biometry)
    deps = fake_deps(keys=session.keys, local_auth=auth)
    answer = worker.selftest(
        "darwin", request={**session.request("selftest"), "deep": True}, deps=deps
    )
    touch = answer["details"]["touch_id"]
    assert touch["pin"] == pin and touch["biometry"] == biometry.state
    assert touch["detail"] == biometry.detail and touch["clamshell"] == biometry.clamshell
    assert auth.calls == [] and auth.probes == 1  # never a prompt


def test_the_deep_selftest_without_an_enrollment_or_a_pin(session: Session) -> None:
    deps = fake_deps(keys=session.keys)
    request = {**session.request("selftest"), "deep": True}
    assert worker.selftest("darwin", request=request, deps=deps)["details"]["touch_id"]["pin"] == (
        "unknown"
    )
    session.auth = FakeLocalAuth(biometry=Biometry("none", "no_sensor"))
    session.enroll()
    deps = fake_deps(keys=session.keys)
    assert worker.selftest("darwin", request=request, deps=deps)["details"]["touch_id"]["pin"] == (
        "not_pinned"
    )
