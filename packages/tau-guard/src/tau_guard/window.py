"""The guard window (issue 126): what a check shows on the Mac's screen while it runs.

The owner cannot follow "turn left" or "move closer" as scrolling text without seeing the
camera, so the **worker itself** shows a full-screen window during an attempt: the mirrored
camera picture in a neon τ ring, the current step as a large triangle and an uppercase line,
the live hint, the countdown to the step's deadline and, at the end, the result. The worker
already holds the frames (ADR 0008 decision 2), so there is no second camera session and no
frame transport: frames still exist only in the worker's memory and on the Mac's screen.

This module is the part without AppKit, so it imports on Linux and in tests:

- :class:`GuardView` is the seam the worker talks to (``start``, ``step``, ``hint``,
  ``frame``, ``samples``, ``result``, ``close``, and ``run`` on the main thread).
  :class:`NullView` does nothing; :class:`tau_guard.overlay.MacOverlayView` is the macOS
  window; ``tau_guard.testing.RecordingView`` records the calls.
- :class:`WatchedSource` wraps the camera's frame source for the check: the verifier gets
  every frame, the view at most :data:`UI_FPS` of them per second (a dropped frame is only
  dropped for the picture), and a cancel (Esc, or SIGTERM in window mode) raises
  :class:`Cancelled` at the next frame so the check unwinds and releases the camera.
- :class:`WindowModel` turns the calls into a :class:`Scene` (what to draw now) with a clock;
  :func:`cover_layout` and :func:`compact_layout` place it on a screen.
- :func:`window_field` builds the ``window`` field of a worker request in the hub or the CLI
  (``{"purpose", "language", "texts"}``: every line already in the owner's UI language, since
  the worker never imports tau-core), :func:`intro_from_request` reads it back in the worker.
  A request without the field runs headless exactly as before.
- :func:`headless_reason` says why a worker shows no window even though the request asks for
  one: not macOS, a session that came in over SSH, or ``TAU_GUARD_WINDOW=0``. The GUI checks
  (a window server, pyobjc's AppKit) happen in :func:`tau_guard.overlay.open_view`.
- :func:`demo_events` and :func:`synthetic_frame` drive ``tau guard window --demo``: a scripted
  unlock, a failed step-up and an enrollment on a dark synthetic picture, no camera.

Nothing here writes a frame anywhere.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "DISABLE_ENV",
    "PURPOSES",
    "RESULT_SECONDS",
    "UI_FPS",
    "WINDOW_OPS",
    "Cancelled",
    "GuardView",
    "Intro",
    "Layout",
    "NullView",
    "SafeView",
    "Scene",
    "WatchedSource",
    "WindowModel",
    "compact_layout",
    "cover_layout",
    "demo_events",
    "headless_reason",
    "intro_from_request",
    "synthetic_frame",
    "window_field",
    "window_keys",
]

logger = logging.getLogger(__name__)

WINDOW_OPS = frozenset({"verify", "enroll", "touch_id"})
"""Worker operations that show the window (``selftest`` and ``forget`` never do)."""
PURPOSES = ("unlock", "recheck", "step_up", "enroll", "check")
"""What the window says the check is for; ``check`` is a CLI check that unlocks nothing."""
RESULT_SECONDS = 1.2
"""How long the result stays on screen before the window closes itself."""
UI_FPS = 20.0
"""The most frames per second the picture gets; the verifier always gets every frame."""
DISABLE_ENV = "TAU_GUARD_WINDOW"
"""``TAU_GUARD_WINDOW=0`` keeps every worker of this process tree headless (tests, recordings)."""
MAX_TEXT = 240
MAX_TEXTS = 128
MAX_TOOL = 48
STEP_KEYS = (
    "starting",
    "look",
    "turn_left",
    "turn_right",
    "center",
    "touch_id",
    "look_up",
    "look_down",
    "turn_more",
)
HINT_KEYS = ("too_dark", "face_too_small", "multiple_faces", "no_face")
ENROLL_REASON_KEYS = ("timeout", "no_match")
"""Enrollment failures with their own, longer explanation (``guard.cli.enroll.reason.*``)."""


class Cancelled(BaseException):  # noqa: N818 (a stop request, not an error)
    """The window was cancelled (Esc) or the worker got SIGTERM in window mode: raised from
    the next frame read, so every ``finally`` runs and the camera is released."""


# -- the request field -----------------------------------------------------------------------


def window_keys() -> list[str]:
    """Every ``guard.window.*`` key the window reads."""
    keys = [f"guard.window.purpose.{purpose}" for purpose in PURPOSES]
    keys += [f"guard.window.step.{step}" for step in STEP_KEYS]
    keys += [f"guard.window.hint.{hint}" for hint in HINT_KEYS]
    keys += [f"guard.window.result.{purpose}" for purpose in PURPOSES]
    keys += [
        "guard.window.result.failed",
        "guard.window.result.enroll_failed",
        "guard.window.samples",
        "guard.window.touch_id",
        "guard.window.cancel",
        "guard.window.privacy",
    ]
    return keys


def window_field(language: str, purpose: str) -> dict[str, Any]:
    """The ``window`` field of a worker request: the purpose, the language and every line the
    window may show, looked up in tau-core's message table (templates keep ``{tool}``,
    ``{count}`` and ``{needed}``; the worker fills them). Used by the hub and the CLI only."""
    from tau_core.guard import VERDICT_REASONS
    from tau_core.i18n import t

    from tau_guard import strings as _strings  # noqa: F401  (registers guard.window.*)

    texts = {key: t(key, language) for key in window_keys()}
    texts.update(
        {
            f"guard.verdict.{reason}": t(f"guard.verdict.{reason}", language)
            for reason in VERDICT_REASONS
        }
    )
    for reason in ENROLL_REASON_KEYS:
        key = f"guard.cli.enroll.reason.{reason}"
        texts[key] = t(key, language)
    return {
        "purpose": purpose if purpose in PURPOSES else "unlock",
        "language": language,
        "texts": texts,
    }


@dataclass(frozen=True)
class Intro:
    """What an attempt's window is about, from the request."""

    op: str
    purpose: str
    texts: Mapping[str, str]
    language: str = "en"
    tool: str | None = None


def _default_purpose(op: str, kind: object) -> str:
    if op == "enroll":
        return "enroll"
    return kind if kind in ("unlock", "recheck", "step_up") else "unlock"


def _clean_text(value: object, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit or not value.isprintable():
        return None
    return value


def intro_from_request(op: str, request: Mapping[str, Any]) -> Intro | None:
    """The window's :class:`Intro` when the request asks for one (a ``window`` object and an
    operation of :data:`WINDOW_OPS`), else ``None`` (headless, as before)."""
    field = request.get("window")
    if op not in WINDOW_OPS or not isinstance(field, dict):
        return None
    purpose = field.get("purpose")
    if purpose not in PURPOSES:
        purpose = _default_purpose(op, request.get("kind"))
    if op == "enroll":
        purpose = "enroll"
    raw = field.get("texts")
    texts: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in list(raw.items())[:MAX_TEXTS]:
            text = _clean_text(value)
            if isinstance(key, str) and text is not None:
                texts[key] = text
    language = field.get("language") if field.get("language") in ("en", "tr") else "en"
    tool = _clean_text(request.get("tool"), MAX_TOOL)
    return Intro(op=op, purpose=str(purpose), texts=texts, language=str(language), tool=tool)


def headless_reason(
    environ: Mapping[str, str] | None = None, platform: str | None = None
) -> str | None:
    """Why a worker shows no window although the request asks for one, before any GUI check:
    ``platform`` (not macOS), ``ssh`` (``SSH_CONNECTION`` is set: the screen is not in front of
    whoever asked) or ``disabled`` (``TAU_GUARD_WINDOW=0``); ``None`` when nothing stops it."""
    import sys

    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform != "darwin":
        return "platform"
    if environ.get(DISABLE_ENV, "").strip().lower() in ("0", "off", "false", "no"):
        return "disabled"
    if environ.get("SSH_CONNECTION"):
        return "ssh"
    return None


# -- the view seam ---------------------------------------------------------------------------


@runtime_checkable
class GuardView(Protocol):
    """What the worker shows while a check runs. Every method but :meth:`run` is called from
    the check's thread and must return at once (store, never draw); :meth:`run` runs the UI on
    the main thread until the window closed."""

    def start(self, intro: Intro) -> None: ...

    def step(self, step: str, deadline: float | None) -> None:
        """A progress step (tau-core's ``PROGRESS_STEPS``) and its deadline in monotonic
        seconds (``None``: no deadline)."""
        ...

    def hint(self, hint: str | None) -> None: ...

    def frame(self, image: Any) -> None:
        """A BGR picture from the camera (a throttled subset of the frames)."""
        ...

    def samples(self, count: int, needed: int) -> None:
        """Enrollment samples kept so far."""
        ...

    def result(self, ok: bool, reason: str | None) -> None: ...

    def close(self, delay: float = 0.0) -> None:
        """Close the window ``delay`` seconds from now (at once for 0)."""
        ...

    def run(self) -> None: ...


class NullView:
    """No window: every call does nothing, :meth:`run` returns at once."""

    def start(self, intro: Intro) -> None:
        pass

    def step(self, step: str, deadline: float | None) -> None:
        pass

    def hint(self, hint: str | None) -> None:
        pass

    def frame(self, image: Any) -> None:
        pass

    def samples(self, count: int, needed: int) -> None:
        pass

    def result(self, ok: bool, reason: str | None) -> None:
        pass

    def close(self, delay: float = 0.0) -> None:
        pass

    def run(self) -> None:
        pass


class SafeView:
    """Wraps a view for the check's thread: a view that raises is logged once and silenced,
    so a broken window never breaks a check."""

    def __init__(self, view: Any, log: Callable[[str], None] | None = None) -> None:
        self.view = view
        self.broken = False
        self._log = log or (lambda message: logger.warning("%s", message))

    def _call(self, name: str, *args: Any) -> None:
        if self.broken:
            return
        try:
            getattr(self.view, name)(*args)
        except Exception as exc:
            self.broken = True
            self._log(f"window: {name} failed ({type(exc).__name__}); the check goes on without it")

    def start(self, intro: Intro) -> None:
        self._call("start", intro)

    def step(self, step: str, deadline: float | None) -> None:
        self._call("step", step, deadline)

    def hint(self, hint: str | None) -> None:
        self._call("hint", hint)

    def frame(self, image: Any) -> None:
        self._call("frame", image)

    def samples(self, count: int, needed: int) -> None:
        self._call("samples", count, needed)

    def result(self, ok: bool, reason: str | None) -> None:
        self._call("result", ok, reason)

    def close(self, delay: float = 0.0) -> None:
        self._call("close", delay)

    def run(self) -> None:
        self.view.run()


class WatchedSource:
    """A :class:`~tau_guard.camera.FrameSource` that shows frames on a view.

    :meth:`read` hands every frame to the check unchanged; the view gets one when at least
    ``1 / fps`` seconds (on the frames' own clock) passed since the last one it got, so the
    picture never slows the check. With ``cancel`` set, the next read raises
    :class:`Cancelled`. ``tick`` runs after each read (the enrollment's sample count). Every
    other attribute (``stops_at``, ``open_seconds``, ``device``) is the wrapped source's."""

    def __init__(
        self,
        source: Any,
        view: Any,
        *,
        fps: float = UI_FPS,
        cancel: threading.Event | None = None,
        tick: Callable[[], None] | None = None,
    ) -> None:
        self._source = source
        self._view = view
        self._interval = 1.0 / fps if fps > 0 else 0.0
        self._cancel = cancel
        self._tick = tick
        self._shown_at: float | None = None
        self.read_count = 0
        self.shown_count = 0

    def open(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise Cancelled()
        self._source.open()

    def read(self) -> Any:
        if self._cancel is not None and self._cancel.is_set():
            raise Cancelled()
        frame = self._source.read()
        if frame is None:
            return None
        self.read_count += 1
        at = getattr(frame, "at", None)
        at = at if isinstance(at, int | float) and not isinstance(at, bool) else time.monotonic()
        if self._shown_at is None or at - self._shown_at >= self._interval:
            self._shown_at = at
            self.shown_count += 1
            self._view.frame(frame.image)
        if self._tick is not None:
            self._tick()
        return frame

    def close(self) -> None:
        self._source.close()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._source, name)


# -- the model -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    """What the window draws now."""

    mode: str
    """``cover`` (the full-screen window) or ``compact`` (the small Touch ID panel at the top:
    it never covers the macOS prompt)."""
    phase: str
    """``running``, ``passed`` or ``failed``."""
    step: str
    glyph: str | None
    """``look`` (hollow, toward the camera), ``left``, ``right``, ``up``, ``down``, ``touch``,
    ``check``, ``cross`` or ``None`` (starting)."""
    double: bool
    """``turn_more``: two triangles."""
    headline: str
    hint: str
    purpose: str
    detail: str
    """The samples line of an enrollment, the Touch ID line, or the failure's reason."""
    samples: tuple[int, int] | None
    countdown: float | None
    """1.0 at the step's start → 0.0 at its deadline; ``None`` without a deadline."""
    since_step: float
    since_result: float | None
    cancel: str
    privacy: str


GLYPHS = {
    "look": "look",
    "center": "look",
    "turn_left": "left",
    "turn_right": "right",
    "look_up": "up",
    "look_down": "down",
    "touch_id": "touch",
}


def fill(template: str, **values: object) -> str:
    """``{name}`` placeholders replaced by ``values`` (no ``str.format``: a text may hold other
    braces)."""
    for name, value in values.items():
        template = template.replace("{" + name + "}", str(value))
    return template


def _sentence(text: str, language: str) -> str:
    """The first letter in upper case (in Turkish, ``i`` becomes the dotted capital U+0130)."""
    if not text:
        return text
    first = text[0]
    upper = "\u0130" if (first == "i" and language == "tr") else first.upper()
    return upper + text[1:]


class WindowModel:
    """The window's state: fed by the view's calls, read as a :class:`Scene`. Pure; the clock
    is injectable (monotonic seconds, the same clock as the check's deadlines)."""

    def __init__(self, intro: Intro, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.close_at: float | None = None
        self.start(intro)

    def start(self, intro: Intro) -> None:
        self.intro = intro
        self.step_name = "touch_id" if intro.op == "touch_id" else "starting"
        self.deadline: float | None = None
        self.step_at = self.clock()
        self.total: float | None = None
        self.hint_key: str | None = None
        self.count: tuple[int, int] | None = None
        self.ok: bool | None = None
        self.reason: str | None = None
        self.result_at: float | None = None
        self.last_turn: str | None = None
        self.close_at = None

    def text(self, key: str) -> str:
        return self.intro.texts.get(key, "")

    def step(self, step: str, deadline: float | None) -> None:
        if step == "done" or self.ok is not None:
            return
        now = self.clock()
        if step != self.step_name or deadline != self.deadline:
            self.step_at = now
            self.total = (deadline - now) if deadline is not None else None
        if step in ("turn_left", "turn_right"):
            self.last_turn = step
        self.step_name = step
        self.deadline = deadline

    def hint(self, hint: str | None) -> None:
        if self.ok is None:
            self.hint_key = hint

    def samples(self, count: int, needed: int) -> None:
        self.count = (max(0, int(count)), max(1, int(needed)))

    def result(self, ok: bool, reason: str | None) -> None:
        self.ok = bool(ok)
        self.reason = reason
        self.result_at = self.clock()
        self.hint_key = None

    def close(self, delay: float = 0.0) -> None:
        at = self.clock() + max(0.0, delay)
        self.close_at = at if self.close_at is None else min(self.close_at, at)

    def closed(self) -> bool:
        return self.close_at is not None and self.clock() >= self.close_at

    def _glyph(self) -> tuple[str | None, bool]:
        if self.ok is True:
            return "check", False
        if self.ok is False:
            return "cross", False
        if self.step_name == "turn_more":
            return ("left" if self.last_turn == "turn_left" else "right"), True
        return GLYPHS.get(self.step_name), False

    def _reason_text(self) -> str:
        reason = self.reason or "error"
        if self.intro.purpose == "enroll" and reason in ENROLL_REASON_KEYS:
            text = self.text(f"guard.cli.enroll.reason.{reason}")
            if text:
                return _sentence(text, self.intro.language)
        return self.text(f"guard.verdict.{reason}") or self.text("guard.verdict.error")

    def scene(self) -> Scene:
        now = self.clock()
        purpose = self.intro.purpose
        compact = self.step_name == "touch_id" or self.intro.op == "touch_id"
        glyph, double = self._glyph()
        countdown = None
        if self.ok is None and self.deadline is not None and self.total and self.total > 0:
            countdown = min(1.0, max(0.0, (self.deadline - now) / self.total))
        if self.ok is None:
            phase = "running"
            headline = self.text(f"guard.window.step.{self.step_name}")
            hint = self.text(f"guard.window.hint.{self.hint_key}") if self.hint_key else ""
            detail = ""
            if compact:
                detail = self.text("guard.window.touch_id")
            elif purpose == "enroll" and self.count is not None:
                detail = fill(
                    self.text("guard.window.samples"), count=min(self.count), needed=self.count[1]
                )
        else:
            phase = "passed" if self.ok else "failed"
            hint = ""
            if self.ok:
                headline = self.text(f"guard.window.result.{purpose}")
                detail = ""
            else:
                key = "enroll_failed" if purpose == "enroll" else "failed"
                headline = self.text(f"guard.window.result.{key}")
                detail = self._reason_text()
        purpose_line = fill(
            self.text(f"guard.window.purpose.{purpose}"), tool=self.intro.tool or "-"
        )
        return Scene(
            mode="compact" if compact else "cover",
            phase=phase,
            step=self.step_name,
            glyph=glyph,
            double=double,
            headline=headline,
            hint=hint,
            purpose=purpose_line,
            detail=detail,
            samples=self.count if purpose == "enroll" else None,
            countdown=countdown,
            since_step=max(0.0, now - self.step_at),
            since_result=None if self.result_at is None else max(0.0, now - self.result_at),
            cancel=self.text("guard.window.cancel"),
            privacy=self.text("guard.window.privacy"),
        )


# -- layout ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """Where the parts go, in points with the origin at the top left (y grows downward)."""

    width: float
    height: float
    cx: float
    cy: float
    radius: float
    """The camera circle."""
    ring: float
    """The neon τ ring (just outside the picture)."""
    comet: float
    """The countdown comet."""
    dial: float
    """The instrument ticks."""
    outer: float
    """The outer Signal ring; nothing but the triangles lies between it and the text."""
    tri: float
    """A direction triangle's height."""
    left: tuple[float, float]
    right: tuple[float, float]
    up: tuple[float, float]
    down: tuple[float, float]
    header_y: float
    headline_y: float
    hint_y: float
    detail_y: float
    footer_y: float
    headline_size: float
    hint_size: float
    small_size: float
    hud: tuple[float, float, float, float]
    """The rectangle redrawn every frame (x, y, w, h); the rest changes only with the phase."""
    chip: tuple[float, float, float, float]
    """The Esc chip, which also cancels on a click."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cover_layout(width: float, height: float) -> Layout:
    """The full-screen layout for a screen of ``width`` x ``height`` points."""
    short = min(width, height)
    headline_size = _clamp(short * 0.044, 24.0, 56.0)
    hint_size = _clamp(short * 0.02, 13.0, 22.0)
    small_size = _clamp(short * 0.014, 11.0, 15.0)
    header = 30 + small_size * 3.2
    below = headline_size * 1.5 + hint_size * 2.2 + small_size * 2.6 + 70
    radius = _clamp(short * 0.21, 90.0, 300.0)
    while True:
        outer = radius * 1.3
        tri = _clamp(radius * 0.36, 30.0, 96.0)
        above = header + tri * 1.5
        fits_v = above + 2 * outer + below <= height
        fits_h = 2 * (outer + tri * 1.9) <= width
        if (fits_v and fits_h) or radius <= 60:
            break
        radius *= 0.94
    outer = radius * 1.3
    tri = _clamp(radius * 0.36, 30.0, 96.0)
    above = header + tri * 1.5
    spare = max(0.0, height - above - 2 * outer - below)
    cy = above + outer + spare * 0.42
    cx = width / 2
    side = outer + tri * 0.95
    headline_y = cy + outer + headline_size * 0.55
    hint_y = headline_y + headline_size * 1.25
    detail_y = hint_y + hint_size * 1.9
    footer_y = height - 34 - small_size
    hud_top = cy - outer - tri * 1.45
    hud_bottom = detail_y + small_size * 3.0
    hud_half = outer + tri * 1.8
    chip_w = small_size * 12.5
    chip_h = small_size * 2.4
    return Layout(
        width=width,
        height=height,
        cx=cx,
        cy=cy,
        radius=radius,
        ring=radius + max(6.0, radius * 0.04),
        comet=radius + max(15.0, radius * 0.1),
        dial=radius + max(24.0, radius * 0.16),
        outer=outer,
        tri=tri,
        left=(cx - side, cy),
        right=(cx + side, cy),
        up=(cx, cy - outer - tri * 0.62),
        down=(cx, cy + outer + tri * 0.62),
        header_y=30.0,
        headline_y=headline_y,
        hint_y=hint_y,
        detail_y=detail_y,
        footer_y=footer_y,
        headline_size=headline_size,
        hint_size=hint_size,
        small_size=small_size,
        hud=(cx - hud_half, hud_top, 2 * hud_half, hud_bottom - hud_top),
        chip=(cx - chip_w / 2, footer_y - chip_h * 0.3, chip_w, chip_h),
    )


COMPACT_SIZE = (560.0, 132.0)
"""The Touch ID panel, in points."""


def compact_layout(width: float = COMPACT_SIZE[0], height: float = COMPACT_SIZE[1]) -> Layout:
    """The Touch ID panel: a glyph on the left, three lines on the right."""
    radius = height * 0.26
    cx = 24 + radius * 1.3
    cy = height / 2
    return Layout(
        width=width,
        height=height,
        cx=cx,
        cy=cy,
        radius=radius,
        ring=radius * 1.12,
        comet=radius * 1.3,
        dial=radius * 1.45,
        outer=radius * 1.5,
        tri=radius * 0.6,
        left=(cx, cy),
        right=(cx, cy),
        up=(cx, cy),
        down=(cx, cy),
        header_y=22.0,
        headline_y=height * 0.36,
        hint_y=height * 0.62,
        detail_y=height * 0.62,
        footer_y=height * 0.8,
        headline_size=22.0,
        hint_size=12.0,
        small_size=11.0,
        hud=(0.0, 0.0, width, height),
        chip=(width - 120.0, height - 30.0, 104.0, 20.0),
    )


# -- the demo --------------------------------------------------------------------------------

DemoEvent = tuple[float, str, tuple[Any, ...]]


def demo_events(texts: Mapping[str, str], language: str = "en") -> list[DemoEvent]:
    """``tau guard window --demo``: ``(seconds from the start, view method, arguments)``. A
    deadline argument is seconds after the event (the player turns it into monotonic time).
    An unlock that passes, a step-up that fails, then an enrollment behind Touch ID."""

    def intro(op: str, purpose: str, tool: str | None = None) -> Intro:
        return Intro(op=op, purpose=purpose, texts=texts, language=language, tool=tool)

    events: list[DemoEvent] = [
        (0.0, "start", (intro("verify", "unlock"),)),
        (0.0, "step", ("starting", None)),
        (1.3, "step", ("look", 12.0)),
        (2.3, "hint", ("too_dark",)),
        (3.6, "hint", (None,)),
        (4.4, "step", ("turn_left", 3.5)),
        (6.1, "step", ("center", 3.5)),
        (6.9, "step", ("turn_right", 3.5)),
        (8.6, "step", ("center", 3.5)),
        (9.5, "result", (True, "match")),
        (11.4, "start", (intro("verify", "step_up", "robot.move"),)),
        (11.4, "step", ("starting", None)),
        (12.2, "step", ("look", 12.0)),
        (13.6, "step", ("turn_right", 3.5)),
        (14.4, "hint", ("multiple_faces",)),
        (15.2, "result", (False, "multiple_faces")),
        (17.2, "start", (intro("enroll", "enroll"),)),
        (17.2, "step", ("touch_id", None)),
        (19.6, "step", ("starting", None)),
        (20.4, "step", ("look", 5.0)),
    ]
    count = 0
    for at in (20.9, 21.3, 21.8, 22.3):
        count += 1
        events.append((at, "samples", (count, 10)))
    events += [
        (22.8, "step", ("turn_left", 3.0)),
        (23.6, "samples", (5, 10)),
        (24.2, "step", ("turn_more", 1.6)),
        (25.2, "step", ("turn_right", 3.0)),
        (25.8, "samples", (6, 10)),
        (26.3, "samples", (7, 10)),
        (26.8, "step", ("look_up", 3.0)),
        (27.3, "samples", (8, 10)),
        (27.8, "samples", (9, 10)),
        (28.6, "step", ("look_down", 3.0)),
        (29.1, "samples", (10, 10)),
        (29.6, "samples", (11, 10)),
        (30.4, "result", (True, "match")),
        (30.4, "close", (RESULT_SECONDS,)),
    ]
    return events


def demo_offset(step: str, since: float) -> tuple[float, float]:
    """Where the synthetic head is (x, y in pixels from the centre) during ``step``."""
    ease = min(1.0, since / 0.6)
    if step == "turn_left":
        return (-70.0 * ease, 0.0)  # the owner's left is the picture's left: it is mirrored later
    if step == "turn_right":
        return (70.0 * ease, 0.0)
    if step == "turn_more":
        return (-95.0 * ease, 0.0)
    if step == "look_up":
        return (0.0, -40.0 * ease)
    if step == "look_down":
        return (0.0, 40.0 * ease)
    return (6.0 * math.sin(since * 1.7), 3.0 * math.sin(since * 1.1))


_GRID: dict[tuple[int, int], Any] = {}


def synthetic_frame(
    offset: tuple[float, float] = (0.0, 0.0),
    *,
    size: tuple[int, int] = (640, 480),
    dark: float = 1.0,
) -> Any:
    """A dark BGR picture with a faint head-shaped glow at ``offset``: the demo's camera. No
    face, no person, nothing from a camera. The picture is drawn un-mirrored, like a camera
    frame (the window mirrors it)."""
    import numpy as np

    width, height = size
    grid = _GRID.get(size)
    if grid is None:
        ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
        grid = _GRID[size] = (xs, ys)
    xs, ys = grid
    cx = width / 2 - offset[0]  # a camera frame: the owner's left turn moves right in it
    cy = height * 0.52 + offset[1]
    head = ((xs - cx) / (width * 0.16)) ** 2 + ((ys - cy) / (height * 0.3)) ** 2
    shoulders = ((xs - width / 2) / (width * 0.42)) ** 2 + (
        (ys - height * 1.08) / (height * 0.3)
    ) ** 2
    glow = np.clip(1.25 - head, 0, 1) ** 1.6 + 0.55 * np.clip(1.1 - shoulders, 0, 1)
    vignette = (
        1.0 - 0.55 * (((xs - width / 2) / width) ** 2 + ((ys - height / 2) / height) ** 2) * 2.2
    )
    base = (np.clip(vignette, 0, 1) * 26 + glow * 64) * dark
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[..., 0] = np.clip(base * 1.05 + 10, 0, 255)
    frame[..., 1] = np.clip(base * 0.92 + 6, 0, 255)
    frame[..., 2] = np.clip(base * 0.98 + 8, 0, 255)
    return frame
