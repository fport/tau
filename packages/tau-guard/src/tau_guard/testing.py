"""Test helpers for the guard: a fake clock, a fake presence source and a fake worker.

Nothing here opens a camera, a microphone, the Keychain or a Touch ID prompt.

- :class:`FakeClock`: ``advance(seconds)`` moves wall and monotonic time together;
  ``sleep(seconds)`` moves only the wall clock, as a Mac's monotonic clock stops while the
  machine sleeps.
- :class:`FakePresence`: a :class:`~tau_guard.presence.PresenceSource` whose ``idle_seconds``
  and ``screen_locked`` a test sets.
- The fake worker, ``python -m tau_guard.testing <script> <op>``, speaks the worker protocol
  from a JSON script file (see :func:`write_script`) and appends every request it gets, with
  its pid, to ``requests.jsonl`` next to the script. :func:`fake_worker_command` builds the
  ``worker_command`` for :class:`~tau_guard.service.GuardService`.

A script is a list of runs; each worker takes the first run and leaves the rest (the last run
stays for every later worker). A run is a list of steps:

- ``{"progress": "look", "hint": null, "deadline": null}``: one progress line;
- ``{"verdict": {...}}``: the verdict line (``type`` is added);
- ``{"sleep": 0.2}``; ``{"hang": true}`` (sleep for a long time);
- ``{"raw": "text"}``: a raw stdout line; ``{"stderr": "text"}``: a stderr line;
- ``{"ignore_term": true}``: ignore SIGTERM from here on; ``{"exit": 3}``: exit at once.

Face fakes (issue 112), for the verify, liveness and enrollment state machines and the worker's
operations run in-process:

- :func:`identity` and :func:`variant`: synthetic unit embeddings (a person, and one frame of
  that person); :func:`project_head`: the five landmarks of :data:`tau_guard.engine.HEAD_MODEL`
  turned by a yaw, pitch and roll in degrees and projected through the camera model of
  :func:`tau_guard.engine.head_pose` (``flat=True``: all five points in one plane, a printed
  frontal face turned instead of a head); :func:`face_row`: a synthetic YuNet row built from
  it.
- :class:`Scene`, :class:`FakeEngine`: a "frame" is a :class:`Scene` (rows, embeddings,
  brightness, sharpness) and the engine reads it back; :class:`FakeFrameSource` yields frames
  and records ``open``/``close``.
- :class:`SimulatedUser`: a synthetic person who follows the published prompts (turns, holds,
  returns), with switches for the ways an attempt must fail; its :meth:`SimulatedUser.now` is
  the clock.
- :class:`FakeLocalAuth` and :func:`fake_deps` (with ``tau_guard.store.MemoryKeyStore``).

The guard window (issue 126): :class:`RecordingView` is a
:class:`~tau_guard.window.GuardView` that records every call and never opens a window.
"""

from __future__ import annotations

import json
import math
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tau_guard.state import Reading

__all__ = [
    "FINGERPRINTS",
    "OTHER_FINGERPRINTS",
    "OWNER",
    "STRANGER",
    "FakeClock",
    "FakeEngine",
    "FakeFrameSource",
    "FakeLocalAuth",
    "FakePresence",
    "RecordingView",
    "Scene",
    "SimulatedUser",
    "face_row",
    "fake_deps",
    "fake_worker_command",
    "identity",
    "match",
    "project_head",
    "read_requests",
    "variant",
    "write_script",
]

START = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """A clock that moves only when told to."""

    def __init__(self, start: datetime = START, monotonic: float = 1000.0) -> None:
        self._wall = start
        self._mono = monotonic

    def wall(self) -> datetime:
        return self._wall

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._wall += timedelta(seconds=seconds)
        self._mono += seconds

    def sleep(self, seconds: float) -> None:
        """The machine slept: wall time moves, monotonic time does not."""
        self._wall += timedelta(seconds=seconds)


class FakePresence:
    """Presence a test controls; ``None`` means unknown."""

    def __init__(self, idle_seconds: float | None = 0.0, screen_locked: bool | None = False):
        self.idle_seconds = idle_seconds
        self.screen_locked = screen_locked
        self.reads = 0

    def read(self) -> Reading:
        self.reads += 1
        return Reading(self.idle_seconds, self.screen_locked)


def match(method: str = "face", score: float = 0.71, liveness: str = "challenge") -> dict:
    """A passing verdict step."""
    return {
        "verdict": {
            "ok": True,
            "reason": "match",
            "method": method,
            "score": score,
            "liveness": liveness,
        }
    }


def write_script(path: Path, runs: Sequence[Sequence[dict[str, Any]]]) -> Path:
    """Write a fake-worker script (a list of runs) to ``path``."""
    path.write_text(json.dumps([list(run) for run in runs]), encoding="utf-8")
    return path


def read_requests(script: Path) -> list[dict[str, Any]]:
    """What the fake workers were asked, oldest first (``op``, ``pid``, ``request``)."""
    path = script.parent / "requests.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fake_worker_command(script: Path) -> list[str]:
    """``worker_command`` for a :class:`~tau_guard.service.GuardService` under test."""
    return [sys.executable, "-m", "tau_guard.testing", str(script)]


# -- face fakes (issue 112) -----------------------------------------------------------------------


def identity(seed: int, dim: int = 128) -> tuple[float, ...]:
    """A synthetic person: a random unit vector (people are nearly orthogonal)."""
    import random as _random

    from tau_guard.engine import normalise

    rng = _random.Random(seed)
    return normalise(rng.gauss(0.0, 1.0) for _ in range(dim))


def variant(base: Sequence[float], seed: int, noise: float = 0.05) -> tuple[float, ...]:
    """One frame of the person ``base``: cosine to ``base`` about 0.87 with the default noise,
    about 0.76 between two frames."""
    import random as _random

    from tau_guard.engine import normalise

    rng = _random.Random(seed)
    return normalise(value + rng.gauss(0.0, noise) for value in base)


OWNER = identity(1)
STRANGER = identity(2)


def _rotation(yaw: float, pitch: float, roll: float) -> list[list[float]]:
    """The head's rotation (degrees): yaw about the camera's vertical axis (positive: the face
    turns toward the image's right edge), then pitch (positive: up), then roll."""
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    ry = [[math.cos(y), 0.0, -math.sin(y)], [0.0, 1.0, 0.0], [math.sin(y), 0.0, math.cos(y)]]
    rx = [[1.0, 0.0, 0.0], [0.0, math.cos(p), math.sin(p)], [0.0, -math.sin(p), math.cos(p)]]
    rz = [[math.cos(r), -math.sin(r), 0.0], [math.sin(r), math.cos(r), 0.0], [0.0, 0.0, 1.0]]

    def mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return mul(mul(ry, rx), rz)


def project_head(
    *,
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    cx: float = 320.0,
    cy: float = 240.0,
    iod: float = 80.0,
    size: tuple[int, int] = (640, 480),
    flat: bool = False,
) -> list[tuple[float, float]]:
    """The five landmarks (YuNet's order) of :data:`~tau_guard.engine.HEAD_MODEL` turned by
    ``yaw``, ``pitch`` and ``roll`` degrees, at the distance where a frontal head has an eye
    distance of ``iod`` px with its nose tip at (``cx``, ``cy``), through the camera model of
    :func:`~tau_guard.engine.head_pose` (focal length = frame width, principal point in the
    middle). ``flat=True`` puts all five points in one plane first: a printed frontal face,
    turned about the vertical axis by ``yaw``."""
    from tau_guard.engine import HEAD_MODEL

    width, height = size
    focal = float(width)
    eyes = focal * math.dist(HEAD_MODEL[0][:2], HEAD_MODEL[1][:2]) / iod  # the eyes' distance
    distance = eyes - HEAD_MODEL[0][2]  # the nose tip's
    shift = ((cx - width / 2) * distance / focal, (cy - height / 2) * distance / focal, distance)
    rotation = _rotation(yaw, pitch, roll)
    points = []
    for x, y, z in HEAD_MODEL:
        z = 0.0 if flat else z
        cam = [sum(rotation[i][k] * (x, y, z)[k] for k in range(3)) + shift[i] for i in range(3)]
        points.append((focal * cam[0] / cam[2] + width / 2, focal * cam[1] / cam[2] + height / 2))
    return points


def face_row(
    *,
    cx: float = 320.0,
    cy: float = 240.0,
    iod: float = 80.0,
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    score: float = 0.98,
    flat: bool = False,
    jitter: tuple[float, ...] | None = None,
    size: tuple[int, int] = (640, 480),
) -> list[float]:
    """A YuNet row for :func:`project_head` (degrees; ``flat`` for a turned flat photo), with
    a box of 2 x 2.4 eye distances around the landmarks; ``jitter`` adds ten pixel offsets to
    the landmarks (detector noise)."""
    points = project_head(
        yaw=yaw, pitch=pitch, roll=roll, cx=cx, cy=cy, iod=iod, size=size, flat=flat
    )
    marks = [value for point in points for value in point]
    if jitter is not None:
        marks = [value + offset for value, offset in zip(marks, jitter, strict=True)]
    mid_x = sum(marks[0::2]) / 5
    mid_y = sum(marks[1::2]) / 5
    width, height = 2.0 * iod, 2.4 * iod
    return [mid_x - width / 2, mid_y - height / 2, width, height, *marks, score]


@dataclass
class Scene:
    """A synthetic frame: YuNet rows and the embedding of each face."""

    rows: list[list[float]]
    embeddings: list[tuple[float, ...]]
    brightness: float = 120.0
    sharpness: float = 150.0
    size: tuple[int, int] = (640, 480)


class FakeEngine:
    """A :class:`~tau_guard.engine.FaceEngine` that reads :class:`Scene` frames back."""

    def __init__(self, model_sha256: str | None = None) -> None:
        from tau_guard.engine import SFACE_SHA256

        self.model_sha256 = model_sha256 or SFACE_SHA256
        self.embedded = 0

    def detect(self, frame: Scene) -> list[Any]:
        from tau_guard.engine import Face

        return [Face.from_row(row, size=frame.size) for row in frame.rows]

    def brightness(self, frame: Scene, face: Any) -> float:
        return frame.brightness

    def crop(self, frame: Scene, face: Any) -> tuple[Scene, int]:
        from tau_guard.engine import Face

        for index, row in enumerate(frame.rows):
            if Face.from_row(row, size=frame.size) == face:
                return frame, index
        raise LookupError("the face is not in this frame")

    def sharpness(self, crop: tuple[Scene, int]) -> float:
        return crop[0].sharpness

    def embed(self, crop: tuple[Scene, int]) -> tuple[float, ...]:
        from tau_guard.engine import normalise

        self.embedded += 1
        scene, index = crop
        return normalise(scene.embeddings[index])


class FakeFrameSource:
    """A :class:`~tau_guard.camera.FrameSource` over frames (an iterable, or a callable that
    returns one when opened). ``open_error`` raises from :meth:`open`; ``read_error`` raises
    from the first :meth:`read`."""

    def __init__(
        self,
        frames: Any = (),
        *,
        open_error: BaseException | None = None,
        read_error: BaseException | None = None,
    ) -> None:
        self._frames = frames
        self.open_error = open_error
        self.read_error = read_error
        self.opened = False
        self.closed = False
        self.reads = 0
        self._iterator: Any = None
        self._first: float | None = None
        self._last: float | None = None

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened = True
        frames = self._frames() if callable(self._frames) else self._frames
        self._iterator = iter(frames)

    def read(self) -> Any:
        if self.read_error is not None:
            raise self.read_error
        frame = next(self._iterator, None)
        if frame is not None:
            self.reads += 1
            self._first = frame.at if self._first is None else self._first
            self._last = frame.at
        return frame

    def close(self) -> None:
        self.closed = True

    @property
    def open_seconds(self) -> float | None:
        if not self.opened:
            return None
        if self._first is None or self._last is None:
            return 0.0
        return self._last - self._first


@dataclass
class SimulatedUser:
    """A synthetic person in front of the camera who follows the prompts.

    Frames come at ``fps`` from ``start``; :meth:`on_progress` takes the published steps
    (``Progress`` values or protocol lines) and the user reacts after ``reaction`` seconds,
    turning at ``speed`` (degrees per second) to ``amplitude`` degrees in the asked direction
    from the ``frontal`` yaw (``sign`` is how the camera sees a left turn). The head is the 3D
    model of :func:`project_head` with an eye distance of ``iod`` px. Natural touches:
    ``overshoot`` (degrees the head swings past the frontal yaw on the way back before it
    settles), ``sway`` (a slow 0.3 Hz sway of that many degrees, all the time), ``lean`` (the
    head rolls by ``lean`` degrees per degree of turn, toward the side it turns to, as when the
    neck bends into a turn) and ``jitter`` (the detector's landmark noise, standard deviation in
    px, seeded by ``frame_seed``).
    Switches for failures: ``wrong_way``, ``hold=False`` (turn back as soon as the turn is
    reached), ``returns=False`` (never turn back), ``turn=False`` (never turn), ``photo=True``
    (a flat photo of the frontal face turned about the vertical axis instead of a head),
    ``second_face`` (a ``(from, to)`` time window with a second face of ``second_iod``),
    ``jump_at`` (the box moves away at that time), ``gap`` (a ``(from, to)`` time window
    without any face), ``stranger_after`` (the embedding becomes someone else's from that time)
    and ``stranger_after_centers`` (the same, once that many ``center`` prompts were published:
    a face swapped in place)."""

    embedding: tuple[float, ...] = OWNER
    fps: float = 30.0
    start: float = 100.0
    duration: float = 30.0
    frontal: float = 0.0
    sign: int = 1
    amplitude: float = 25.0
    reaction: float = 0.35
    speed: float = 120.0
    iod: float = 80.0
    overshoot: float = 0.0
    sway: float = 0.0
    lean: float = 0.0
    jitter: float = 0.0
    brightness: float = 120.0
    sharpness: float = 150.0
    score: float = 0.98
    wrong_way: bool = False
    hold: bool = True
    returns: bool = True
    turn: bool = True
    photo: bool = False
    second_face: tuple[float, float] | None = None
    second_iod: float = 60.0
    jump_at: float | None = None
    gap: tuple[float, float] | None = None
    stranger_after: float | None = None
    stranger_after_centers: int | None = None
    frame_seed: int = 0
    steps: list[tuple[float, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.t = self.start
        self.yaw = self.frontal
        self.pending: list[tuple[float, float]] = []
        self.target = self.frontal
        self.index = 0

    def now(self) -> float:
        return self.t

    def on_progress(self, message: Any) -> None:
        step = message.get("step") if isinstance(message, dict) else message.step
        if isinstance(message, dict) and message.get("type") not in (None, "progress"):
            return
        self.steps.append((self.t, step))
        when = self.t + self.reaction
        if step in ("turn_left", "turn_right", "turn_more") and self.turn:
            direction = 1 if step == "turn_left" else -1
            if step == "turn_more":
                direction = 1 if self.target - self.frontal >= 0 else -1
            if self.wrong_way:
                direction = -direction
            size = self.amplitude * (1.5 if step == "turn_more" else 1.0)
            target = self.frontal + self.sign * direction * size
            self.pending.append((when, target))
            if not self.hold:
                self.pending.append((when + size / self.speed + 0.05, self.frontal))
        elif step in ("center", "look", "look_up", "look_down") and self.returns:
            side = 1 if self.target - self.frontal >= 0 else -1
            if self.overshoot and self.target != self.frontal:
                swing = self.frontal - side * self.overshoot
                self.pending.append((when, swing))
                span = abs(self.target - swing) / self.speed + 0.15
                self.pending.append((when + span, self.frontal))
            else:
                self.pending.append((when, self.frontal))

    def _move(self, dt: float) -> None:
        while self.pending and self.pending[0][0] <= self.t:
            self.target = self.pending.pop(0)[1]
        step = self.speed * dt
        self.yaw += max(-step, min(step, self.target - self.yaw))

    def _jitter(self) -> tuple[float, ...] | None:
        if not self.jitter:
            return None
        import random as _random

        rng = _random.Random(self.frame_seed * 7919 + self.index)
        return tuple(rng.gauss(0.0, self.jitter) for _ in range(10))

    def scene(self) -> Scene:
        cx = 320.0 if self.jump_at is None or self.t < self.jump_at else 520.0
        yaw = self.yaw + self.sway * math.sin(2 * math.pi * 0.3 * (self.t - self.start))
        row = face_row(
            cx=cx,
            iod=self.iod,
            yaw=yaw,
            roll=self.lean * (self.yaw - self.frontal),
            score=self.score,
            flat=self.photo,
            jitter=self._jitter(),
        )
        rows = [row]
        person = self.embedding
        if self.stranger_after is not None and self.t >= self.stranger_after:
            person = STRANGER
        centers = sum(1 for _, step in self.steps if step == "center")
        if self.stranger_after_centers is not None and centers >= self.stranger_after_centers:
            person = STRANGER
        embeddings = [variant(person, self.frame_seed * 100003 + self.index)]
        window = self.second_face
        if window is not None and window[0] <= self.t < window[1]:
            rows.append(face_row(cx=120.0, cy=200.0, iod=self.second_iod))
            embeddings.append(variant(STRANGER, self.index))
        if self.gap is not None and self.gap[0] <= self.t < self.gap[1]:
            rows, embeddings = [], []
        return Scene(rows, embeddings, self.brightness, self.sharpness)

    def frames(self) -> Any:
        from tau_guard.camera import Frame

        dt = 1.0 / self.fps
        count = int(self.duration * self.fps)
        for index in range(count):
            self.index = index
            self.t = self.start + index * dt
            self._move(dt)
            yield Frame(self.scene(), self.t)

    def source(self) -> FakeFrameSource:
        return FakeFrameSource(self.frames)


FINGERPRINTS = "a1" * 32
"""The fake Mac's enrolled fingerprint set (a ``domainState`` sha256)."""
OTHER_FINGERPRINTS = "b2" * 32
"""The same Mac after someone added a finger."""


class FakeLocalAuth:
    """A :class:`~tau_guard.localauth.LocalAuthFactor` that answers from a list (the last
    answer repeats) and records every call; it never shows a prompt.

    ``biometry`` is what Touch ID looks like (default: available, with :data:`FINGERPRINTS`).
    Like the real factor, the biometrics policy answers ``unavailable`` unless Touch ID is
    available and ``changed`` when a pinned ``domain_state`` differs, both without a prompt
    (no answer is taken from the list); ``prompts`` counts the prompts that were shown."""

    def __init__(self, *outcomes: str, biometry: Any = None) -> None:
        from tau_guard.localauth import Biometry

        self.outcomes = list(outcomes) or ["ok"]
        self.state = biometry or Biometry("available", domain_state=FINGERPRINTS)
        self.calls: list[tuple[str, str]] = []
        self.pins: list[str | None] = []
        self.timeouts: list[float] = []
        self.probes = 0
        self.prompts = 0

    def biometry(self) -> Any:
        self.probes += 1
        return self.state

    def authenticate(
        self,
        policy: str,
        reason: str,
        *,
        timeout: float = 30.0,
        domain_state: str | None = None,
    ) -> str:
        from tau_guard.localauth import BIOMETRICS

        self.calls.append((policy, reason))
        self.pins.append(domain_state)
        self.timeouts.append(timeout)
        if policy == BIOMETRICS:
            if self.state.state != "available":
                return "unavailable"
            if domain_state is not None and domain_state != self.state.domain_state:
                return "changed"
        self.prompts += 1
        return self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]


class RecordingView:
    """A :class:`~tau_guard.window.GuardView` that records every call in :attr:`calls` (the
    frames also in :attr:`frames`) and never opens a window. :meth:`run` first calls
    ``during_run(self)`` (a test's Esc through :attr:`on_cancel`, or a signal), then waits at
    most ``timeout`` seconds for :meth:`close`. ``fail`` names a method that raises. Used as the
    worker's window through ``open_view``: :meth:`opener`."""

    def __init__(
        self,
        *,
        during_run: Callable[[RecordingView], None] | None = None,
        timeout: float = 10.0,
        fail: str | None = None,
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.frames: list[Any] = []
        self.intro: Any = None
        self.on_cancel: Callable[[], None] | None = None
        self.during_run = during_run
        self.timeout = timeout
        self.fail = fail
        self.closed = threading.Event()
        self.opened_with: Any = None

    def _record(self, name: str, *args: Any) -> None:
        if name == self.fail:
            raise RuntimeError(f"{name} is broken")
        self.calls.append((name, *args))

    def opener(self, intro: Any, *, on_cancel: Callable[[], None]) -> tuple[Any, None]:
        self.opened_with = intro
        self.on_cancel = on_cancel
        return self, None

    def start(self, intro: Any) -> None:
        self.intro = intro
        self._record("start", intro.op, intro.purpose)

    def step(self, step: str, deadline: float | None) -> None:
        self._record("step", step, deadline)

    def hint(self, hint: str | None) -> None:
        self._record("hint", hint)

    def frame(self, image: Any) -> None:
        self._record("frame")
        self.frames.append(image)

    def samples(self, count: int, needed: int) -> None:
        self._record("samples", count, needed)

    def result(self, ok: bool, reason: str | None) -> None:
        self._record("result", ok, reason)

    def close(self, delay: float = 0.0) -> None:
        self.calls.append(("close", delay))
        self.closed.set()

    def run(self) -> None:
        if self.fail == "run":
            raise RuntimeError("run is broken")
        if self.during_run is not None:
            self.during_run(self)
        if not self.closed.wait(self.timeout):
            raise AssertionError("the view was never closed")

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


def fake_deps(
    *,
    source: Any = None,
    engine: Any = None,
    keys: Any = None,
    local_auth: Any = None,
    rng: Any = None,
    clock: Any = None,
    wall: Any = None,
    platform: str = "darwin",
    devices: Any = None,
    permission: Any = None,
) -> Any:
    """A :class:`tau_guard.worker.Deps` of fakes; ``source`` is a frame source (or a callable
    taking the camera setting)."""
    import random as _random

    from tau_guard.store import MemoryKeyStore
    from tau_guard.worker import Deps

    chosen_engine = engine or FakeEngine()
    return Deps(
        platform=platform,
        source=source if callable(source) and not hasattr(source, "open") else lambda _: source,
        engine=lambda data_dir: chosen_engine,
        keys=keys if keys is not None else MemoryKeyStore(),
        local_auth=local_auth or FakeLocalAuth(),
        rng=rng or _random.Random(7),
        clock=clock or time.monotonic,
        wall=wall or (lambda: START),
        devices=devices,
        permission=permission,
    )


def _take_run(script: Path) -> list[dict[str, Any]]:
    try:
        runs = json.loads(script.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(runs, list) or not runs:
        return []
    run = runs[0]
    if len(runs) > 1:
        script.write_text(json.dumps(runs[1:]), encoding="utf-8")
    return run if isinstance(run, list) else []


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tau_guard.testing <script> <op>", file=sys.stderr)
        return 2
    script, op = Path(argv[0]), argv[1]
    request = json.loads(sys.stdin.read() or "{}")
    with open(script.parent / "requests.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps({"op": op, "pid": os.getpid(), "request": request}) + "\n")
    for step in _take_run(script):
        if "progress" in step:
            message = {
                "type": "progress",
                "step": step["progress"],
                "hint": step.get("hint"),
                "deadline": step.get("deadline"),
            }
            _say(json.dumps(message))
        elif "verdict" in step:
            _say(json.dumps({"type": "verdict", **step["verdict"]}))
        elif "sleep" in step:
            time.sleep(float(step["sleep"]))
        elif "hang" in step:
            time.sleep(3600)
        elif "raw" in step:
            _say(str(step["raw"]))
        elif "stderr" in step:
            print(step["stderr"], file=sys.stderr, flush=True)
        elif "ignore_term" in step:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        elif "exit" in step:
            return int(step["exit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
