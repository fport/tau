"""The guard window (issue 126): the model, the frame tee, the layout, the request field, the
worker's window mode with a recording view, the Esc cancel through the runners and the
service, the ``window`` knob and ``--no-window``. Nothing here opens a window or a camera."""

from __future__ import annotations

import io
import json
import os
import random
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from tau_core.guard import VERDICT_REASONS, config_problem
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_guard import window, worker
from tau_guard.config import SettingsError, parse_settings
from tau_guard.local import run_local
from tau_guard.runner import CancelRequest, Malformed, Progress, WorkerRun, parse_line
from tau_guard.state import Outcome
from tau_guard.store import MemoryKeyStore
from tau_guard.strings import WINDOW_MESSAGES
from tau_guard.testing import (
    FakeLocalAuth,
    RecordingView,
    SimulatedUser,
    fake_deps,
    fake_worker_command,
    match,
    read_requests,
    write_script,
)
from tau_guard.window import (
    PURPOSES,
    RESULT_SECONDS,
    UI_FPS,
    Cancelled,
    Intro,
    NullView,
    SafeView,
    WatchedSource,
    WindowModel,
    compact_layout,
    cover_layout,
    headless_reason,
    intro_from_request,
    window_field,
    window_keys,
)


@pytest.fixture(autouse=True)
def gui_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window path may run here (with fake windows only): no SSH, no TAU_GUARD_WINDOW."""
    monkeypatch.delenv("TAU_GUARD_WINDOW", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)


class Clock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


def texts(language: str = "en") -> dict[str, str]:
    return window_field(language, "unlock")["texts"]


# -- the message table and the request field -----------------------------------------------------


def test_every_window_message_has_both_languages() -> None:
    for key, templates in WINDOW_MESSAGES.items():
        assert key.startswith(("guard.window.", "guard.cli.window.")), key
        assert set(templates) == set(LANGUAGES), key
        assert MESSAGES[key] == templates
    for key in window_keys():
        assert key in WINDOW_MESSAGES, key


def test_the_hud_lines_are_written_in_upper_case() -> None:
    for key, templates in WINDOW_MESSAGES.items():
        if key.startswith(("guard.window.step.", "guard.window.hint.", "guard.window.result.")):
            for text in templates.values():
                assert text == text.upper() or "{" in text, key


def test_the_request_field_carries_every_line_in_the_language() -> None:
    field = window_field("tr", "step_up")
    assert field["purpose"] == "step_up" and field["language"] == "tr"
    for key in window_keys():
        assert field["texts"][key] == WINDOW_MESSAGES[key]["tr"]
    for reason in VERDICT_REASONS:
        assert (
            field["texts"][f"guard.verdict.{reason}"] == MESSAGES[f"guard.verdict.{reason}"]["tr"]
        )
    assert "{tool}" in field["texts"]["guard.window.purpose.step_up"]  # filled by the worker
    assert len(json.dumps(field)) < worker.MAX_REQUEST // 4
    assert window_field("en", "nonsense")["purpose"] == "unlock"


def test_intro_from_request() -> None:
    field = window_field("en", "unlock")
    assert intro_from_request("verify", {"kind": "unlock"}) is None
    assert intro_from_request("selftest", {"window": field}) is None
    assert intro_from_request("forget", {"window": field}) is None
    intro = intro_from_request(
        "verify", {"kind": "step_up", "window": {**field, "purpose": "x"}, "tool": "lamp"}
    )
    assert intro is not None and intro.purpose == "step_up" and intro.tool == "lamp"
    assert intro_from_request("enroll", {"window": field}).purpose == "enroll"
    dirty = {"a": "ok", "b": 3, "c": "x" * 1000, "d": "bad\x1b[0m", 7: "key"}
    intro = intro_from_request("touch_id", {"kind": "recheck", "window": {"texts": dirty}})
    assert intro.texts == {"a": "ok"} and intro.purpose == "recheck" and intro.language == "en"
    assert intro_from_request("verify", {"window": {}, "tool": "\x00"}).tool is None


def test_headless_reasons() -> None:
    assert headless_reason({}, "linux") == "platform"
    assert headless_reason({"SSH_CONNECTION": "1 2 3 4"}, "darwin") == "ssh"
    assert headless_reason({"TAU_GUARD_WINDOW": "0"}, "darwin") == "disabled"
    assert headless_reason({"TAU_GUARD_WINDOW": "off"}, "darwin") == "disabled"
    assert headless_reason({"TAU_GUARD_WINDOW": "1"}, "darwin") is None
    assert headless_reason({}, "darwin") is None


# -- the model -----------------------------------------------------------------------------------


def model(op: str = "verify", purpose: str = "unlock", language: str = "en", **kw: Any):
    clock = Clock()
    return WindowModel(Intro(op, purpose, texts(language), language, **kw), clock=clock), clock


def test_a_check_from_start_to_result() -> None:
    m, clock = model()
    scene = m.scene()
    assert scene.mode == "cover" and scene.phase == "running" and scene.glyph is None
    assert scene.headline == "STARTING CAMERA" and scene.countdown is None
    assert scene.purpose == "UNLOCK" and scene.cancel == "ESC · CANCEL"
    m.step("look", clock.now + 10.0)
    clock.now += 2.5
    scene = m.scene()
    assert scene.glyph == "look" and scene.countdown == pytest.approx(0.75)
    m.hint("too_dark")
    assert m.scene().hint == "TOO DARK · FIND MORE LIGHT"
    m.step("look", clock.now + 7.5)  # the same deadline again: the countdown goes on
    assert m.scene().countdown == pytest.approx(0.75)
    m.step("turn_left", clock.now + 3.5)
    m.hint(None)
    scene = m.scene()
    assert (scene.glyph, scene.headline, scene.hint) == ("left", "TURN LEFT", "")
    assert scene.countdown == pytest.approx(1.0)
    clock.now += 4.0
    assert m.scene().countdown == 0.0
    m.step("turn_right", clock.now + 3.5)
    assert m.scene().glyph == "right"
    m.result(True, "match")
    m.step("look", clock.now + 3)  # nothing moves after the result
    scene = m.scene()
    assert (scene.phase, scene.glyph, scene.headline) == ("passed", "check", "UNLOCKED")
    assert scene.countdown is None and scene.since_result == 0.0


def test_results_by_purpose_and_reason() -> None:
    for purpose, headline in (
        ("unlock", "UNLOCKED"),
        ("recheck", "PRESENCE CONFIRMED"),
        ("step_up", "CONFIRMED"),
        ("check", "VERIFIED"),
        ("enroll", "ENROLLED"),
    ):
        m, _ = model("enroll" if purpose == "enroll" else "verify", purpose)
        m.result(True, "match")
        assert m.scene().headline == headline
    m, _ = model()
    m.result(False, "multiple_faces")
    scene = m.scene()
    assert (scene.phase, scene.glyph, scene.headline) == ("failed", "cross", "NOT VERIFIED")
    assert scene.detail == "More than one face was seen."
    m, _ = model(language="tr")
    m.result(False, None)
    assert m.scene().detail == MESSAGES["guard.verdict.error"]["tr"]
    m, _ = model("enroll", "enroll", language="tr")
    m.result(False, "timeout")
    scene = m.scene()
    assert scene.headline == WINDOW_MESSAGES["guard.window.result.enroll_failed"]["tr"]
    reason = MESSAGES["guard.cli.enroll.reason.timeout"]["tr"]
    assert reason[0].islower() and scene.detail == reason[0].upper() + reason[1:]


def test_enrollment_poses_and_samples() -> None:
    m, clock = model("enroll", "enroll")
    m.step("touch_id", None)
    scene = m.scene()
    assert scene.mode == "compact" and scene.glyph == "touch"
    assert scene.detail == "CONFIRM IN THE MACOS PROMPT"
    m.step("starting", None)
    assert m.scene().mode == "cover"
    m.samples(4, 10)
    m.step("look_up", clock.now + 3)
    scene = m.scene()
    assert (scene.glyph, scene.detail, scene.samples) == ("up", "4/10 SAMPLES", (4, 10))
    m.step("look_down", clock.now + 3)
    assert m.scene().glyph == "down"
    m.step("turn_left", clock.now + 3)
    m.step("turn_more", clock.now + 2)
    scene = m.scene()
    assert (scene.glyph, scene.double, scene.headline) == ("left", True, "TURN FURTHER")
    m.samples(14, 10)
    assert m.scene().detail == "10/10 SAMPLES"


def test_the_touch_id_op_is_the_compact_panel() -> None:
    m, _ = model("touch_id", "unlock")
    scene = m.scene()
    assert scene.mode == "compact" and scene.headline == "TOUCH THE SENSOR"
    m.result(True, "match")
    assert m.scene().mode == "compact" and m.scene().headline == "UNLOCKED"


def test_the_step_up_names_its_tool() -> None:
    m, _ = model(purpose="step_up", tool="robot.move")
    assert m.scene().purpose == "STEP-UP · robot.move"
    m, _ = model(purpose="step_up", language="tr")
    template = WINDOW_MESSAGES["guard.window.purpose.step_up"]["tr"]
    assert m.scene().purpose == template.replace("{tool}", "-")


def test_closing() -> None:
    m, clock = model()
    assert not m.closed()
    m.close(RESULT_SECONDS)
    clock.now += 1.0
    assert not m.closed()
    m.close(0.0)  # the earlier close wins
    assert m.closed()
    m.start(m.intro)  # a new attempt reopens
    assert not m.closed()


# -- the frame tee -------------------------------------------------------------------------------


def test_the_verifier_gets_every_frame_and_the_view_a_throttled_subset() -> None:
    user = SimulatedUser(duration=2.0, fps=30.0)
    source = user.source()
    view = RecordingView()
    ticks: list[int] = []
    watched = WatchedSource(source, view, tick=lambda: ticks.append(1))
    watched.open()
    got = []
    while (frame := watched.read()) is not None:
        got.append(frame)
    watched.close()
    assert len(got) == 60 == source.reads and source.closed
    assert 0 < len(view.frames) <= 2 * UI_FPS + 1 < len(got)
    assert all(image is frame.image for image, frame in zip(view.frames, got[::2], strict=False))
    assert len(ticks) == 60
    assert watched.open_seconds == source.open_seconds  # the source's attributes pass through


def test_a_cancel_stops_the_next_read() -> None:
    cancel = threading.Event()
    source = SimulatedUser(duration=1.0).source()
    watched = WatchedSource(source, NullView(), cancel=cancel)
    watched.open()
    assert watched.read() is not None
    cancel.set()
    with pytest.raises(Cancelled):
        watched.read()
    with pytest.raises(Cancelled):
        WatchedSource(SimulatedUser().source(), NullView(), cancel=cancel).open()


def test_a_broken_view_never_breaks_the_check() -> None:
    logged: list[str] = []
    view = SafeView(RecordingView(fail="frame"), logged.append)
    view.start(Intro("verify", "unlock", {}))
    view.frame(object())
    view.frame(object())
    view.result(True, "match")
    assert view.broken and len(logged) == 1 and "frame failed" in logged[0]


# -- layout --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [(1024, 610), (1280, 775), (1440, 875), (1512, 945), (1728, 1085), (2560, 1415), (3840, 2135)],
)
def test_the_cover_layout_fits(size: tuple[int, int]) -> None:
    lay = cover_layout(*size)
    header_bottom = lay.header_y + lay.small_size * 3
    assert lay.up[1] - lay.tri / 2 > header_bottom
    assert lay.headline_y - lay.headline_size / 2 > lay.cy + lay.outer
    assert lay.hint_y > lay.headline_y and lay.detail_y > lay.hint_y
    assert lay.detail_y + lay.small_size * 2.5 < lay.chip[1]
    assert lay.chip[1] + lay.chip[3] < lay.height
    assert lay.left[0] - lay.tri > 0 and lay.right[0] + lay.tri < lay.width
    x, y, w, h = lay.hud
    for px, py in (lay.left, lay.right, lay.up, lay.down):
        assert x <= px - lay.tri / 2 and px + lay.tri / 2 <= x + w and y <= py - lay.tri / 2
    assert y + h >= lay.detail_y + lay.small_size * 2
    assert lay.radius < lay.ring < lay.comet < lay.dial < lay.outer


def test_the_compact_layout_keeps_the_glyph_left_of_the_text() -> None:
    lay = compact_layout()
    assert lay.cx + lay.outer < lay.width / 2 and lay.hud == (0.0, 0.0, lay.width, lay.height)


# -- the worker with a window --------------------------------------------------------------------


class Worker:
    """An enrolled data dir and the worker's operations in-process with fakes."""

    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir()
        self.keys = MemoryKeyStore()
        self.auth = FakeLocalAuth()
        self.user = SimulatedUser()
        self.sources: list[Any] = []
        enrolled = self.run("enroll", self.request("enroll"), user=SimulatedUser(duration=25))
        assert enrolled["ok"] is True

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

    def deps(self, user: SimulatedUser, source: Any = None) -> Any:
        self.user = user

        def make(camera: str) -> Any:
            made = source or user.source()
            self.sources.append(made)
            return made

        return fake_deps(
            source=make, keys=self.keys, local_auth=self.auth, rng=random.Random(11), clock=user.now
        )

    def run(
        self,
        op: str,
        request: dict,
        *,
        user: SimulatedUser | None = None,
        view: Any = None,
        source: Any = None,
    ) -> dict:
        user = user or SimulatedUser()
        lines: list[dict] = []

        def emit(message: dict) -> None:
            lines.append(message)
            if message["type"] == "progress":
                user.on_progress(message)

        self.lines = lines
        return worker.run(op, request, deps=self.deps(user, source), emit=emit, view=view)


@pytest.fixture
def enrolled(tmp_path: Path) -> Worker:
    return Worker(tmp_path)


def test_the_view_follows_a_check_and_the_verifier_sees_every_frame(enrolled: Worker) -> None:
    request = enrolled.request("verify", "unlock", window=window_field("en", "unlock"))
    headless = enrolled.run("verify", request)
    reads = enrolled.sources[-1].reads
    view = RecordingView()
    shown = enrolled.run("verify", request, view=view)
    assert shown == headless and shown["ok"] is True  # the window changes nothing
    assert enrolled.sources[-1].reads == reads  # the verifier got every frame
    names = view.names()
    assert names[0] == "start" and view.calls[0] == ("start", "verify", "unlock")
    assert names[-1] == "result" and view.calls[-1] == ("result", True, "match")
    steps = [call[1] for call in view.calls if call[0] == "step"]
    assert steps[0] == "starting" and "look" in steps
    assert sum(step.startswith("turn_") for step in steps) == 2
    deadlines = [call[2] for call in view.calls if call[0] == "step" and call[1] == "turn_left"]
    assert all(isinstance(value, float) for value in deadlines)  # monotonic, not ISO
    assert "hint" in names and 0 < len(view.frames) < reads


def test_the_enrollment_view_counts_samples(enrolled: Worker) -> None:
    view = RecordingView()
    request = enrolled.request("enroll", window=window_field("en", "enroll"))
    answer = enrolled.run("enroll", request, user=SimulatedUser(duration=25), view=view)
    assert answer["ok"] is True
    assert view.calls[0] == ("start", "enroll", "enroll")
    steps = [call[1] for call in view.calls if call[0] == "step"]
    assert steps[:2] == ["touch_id", "starting"]
    counts = [call[1] for call in view.calls if call[0] == "samples"]
    assert counts[0] == 0 and counts[-1] >= 10 and counts == sorted(counts)
    assert all(call[2] == 10 for call in view.calls if call[0] == "samples")


def test_the_touch_id_op_shows_the_panel(enrolled: Worker) -> None:
    view = RecordingView()
    request = enrolled.request(
        "touch_id", "step_up", policy={"step_up": "touch_id"}, window=window_field("en", "step_up")
    )
    enrolled.auth = FakeLocalAuth("ok")
    answer = enrolled.run("touch_id", request, view=view)
    assert view.names() == ["start", "step", "hint", "result"]
    assert view.calls[1] == ("step", "touch_id", None) and view.calls[-1][1] == answer["ok"]


def test_a_refusal_before_the_camera_is_shown_as_the_result(tmp_path: Path) -> None:
    view = RecordingView()
    request = {"kind": "unlock", "data_dir": str(tmp_path), "window": window_field("en", "unlock")}
    answer = worker.run("verify", request, deps=fake_deps(), view=view)
    assert answer["reason"] == "not_enrolled"
    assert view.names() == ["start", "result"] and view.calls[-1] == (
        "result",
        False,
        "not_enrolled",
    )


class Blocking:
    """A frame source that stops after ``after`` frames until ``release`` is set."""

    def __init__(self, user: SimulatedUser, after: int = 3) -> None:
        self.inner = user.source()
        self.after = after
        self.release = threading.Event()
        self.reached = threading.Event()
        self.closed = False

    def open(self) -> None:
        self.inner.open()

    def read(self) -> Any:
        if self.inner.reads >= self.after:
            self.reached.set()
            self.release.wait(5.0)
        return self.inner.read()

    def close(self) -> None:
        self.closed = True
        self.inner.close()

    @property
    def open_seconds(self) -> float | None:
        return self.inner.open_seconds


class Output:
    """What the worker wrote: stdout as protocol lines, stderr (``worker.log``) as text."""

    def __init__(self, capsys: pytest.CaptureFixture) -> None:
        self.capsys = capsys
        self.out = ""
        self.err = ""

    def read(self) -> Output:
        got = self.capsys.readouterr()
        self.out += got.out
        self.err += got.err
        return self

    def lines(self) -> list[dict]:
        self.read()
        return [json.loads(line) for line in self.out.splitlines() if line.strip()]


@pytest.fixture
def output(capsys: pytest.CaptureFixture) -> Output:
    return Output(capsys)


def main_run(
    enrolled: Worker,
    view: RecordingView,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: Any = None,
    user: SimulatedUser | None = None,
) -> int:
    """``worker.main`` in-process with a fake window; the simulated user watches stdout."""
    request = enrolled.request("verify", "unlock", window=window_field("en", "unlock"))
    user = user or SimulatedUser()
    deps = enrolled.deps(user, source)
    real = worker.emit_line

    def emit_line(stream: Any, message: dict) -> None:
        if message.get("type") == "progress":
            user.on_progress(message)
        real(stream, message)

    monkeypatch.setattr(worker, "emit_line", emit_line)
    stdin = io.StringIO(json.dumps(request))
    return worker.main(["verify"], stdin=stdin, deps=deps, open_view=view.opener)


def test_main_shows_the_result_then_closes(
    enrolled: Worker, output: Output, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = signal.getsignal(signal.SIGTERM)
    view = RecordingView()
    code = main_run(enrolled, view, monkeypatch)
    lines = output.lines()
    assert code == 0 and lines[-1]["type"] == "verdict" and lines[-1]["ok"] is True
    assert any(line["type"] == "progress" for line in lines)
    assert view.opened_with.purpose == "unlock"
    assert view.calls[-1] == ("close", RESULT_SECONDS) and ("result", True, "match") in view.calls
    assert signal.getsignal(signal.SIGTERM) is previous


def test_esc_writes_a_cancel_line_and_no_verdict(
    enrolled: Worker, output: Output, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = SimulatedUser()
    source = Blocking(user)

    def press_esc(view: RecordingView) -> None:
        assert source.reached.wait(5.0)
        view.on_cancel()
        view.on_cancel()  # twice: one line
        source.release.set()

    view = RecordingView(during_run=press_esc)
    code = main_run(enrolled, view, monkeypatch, source=source, user=user)
    lines = output.lines()
    assert code == 130
    assert [line for line in lines if line["type"] != "progress"] == [{"type": "cancel"}]
    assert source.closed  # the check unwound and released the camera
    assert view.calls[-1] == ("close", 0.0) and not any(c[0] == "result" for c in view.calls)


def test_sigterm_in_window_mode_closes_and_stops_the_check(
    enrolled: Worker, output: Output, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = SimulatedUser()
    source = Blocking(user)

    def terminate(view: RecordingView) -> None:
        assert source.reached.wait(5.0)
        signal.raise_signal(signal.SIGTERM)  # the worker's handler: closes, never raises
        source.release.set()

    previous = signal.getsignal(signal.SIGTERM)
    view = RecordingView(during_run=terminate)
    code = main_run(enrolled, view, monkeypatch, source=source, user=user)
    assert code == 143 and signal.getsignal(signal.SIGTERM) is previous
    assert not any(line["type"] in ("verdict", "cancel") for line in output.lines())
    assert ("close", 0.0) in view.calls
    deadline = time.monotonic() + 5
    while not source.closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert source.closed


def test_a_window_that_breaks_leaves_the_check_running(
    enrolled: Worker,
    output: Output,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = RecordingView(fail="run")
    code = main_run(enrolled, view, monkeypatch)
    assert code == 0 and output.lines()[-1]["ok"] is True
    assert "window: failed (RuntimeError)" in output.read().err


@pytest.mark.parametrize(
    ("env", "opened", "reason"),
    [
        ({"SSH_CONNECTION": "100.x.y.z 1 100.x.y.z 22"}, False, "ssh"),
        ({"TAU_GUARD_WINDOW": "0"}, False, "disabled"),
    ],
)
def test_headless_fallbacks(
    enrolled: Worker,
    output: Output,
    monkeypatch: pytest.MonkeyPatch,
    env: dict,
    opened: bool,
    reason: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    view = RecordingView()
    code = main_run(enrolled, view, monkeypatch)
    assert code == 0 and output.lines()[-1]["ok"] is True
    assert view.opened_with is None and view.calls == []
    assert f"window: not shown ({reason})" in output.read().err


def test_an_opener_that_refuses_or_raises_runs_headless(enrolled: Worker, output: Output) -> None:
    request = enrolled.request("verify", "recheck", window=window_field("en", "recheck"))
    for opener in (
        lambda intro, on_cancel: (None, "no_gui_session"),
        lambda intro, on_cancel: 1 / 0,
    ):
        code = worker.main(
            ["verify"],
            stdin=io.StringIO(json.dumps(request)),
            deps=enrolled.deps(SimulatedUser()),
            open_view=opener,
        )
        assert code == 0
    err = output.read().err
    assert "window: not shown (no_gui_session)" in err and "ZeroDivisionError" in err
    assert [line["type"] for line in output.lines()].count("verdict") == 2


def test_a_request_without_the_field_never_opens_a_window(enrolled: Worker, output: Output) -> None:
    view = RecordingView()
    request = enrolled.request("verify", "recheck")
    code = worker.main(
        ["verify"],
        stdin=io.StringIO(json.dumps(request)),
        deps=enrolled.deps(SimulatedUser()),
        open_view=view.opener,
    )
    assert code == 0 and view.opened_with is None


def test_without_pyobjc_the_overlay_answers_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AppKit", "Quartz", "Foundation", "objc"):
        monkeypatch.setitem(sys.modules, name, None)
    from tau_guard import overlay

    assert overlay.gui_reason() == "pyobjc_missing"
    view, reason = overlay.open_view(Intro("verify", "unlock", {}), on_cancel=lambda: None)
    expected = "pyobjc_missing" if sys.platform == "darwin" else "platform"
    assert view is None and reason == expected


def test_the_window_modules_import_without_appkit() -> None:
    import subprocess

    names = ("AppKit", "Quartz", "Foundation", "objc", "numpy", "cv2", "tau_core")
    code = (
        "import sys, tau_guard.overlay, tau_guard.window; "
        f"print(sorted(m for m in {names!r} if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]", out.stderr


def test_the_demo_script_is_well_formed() -> None:
    events = window.demo_events(texts())
    assert [at for at, _, _ in events] == sorted(at for at, _, _ in events)
    names = {name for _, name, _ in events}
    assert names <= {"start", "step", "hint", "samples", "result", "close"}
    view = RecordingView()
    for _, name, args in events:
        getattr(view, name)(*args)
    assert ("result", True, "match") in view.calls and (
        "result",
        False,
        "multiple_faces",
    ) in view.calls
    assert view.calls[-1] == ("close", RESULT_SECONDS)
    starts = [call for call in view.calls if call[0] == "start"]
    assert [call[2] for call in starts] == ["unlock", "step_up", "enroll"]
    frame = window.synthetic_frame((30.0, 0.0))
    assert frame.shape == (480, 640, 3) and frame.dtype.name == "uint8" and frame.max() < 140


# -- the cancel line through the runners ---------------------------------------------------------


def test_the_cancel_line_parses_only_for_window_operations() -> None:
    raw = b'{"type": "cancel"}'
    for op in ("verify", "enroll", "touch_id"):
        assert isinstance(parse_line(raw, op=op), CancelRequest)
    for op in ("selftest", "forget"):
        with pytest.raises(Malformed):
            parse_line(raw, op=op)


def cancel_run(tmp_path: Path, steps: list[dict], **kwargs: Any) -> tuple[WorkerRun, list, list]:
    script = write_script(tmp_path / "script.json", [steps])
    progress: list[Progress] = []
    done: list[Outcome] = []
    run = WorkerRun(
        "verify",
        {"v": 1},
        command=fake_worker_command(script),
        log_dir=tmp_path,
        timeout=10,
        on_progress=progress.append,
        on_done=done.append,
        **kwargs,
    )
    run.start()
    return run, progress, done


def test_worker_run_hands_esc_to_the_service(tmp_path: Path) -> None:
    cancels: list[int] = []
    steps = [{"progress": "look"}, {"raw": '{"type": "cancel"}'}, {"hang": True}]
    run, progress, done = cancel_run(tmp_path, steps, on_cancel=lambda: cancels.append(1))
    deadline = time.monotonic() + 10
    while not cancels and time.monotonic() < deadline:
        time.sleep(0.01)
    assert cancels == [1] and [p.step for p in progress] == ["look"] and done == []
    run.stop("cancelled")  # what the service's kill effect does
    assert done == [Outcome(False, "cancelled")] and run.wait(5)


def test_worker_run_without_a_handler_stops_as_cancelled(tmp_path: Path) -> None:
    run, _, done = cancel_run(tmp_path, [{"raw": '{"type": "cancel"}'}, {"hang": True}])
    deadline = time.monotonic() + 10
    while not done and time.monotonic() < deadline:
        time.sleep(0.01)
    assert done == [Outcome(False, "cancelled")] and run.wait(5)


def test_run_local_answers_cancelled(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [[{"progress": "look"}, {"raw": '{"type":"cancel"}'}, {"hang": True}]],
    )
    started = time.monotonic()
    answer = run_local(
        tmp_path / "guard", "verify", {}, timeout=10, command=fake_worker_command(script)
    )
    assert answer["ok"] is False and answer["reason"] == "cancelled" and answer["cancelled"] is True
    assert time.monotonic() - started < 5  # stopped at once, not at the timeout


# -- the service ---------------------------------------------------------------------------------


def service_for(tmp_path: Path, runs: list, **table: Any):
    from guard_helpers import FakeHub, guard_config
    from tau_core.hub import ControlApi
    from tau_guard.service import GuardService
    from tau_guard.testing import FakeClock, FakePresence

    config = guard_config(tmp_path, **table)
    work = tmp_path / "worker"
    work.mkdir(exist_ok=True)
    script = write_script(work / "script.json", runs)
    service = GuardService(
        config,
        clock=FakeClock(),
        presence=FakePresence(),
        worker_command=fake_worker_command(script),
        platform="darwin",
        reflex_loop=False,
        attempt_timeout=10.0,
    )
    return service, FakeHub({"control-api": ControlApi(0, lambda: {})}), script


CANCEL = {"raw": '{"type": "cancel"}'}


async def test_esc_in_the_window_cancels_the_attempt_for_every_client(tmp_path: Path) -> None:
    import asyncio

    runs = [[{"progress": "look"}, {"sleep": 0.6}, CANCEL, {"hang": True}]]
    service, hub, script = service_for(tmp_path, runs)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        first = asyncio.ensure_future(service.unlock(channel="tui", client_id="c1"))
        await asyncio.sleep(0.2)
        second = asyncio.ensure_future(service.unlock(channel="cli", client_id="c2"))
        verdicts = await asyncio.wait_for(asyncio.gather(first, second), 10)
        assert [v.reason for v in verdicts] == ["cancelled", "cancelled"]
        status = await service.status()
        assert status.state == "locked" and status.failures == 0
        [request] = [entry["request"] for entry in read_requests(script)]
        assert request["window"]["purpose"] == "unlock" and request["window"]["language"] == "en"
        assert request["window"]["texts"]["guard.window.step.look"] == "LOOK AT THE CAMERA"
    finally:
        await service.stop()


async def test_esc_at_a_head_turn_prompt_still_counts(tmp_path: Path) -> None:
    runs = [[{"progress": "look"}, {"progress": "turn_left"}, CANCEL, {"hang": True}]]
    service, hub, _ = service_for(tmp_path, runs)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        verdict = await service.unlock(channel="tui", client_id="c1")
        assert verdict.reason == "spoof"
        assert (await service.status()).failures == 1
    finally:
        await service.stop()


async def test_window_false_sends_no_window_and_a_step_up_names_its_tool(tmp_path: Path) -> None:
    from tau_core.approval import ApprovalRequest
    from tau_core.tiers import Tier

    service, hub, script = service_for(tmp_path, [[match()]], window=False)
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert (await service.unlock(channel="tui", client_id="c1")).ok
    finally:
        await service.stop()
    assert "window" not in read_requests(script)[-1]["request"]

    other = tmp_path / "other"
    other.mkdir()
    service, hub, script = service_for(other, [[match()]])
    await service.start(hub)  # type: ignore[arg-type]
    try:
        assert (await service.unlock(channel="tui", client_id="c1")).ok
        request = ApprovalRequest("r1", "robot.move", Tier.PHYSICAL, {}, "", "s1", "tui")
        assert await service.step_up(request, client_id="c1")
    finally:
        await service.stop()
    last = read_requests(script)[-1]["request"]
    assert last["kind"] == "step_up" and last["tool"] == "robot.move"
    assert last["window"]["purpose"] == "step_up"


# -- the knob ------------------------------------------------------------------------------------


def test_the_window_knob() -> None:
    assert config_problem({"window": False}) is None
    assert parse_settings({}).window is True
    assert parse_settings({"window": False}).window is False
    with pytest.raises(SettingsError) as caught:
        parse_settings({"window": "yes"})
    assert "window must be true or false" in caught.value.problems[0]
    assert "window" not in parse_settings({}).worker()  # a request field, not a worker knob


def test_purposes_cover_the_worker_kinds() -> None:
    assert set(PURPOSES) == {"unlock", "recheck", "step_up", "enroll", "check"}
    assert os.environ.get("TAU_GUARD_WINDOW") is None  # the autouse fixture cleared it
