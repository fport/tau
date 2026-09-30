"""The guard window on macOS (issue 126): AppKit through pyobjc, imported lazily.

:class:`MacOverlayView` is the :class:`~tau_guard.window.GuardView` the worker opens for an
attempt. It runs in the worker process, so the frames never leave it:

- **The window.** An ``NSApplication`` with the Accessory activation policy (no Dock icon) and
  one borderless window over the main screen below the menu bar (macOS's camera indicator stays
  visible), at the status window level (above normal windows and the Dock), on every Space and
  over full-screen apps, dark Void at 90 % over the desktop. It asks macOS to keep it out of
  screen capture (``NSWindowSharingNone``). It activates, so Esc reaches it; if macOS keeps
  another app active, a click on the Esc chip cancels too.
- **The Touch ID step** (the ``touch_id`` op, an enrollment's LocalAuthentication, the Touch ID
  half of a ``face_or_touch_id`` step-up) shrinks the window to a small panel at the top of the
  screen at the floating level and deactivates the app, so the macOS prompt shows on its own
  and nothing covers it.
- **Threads.** The worker's main thread runs :meth:`MacOverlayView.run`: a manual AppKit event
  loop (``nextEventMatchingMask``, like pyglet) that redraws at :data:`FPS` and returns to
  Python between events, so the worker's SIGTERM handler runs within a frame. The check runs in
  another thread and only calls the cheap setters (``step``, ``frame``, ...), which store under
  a lock. A new frame is converted on the main thread (BGR → BGRA → ``CGImage``, at most
  :data:`MAX_PICTURE_WIDTH` pixels wide) only when it is drawn.
- **The look** (docs/brand): Void background with a faint grid, the mirrored picture clipped
  to a circle inside a thin neon τ ring (Signal → Ember, Core line), instrument ticks, the
  countdown as a comet arc with a Core head (the brand's thinking motion), the step as a neon
  triangle (hollow for "look", toward the camera), a bold uppercase monospaced line, the hint
  in Flare, the τ guard wordmark and the purpose, a segmented bar for enrollment samples, an
  Ember ring fill with a check or a Signal flash with a cross and the reason. No emoji, sharp
  corners. macOS "Reduce motion" stops the comet's circling, the ticks, the scan line, the
  pulses and the flash.

:func:`open_view` checks what can stop the window first (:func:`tau_guard.window.headless_reason`,
then a GUI session and AppKit, :func:`gui_reason`) and answers ``(None, reason)`` so the worker
runs headless and logs why. :func:`render_png` paints a :class:`~tau_guard.window.Scene`
offscreen (no window, no event loop), and ``python -m tau_guard.overlay demo`` plays
``tau guard window --demo`` (the request JSON on stdin; with ``snapshot`` it writes PNGs and
opens nothing); ``python -m tau_guard.overlay probe`` answers whether a window could open.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tau_guard.window import (
    COMPACT_SIZE,
    Intro,
    Layout,
    Scene,
    WindowModel,
    compact_layout,
    cover_layout,
    demo_events,
    demo_offset,
    headless_reason,
    synthetic_frame,
)

__all__ = [
    "FPS",
    "MAX_PICTURE_WIDTH",
    "MacOverlayView",
    "gui_reason",
    "main",
    "open_view",
    "render_png",
]

FPS = 30.0
MAX_PICTURE_WIDTH = 720
BACKGROUND_ALPHA = 0.9
FLASH_SECONDS = 0.45
FILL_SECONDS = 0.35


def _hex(value: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    value = value.lstrip("#")
    return (int(value[0:2], 16) / 255, int(value[2:4], 16) / 255, int(value[4:6], 16) / 255, alpha)


VOID = _hex("#05071A")
BG2 = _hex("#0A0D24")
LINE = _hex("#1B2042")
LINE2 = _hex("#2D335C")
SIGNAL = _hex("#FF2E63")
EMBER = _hex("#FF7A3D")
FLARE = _hex("#FFB25C")
CORE = _hex("#FFF4E0")
MUTED = _hex("#979BB9")


def _alpha(
    color: tuple[float, float, float, float], alpha: float
) -> tuple[float, float, float, float]:
    return (color[0], color[1], color[2], color[3] * alpha)


def _mix(a: tuple[float, ...], b: tuple[float, ...], u: float) -> tuple[float, float, float, float]:
    u = max(0.0, min(1.0, u))
    return tuple(x + (y - x) * u for x, y in zip(a, b, strict=True))  # type: ignore[return-value]


# -- what can stop the window ----------------------------------------------------------------


def gui_reason() -> str | None:
    """``no_gui_session`` (no window server: a hub started over SSH, a launchd job outside the
    login session), ``pyobjc_missing`` (AppKit or Quartz cannot be imported) or ``None``."""
    try:
        import Quartz  # type: ignore[import-not-found]
    except Exception:
        return "pyobjc_missing"
    try:
        if Quartz.CGSessionCopyCurrentDictionary() is None:
            return "no_gui_session"
    except Exception:
        return "no_gui_session"
    try:
        import AppKit  # type: ignore[import-not-found]  # noqa: F401
    except Exception:
        return "pyobjc_missing"
    return None


def open_view(
    intro: Intro,
    *,
    on_cancel: Callable[[], None] | None = None,
) -> tuple[MacOverlayView | None, str | None]:
    """The window for ``intro``, prepared on this (the main) thread, or ``(None, reason)``."""
    reason = headless_reason() or gui_reason()
    if reason is not None:
        return None, reason
    try:
        view = MacOverlayView(intro, on_cancel=on_cancel)
        view.prepare()
    except Exception as exc:
        return None, f"error ({type(exc).__name__})"
    return view, None


# -- AppKit classes (defined once, on first use) ---------------------------------------------

_CLASSES: tuple[Any, Any] | None = None


def _classes() -> tuple[Any, Any]:
    global _CLASSES
    if _CLASSES is not None:
        return _CLASSES
    import AppKit  # type: ignore[import-not-found]

    class TauGuardWindow(AppKit.NSWindow):  # type: ignore[misc]
        def canBecomeKeyWindow(self) -> bool:  # noqa: N802 (AppKit)
            return True

        def canBecomeMainWindow(self) -> bool:  # noqa: N802
            return True

    class TauGuardCanvas(AppKit.NSView):  # type: ignore[misc]
        def isFlipped(self) -> bool:  # noqa: N802
            return True

        def isOpaque(self) -> bool:  # noqa: N802
            return False

        def acceptsFirstResponder(self) -> bool:  # noqa: N802
            return True

        def acceptsFirstMouse_(self, event: Any) -> bool:  # noqa: N802
            return True

        def keyDown_(self, event: Any) -> None:  # noqa: N802
            if event.keyCode() == 53:  # Esc; every other key is swallowed (no beep)
                self.owner.request_cancel()

        def cancelOperation_(self, sender: Any) -> None:  # noqa: N802
            self.owner.request_cancel()

        def mouseDown_(self, event: Any) -> None:  # noqa: N802
            point = self.convertPoint_fromView_(event.locationInWindow(), None)
            self.owner.clicked(self.role, point.x, point.y)

        def drawRect_(self, rect: Any) -> None:  # noqa: N802
            self.owner.draw(self.role)

    _CLASSES = (TauGuardWindow, TauGuardCanvas)
    return _CLASSES


# -- the view --------------------------------------------------------------------------------


class MacOverlayView:
    """The guard window (see the module docstring). The setters are called from the check's
    thread; :meth:`prepare` and :meth:`run` from the main thread."""

    def __init__(
        self,
        intro: Intro,
        *,
        on_cancel: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = threading.Lock()
        self.clock = clock
        self.model = WindowModel(intro, clock=clock)
        self._on_cancel = on_cancel
        self._image: Any = None
        self._image_seq = 0
        self._drawn_seq = -1
        self._picture: Any = None
        self._scene: Scene | None = None
        self._layout: Layout | None = None
        self._mode: str | None = None
        self._backdrop_key: tuple[Any, ...] | None = None
        self._cancelled = False
        self._broken: set[str] = set()
        self.motion = True
        self._app: Any = None
        self._window: Any = None
        self._canvas: Any = None
        self._hud: Any = None
        self._screen: Any = None

    # -- GuardView (the check's thread) -------------------------------------------------------

    def start(self, intro: Intro) -> None:
        with self._lock:
            self.model.start(intro)
            self._image = None
            self._image_seq += 1

    def step(self, step: str, deadline: float | None) -> None:
        with self._lock:
            self.model.step(step, deadline)

    def hint(self, hint: str | None) -> None:
        with self._lock:
            self.model.hint(hint)

    def frame(self, image: Any) -> None:
        with self._lock:
            self._image = image
            self._image_seq += 1

    def samples(self, count: int, needed: int) -> None:
        with self._lock:
            self.model.samples(count, needed)

    def result(self, ok: bool, reason: str | None) -> None:
        with self._lock:
            self.model.result(ok, reason)

    def close(self, delay: float = 0.0) -> None:
        with self._lock:
            self.model.close(delay)

    # -- the main thread ----------------------------------------------------------------------

    def request_cancel(self) -> None:
        """Esc or a click on the chip: close now and tell the worker (once)."""
        with self._lock:
            if self._cancelled or self.model.ok is not None:
                return
            self._cancelled = True
            self.model.close(0.0)
        if self._on_cancel is not None:
            self._on_cancel()

    def clicked(self, role: str, x: float, y: float) -> None:
        layout = self._layout
        if layout is None or self._mode != "cover":
            return
        if role == "hud":  # the HUD view's own coordinates
            x, y = x + layout.hud[0], y + layout.hud[1]
        cx, cy, cw, ch = layout.chip
        if cx <= x <= cx + cw and cy - 6 <= y <= cy + ch + 6:
            self.request_cancel()

    def prepare(self) -> None:
        """The application and the (hidden) window; raises when AppKit refuses."""
        import AppKit  # type: ignore[import-not-found]

        window_class, canvas_class = _classes()
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        app.finishLaunching()
        self._app = app
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            self.motion = not bool(workspace.accessibilityDisplayShouldReduceMotion())
        except Exception:
            self.motion = True
        self._screen = AppKit.NSScreen.mainScreen() or AppKit.NSScreen.screens()[0]
        rect = self._cover_rect()
        window = window_class.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False
        )
        window.setOpaque_(False)
        window.setHasShadow_(False)
        window.setReleasedWhenClosed_(False)
        window.setIgnoresMouseEvents_(False)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        try:
            window.setSharingType_(AppKit.NSWindowSharingNone)
        except Exception:
            pass
        size = rect[1]
        canvas = canvas_class.alloc().initWithFrame_(((0.0, 0.0), size))
        canvas.owner = self
        canvas.role = "canvas"
        canvas.setWantsLayer_(True)
        hud = canvas_class.alloc().initWithFrame_(((0.0, 0.0), (1.0, 1.0)))
        hud.owner = self
        hud.role = "hud"
        hud.setWantsLayer_(True)
        canvas.addSubview_(hud)
        window.setContentView_(canvas)
        self._window, self._canvas, self._hud = window, canvas, hud

    def _cover_rect(self) -> tuple[tuple[float, float], tuple[float, float]]:
        frame = self._screen.frame()
        visible = self._screen.visibleFrame()
        top = frame.origin.y + frame.size.height
        menu = max(0.0, top - (visible.origin.y + visible.size.height))
        return (
            (frame.origin.x, frame.origin.y),
            (frame.size.width, frame.size.height - menu),
        )

    def _compact_rect(self) -> tuple[tuple[float, float], tuple[float, float]]:
        frame = self._screen.frame()
        visible = self._screen.visibleFrame()
        width, height = COMPACT_SIZE
        x = frame.origin.x + (frame.size.width - width) / 2
        y = visible.origin.y + visible.size.height - height - 14
        return ((x, y), (width, height))

    def _apply_mode(self, mode: str) -> None:
        import AppKit  # type: ignore[import-not-found]

        window, canvas, hud = self._window, self._canvas, self._hud
        if mode == "compact":
            rect = self._compact_rect()
            window.setLevel_(AppKit.NSFloatingWindowLevel)
            window.setBackgroundColor_(AppKit.NSColor.clearColor())
        else:
            rect = self._cover_rect()
            window.setLevel_(AppKit.NSStatusWindowLevel)
            window.setBackgroundColor_(
                AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
                    VOID[0], VOID[1], VOID[2], BACKGROUND_ALPHA
                )
            )
        window.setFrame_display_(rect, False)
        width, height = rect[1]
        canvas.setFrame_(((0.0, 0.0), (width, height)))
        if mode == "compact":
            self._layout = compact_layout(width, height)
            hud.setHidden_(True)
            self._app.deactivate()  # the macOS prompt shows on its own, nothing covers it
            window.orderFrontRegardless()
        else:
            self._layout = cover_layout(width, height)
            x, y, w, h = self._layout.hud
            hud.setFrame_(((x, y), (w, h)))
            hud.setHidden_(False)
            window.makeKeyAndOrderFront_(None)
            window.orderFrontRegardless()
            _activate(self._app)
            window.makeFirstResponder_(canvas)
        self._mode = mode
        self._backdrop_key = None
        canvas.setNeedsDisplay_(True)

    def run(self) -> None:
        """Show the window and run its loop until it closed (the result's delay, Esc,
        :meth:`close`)."""
        import AppKit  # type: ignore[import-not-found]
        import Foundation  # type: ignore[import-not-found]
        import objc  # type: ignore[import-not-found]

        if self._window is None:
            self.prepare()
        app = self._app
        mode_key = Foundation.NSDefaultRunLoopMode
        frame_time = 1.0 / FPS
        try:
            while True:
                with objc.autorelease_pool():
                    began = time.monotonic()
                    with self._lock:
                        if self.model.closed():
                            break
                        scene = self.model.scene()
                        image, seq = self._image, self._image_seq
                    self._update(scene, image, seq)
                    wait = max(0.001, frame_time - (time.monotonic() - began))
                    until = Foundation.NSDate.dateWithTimeIntervalSinceNow_(wait)
                    event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                        AppKit.NSEventMaskAny, until, mode_key, True
                    )
                    while event is not None:
                        app.sendEvent_(event)
                        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                            AppKit.NSEventMaskAny, Foundation.NSDate.distantPast(), mode_key, True
                        )
                    app.updateWindows()
        finally:
            self._teardown()

    def _update(self, scene: Scene, image: Any, seq: int) -> None:
        if scene.mode != self._mode:
            self._apply_mode(scene.mode)
        if seq != self._drawn_seq:
            self._drawn_seq = seq
            self._picture = picture(image) if image is not None else None
        self._scene = scene
        layout = self._layout
        assert layout is not None
        flashing = (
            scene.phase == "failed"
            and self.motion
            and scene.since_result is not None
            and scene.since_result < FLASH_SECONDS + 0.1
        )
        key = (scene.mode, scene.phase, scene.purpose, scene.cancel, flashing)
        if key != self._backdrop_key or flashing or scene.mode == "compact":
            self._backdrop_key = None if flashing else key
            self._canvas.setNeedsDisplay_(True)
        if scene.mode == "cover":
            self._hud.setNeedsDisplay_(True)
        self._window.displayIfNeeded()

    def draw(self, role: str) -> None:
        """``drawRect_`` of a canvas: paint the current scene. An exception never reaches
        AppKit: it is logged once (``worker.log``) and that canvas stays as it was."""
        import AppKit  # type: ignore[import-not-found]
        import Quartz  # type: ignore[import-not-found]

        scene, layout = self._scene, self._layout
        if scene is None or layout is None or role in self._broken:
            return
        try:
            ctx = AppKit.NSGraphicsContext.currentContext().CGContext()
            now = time.monotonic()
            if role == "hud":
                Quartz.CGContextTranslateCTM(ctx, -layout.hud[0], -layout.hud[1])
                paint_hud(ctx, layout, scene, self._picture, now, self.motion)
            elif scene.mode == "compact":
                paint_compact(ctx, layout, scene, now, self.motion)
            else:
                paint_backdrop(ctx, layout, scene, now, self.motion)
        except Exception as exc:
            self._broken.add(role)
            print(
                f"tau-guard worker: window: painting failed ({type(exc).__name__})",
                file=sys.stderr,
                flush=True,
            )

    def _teardown(self) -> None:
        window = self._window
        if window is not None:
            try:
                window.orderOut_(None)
                window.close()
            except Exception:
                pass
        with self._lock:
            self._image = None
        self._picture = None


def _activate(app: Any) -> None:
    """Bring the window's app to the front, so Esc reaches it. macOS may refuse to take focus
    from the app in front (cooperative activation); the window still covers the screen and a
    click on the Esc chip cancels."""
    try:
        app.activateIgnoringOtherApps_(True)
    except Exception:
        try:
            app.activate()
        except Exception:
            pass


# -- the picture -----------------------------------------------------------------------------

_SPACE: list[Any] = []


def _rgb_space() -> Any:
    import Quartz  # type: ignore[import-not-found]

    if not _SPACE:
        try:
            _SPACE.append(Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB))
        except Exception:
            _SPACE.append(Quartz.CGColorSpaceCreateDeviceRGB())
    return _SPACE[0]


def picture(image: Any) -> Any:
    """A camera frame (BGR ``uint8``, ``H x W x 3``) as a ``CGImage``, at most
    :data:`MAX_PICTURE_WIDTH` pixels wide; ``None`` for anything else. Drawn mirrored."""
    import Foundation  # type: ignore[import-not-found]
    import numpy as np
    import Quartz  # type: ignore[import-not-found]

    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim not in (2, 3):
        return None
    if image.ndim == 3 and image.shape[2] != 3:
        return None
    height, width = image.shape[:2]
    if width < 2 or height < 2:
        return None
    if width > MAX_PICTURE_WIDTH:
        stride = math.ceil(width / MAX_PICTURE_WIDTH)
        image = image[::stride, ::stride]
    if image.ndim == 2:
        image = np.repeat(image[:, :, None], 3, axis=2)
    try:
        import cv2  # type: ignore[import-not-found]

        bgra = cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_BGR2BGRA)
    except Exception:
        alpha = np.full(image.shape[:2] + (1,), 255, dtype=np.uint8)
        bgra = np.concatenate((image, alpha), axis=2)
    bgra = np.ascontiguousarray(bgra)
    height, width = bgra.shape[:2]
    data = Foundation.NSData.dataWithBytes_length_(bgra.tobytes(), bgra.nbytes)
    provider = Quartz.CGDataProviderCreateWithCFData(data)
    return Quartz.CGImageCreate(
        width,
        height,
        8,
        32,
        width * 4,
        _rgb_space(),
        Quartz.kCGBitmapByteOrder32Little | Quartz.kCGImageAlphaNoneSkipFirst,
        provider,
        None,
        False,
        Quartz.kCGRenderingIntentDefault,
    )


# -- painting (Quartz on a y-down context; text through AppKit) ------------------------------


def _q() -> Any:
    import Quartz  # type: ignore[import-not-found]

    return Quartz


def _fill(ctx: Any, color: tuple[float, ...]) -> None:
    _q().CGContextSetRGBFillColor(ctx, *color)


def _stroke(ctx: Any, color: tuple[float, ...], width: float) -> None:
    q = _q()
    q.CGContextSetRGBStrokeColor(ctx, *color)
    q.CGContextSetLineWidth(ctx, width)


def _glow(ctx: Any, color: tuple[float, ...], blur: float) -> None:
    q = _q()
    q.CGContextSetShadowWithColor(ctx, q.CGSizeMake(0, 0), blur, q.CGColorCreateGenericRGB(*color))


@contextmanager
def _saved(ctx: Any) -> Iterator[None]:
    """Save the graphics state and restore it afterwards."""
    q = _q()
    q.CGContextSaveGState(ctx)
    try:
        yield
    finally:
        q.CGContextRestoreGState(ctx)


@contextmanager
def _glowing(ctx: Any, color: tuple[float, ...], blur: float) -> Iterator[None]:
    """Draw with a neon bloom: everything inside goes into one transparency layer, so the glow
    is applied once to the whole shape instead of to each piece."""
    q = _q()
    q.CGContextSaveGState(ctx)
    _glow(ctx, color, blur)
    q.CGContextBeginTransparencyLayer(ctx, None)
    try:
        yield
    finally:
        q.CGContextEndTransparencyLayer(ctx)
        q.CGContextRestoreGState(ctx)


def _polyline(ctx: Any, points: list[tuple[float, float]], *, close: bool = False) -> None:
    q = _q()
    q.CGContextBeginPath(ctx)
    q.CGContextMoveToPoint(ctx, *points[0])
    for point in points[1:]:
        q.CGContextAddLineToPoint(ctx, *point)
    if close:
        q.CGContextClosePath(ctx)


def _circle(ctx: Any, cx: float, cy: float, r: float) -> None:
    q = _q()
    q.CGContextBeginPath(ctx)
    q.CGContextAddEllipseInRect(ctx, q.CGRectMake(cx - r, cy - r, 2 * r, 2 * r))


def _arc(ctx: Any, cx: float, cy: float, r: float, a0: float, a1: float) -> None:
    """A path from ``a0`` to ``a1`` (radians, growing clockwise on the screen, 0 = right)."""
    q = _q()
    q.CGContextBeginPath(ctx)
    q.CGContextAddArc(ctx, cx, cy, r, a0, a1, 0)


def _font(size: float, weight: str, mono: bool) -> Any:
    import AppKit  # type: ignore[import-not-found]

    weights = {
        "regular": AppKit.NSFontWeightRegular,
        "medium": AppKit.NSFontWeightMedium,
        "semibold": AppKit.NSFontWeightSemibold,
        "bold": AppKit.NSFontWeightBold,
    }
    value = weights.get(weight, AppKit.NSFontWeightRegular)
    if mono:
        try:
            return AppKit.NSFont.monospacedSystemFontOfSize_weight_(size, value)
        except Exception:
            return AppKit.NSFont.fontWithName_size_("Menlo-Bold", size)
    return AppKit.NSFont.systemFontOfSize_weight_(size, value)


def _nscolor(color: tuple[float, ...]) -> Any:
    import AppKit  # type: ignore[import-not-found]

    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*color)


def _text(
    text: str,
    x: float,
    y: float,
    *,
    size: float,
    color: tuple[float, ...],
    weight: str = "bold",
    mono: bool = True,
    kern: float = 0.0,
    align: str = "center",
    glow: tuple[tuple[float, ...], float] | None = None,
    wrap: float | None = None,
) -> float:
    """Draw ``text`` with its vertical centre at ``y`` (or, with ``wrap``, its top); returns the
    drawn width (or height when wrapped)."""
    import AppKit  # type: ignore[import-not-found]

    if not text:
        return 0.0
    attrs: dict[Any, Any] = {
        AppKit.NSFontAttributeName: _font(size, weight, mono),
        AppKit.NSForegroundColorAttributeName: _nscolor(color),
        AppKit.NSKernAttributeName: kern,
    }
    if glow is not None:
        shadow = AppKit.NSShadow.alloc().init()
        shadow.setShadowColor_(_nscolor(glow[0]))
        shadow.setShadowBlurRadius_(glow[1])
        shadow.setShadowOffset_((0.0, 0.0))
        attrs[AppKit.NSShadowAttributeName] = shadow
    if wrap is not None:
        style = AppKit.NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(AppKit.NSTextAlignmentCenter)
        style.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        attrs[AppKit.NSParagraphStyleAttributeName] = style
        string = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        options = AppKit.NSStringDrawingUsesLineFragmentOrigin
        bounds = string.boundingRectWithSize_options_((wrap, 2000.0), options)
        height = math.ceil(bounds.size.height)
        string.drawWithRect_options_(((x - wrap / 2, y), (wrap, height)), options)
        return float(height)
    string = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
    extent = string.size()
    width = max(0.0, extent.width - kern)
    if align == "center":
        left = x - width / 2
    elif align == "right":
        left = x - width
    else:
        left = x
    string.drawAtPoint_((left, y - extent.height / 2))
    return width


def _ring_color(u: float) -> tuple[float, float, float, float]:
    return _mix(SIGNAL, EMBER, u)


def _bloom(
    ctx: Any,
    path: Callable[[], None],
    color: tuple[float, ...],
    width: float,
    glow: float,
    strength: float = 1.0,
) -> None:
    """A neon bloom without a blur: the path stroked three times, wide and faint to narrow and
    brighter (a shadow blur over a large transparency layer costs several milliseconds a
    frame; this costs a fraction of one)."""
    q = _q()
    for spread, alpha in ((1.6, 0.06), (0.9, 0.11), (0.4, 0.2)):
        _stroke(ctx, _alpha(color, alpha * strength), width + glow * spread)
        path()
        q.CGContextStrokePath(ctx)


def _neon_ring(
    ctx: Any,
    cx: float,
    cy: float,
    r: float,
    width: float,
    *,
    glow: float = 12.0,
    tint: tuple[float, ...] | None = None,
    strength: float = 1.0,
) -> None:
    """The brand ring: Signal at the top left to Ember at the bottom right, bloom, a Core line."""
    q = _q()
    segments = 48
    step = 2 * math.pi / segments

    def colour(index: int) -> tuple[float, float, float, float]:
        if tint is not None:
            return tint  # type: ignore[return-value]
        middle = (index + 0.5) * step
        u = 0.5 + 0.5 * (math.cos(middle) + math.sin(middle)) / math.sqrt(2)
        return _ring_color(u)

    _bloom(
        ctx,
        lambda: _circle(ctx, cx, cy, r),
        tint or _mix(SIGNAL, EMBER, 0.5),
        width,
        glow,
        strength,
    )
    q.CGContextSetLineCap(ctx, q.kCGLineCapButt)
    for index in range(segments):
        _stroke(ctx, colour(index), width)
        _arc(ctx, cx, cy, r, index * step - 0.004, (index + 1) * step + 0.004)
        q.CGContextStrokePath(ctx)
    _stroke(ctx, _alpha(CORE, 0.55), max(0.8, width * 0.34))
    _circle(ctx, cx, cy, r)
    q.CGContextStrokePath(ctx)


def _ticks(
    ctx: Any,
    cx: float,
    cy: float,
    r: float,
    count: int,
    length: float,
    width: float,
    color: tuple[float, ...],
    turn: float,
) -> None:
    q = _q()
    _stroke(ctx, color, width)
    q.CGContextBeginPath(ctx)
    for index in range(count):
        a = turn + 2 * math.pi * index / count
        q.CGContextMoveToPoint(ctx, cx + r * math.cos(a), cy + r * math.sin(a))
        q.CGContextAddLineToPoint(
            ctx, cx + (r + length) * math.cos(a), cy + (r + length) * math.sin(a)
        )
    q.CGContextStrokePath(ctx)


def _comet(
    ctx: Any,
    cx: float,
    cy: float,
    r: float,
    head: float,
    span: float,
    width: float,
    colors: tuple[tuple[float, ...], tuple[float, ...]],
    *,
    floor: float = 0.0,
) -> None:
    """A comet arc: the head at angle ``head`` (a Core dot), the tail ``span`` radians behind it
    (counter-clockwise), fading to ``floor`` (a countdown keeps its whole length visible)."""
    q = _q()
    pieces = max(6, int(span / 0.06))
    q.CGContextSetLineCap(ctx, q.kCGLineCapButt)
    for index in range(pieces):
        a1 = head - index * span / pieces
        a0 = head - (index + 1) * span / pieces
        fade = floor + (1 - floor) * (1 - index / pieces) ** 1.6
        color = colors[0] if index < pieces * 0.2 else colors[1]
        thick = max(1.0, width * (1 - 0.5 * index / pieces))
        for spread, alpha in ((3.6, 0.1), (2.0, 0.22), (1.0, 1.0)):
            _stroke(ctx, _alpha(color, fade * alpha), thick * spread)
            _arc(ctx, cx, cy, r, a0, a1 + 0.01)
            q.CGContextStrokePath(ctx)
    _fill(ctx, CORE)
    _circle(ctx, cx + r * math.cos(head), cy + r * math.sin(head), width * 1.2)
    q.CGContextFillPath(ctx)


def _triangle_points(
    cx: float, cy: float, size: float, direction: str
) -> list[tuple[float, float]]:
    h, half = size / 2, size * 0.6
    if direction == "right":
        return [(cx + h, cy), (cx - h, cy - half), (cx - h, cy + half)]
    if direction == "left":
        return [(cx - h, cy), (cx + h, cy - half), (cx + h, cy + half)]
    if direction == "up":
        return [(cx, cy - h), (cx + half, cy + h), (cx - half, cy + h)]
    return [(cx, cy + h), (cx - half, cy - h), (cx + half, cy - h)]


def _triangle(
    ctx: Any, cx: float, cy: float, size: float, direction: str, *, solid: bool, alpha: float = 1.0
) -> None:
    q = _q()
    points = _triangle_points(cx, cy, size, direction)
    q.CGContextSetLineJoin(ctx, q.kCGLineJoinMiter)
    with _saved(ctx):
        _glow(ctx, _alpha(SIGNAL if solid else EMBER, 0.9 * alpha), 18.0)
        if solid:
            _fill(ctx, _alpha(SIGNAL, 0.92 * alpha))
            _polyline(ctx, points, close=True)
            q.CGContextFillPath(ctx)
        _stroke(ctx, _alpha(EMBER if solid else FLARE, alpha), max(2.0, size * 0.05))
        _polyline(ctx, points, close=True)
        q.CGContextStrokePath(ctx)
    _stroke(ctx, _alpha(CORE, 0.75 * alpha), max(0.8, size * 0.018))
    _polyline(ctx, points, close=True)
    q.CGContextStrokePath(ctx)


def _mark(ctx: Any, cx: float, cy: float, r: float) -> None:
    """The τ mark from docs/brand/render.py (ring radius 100, ring 12, τ 14), flat (small)."""
    q = _q()
    s = r / 100.0
    for index in range(24):
        a0 = index * 2 * math.pi / 24
        middle = a0 + math.pi / 24
        u = 0.5 + 0.5 * (math.cos(middle) + math.sin(middle)) / math.sqrt(2)
        _stroke(ctx, _ring_color(u), 12 * s)
        _arc(ctx, cx, cy, r, a0 - 0.01, a0 + 2 * math.pi / 24 + 0.01)
        q.CGContextStrokePath(ctx)
    sx, ys, hr = cx - 7 * s, cy + 26 * s, 26 * s
    q.CGContextSetLineJoin(ctx, q.kCGLineJoinMiter)
    q.CGContextSetLineCap(ctx, q.kCGLineCapButt)
    for color, width in ((EMBER, 14 * s), (CORE, 14 * s * 0.42)):
        _stroke(ctx, color, width)
        q.CGContextBeginPath(ctx)
        q.CGContextMoveToPoint(ctx, cx - 54 * s, cy - 46 * s)
        q.CGContextAddLineToPoint(ctx, cx + 54 * s, cy - 46 * s)
        q.CGContextMoveToPoint(ctx, sx, cy - 46 * s)
        q.CGContextAddLineToPoint(ctx, sx, ys)
        q.CGContextAddArc(ctx, sx + hr, ys, hr, math.pi, math.pi / 2, 1)
        q.CGContextAddLineToPoint(ctx, sx + hr + 16 * s, ys + hr)
        q.CGContextStrokePath(ctx)


def _chamfer(ctx: Any, x: float, y: float, w: float, h: float, cut: float) -> None:
    """A rectangle with its top-left and bottom-right corners cut at 45 degrees (the brand)."""
    _polyline(
        ctx,
        [
            (x + cut, y),
            (x + w, y),
            (x + w, y + h - cut),
            (x + w - cut, y + h),
            (x, y + h),
            (x, y + cut),
        ],
        close=True,
    )


def _check(
    ctx: Any, cx: float, cy: float, k: float, color: tuple[float, ...], alpha: float = 1.0
) -> None:
    q = _q()
    points = [
        (cx - 0.42 * k, cy + 0.02 * k),
        (cx - 0.12 * k, cy + 0.32 * k),
        (cx + 0.46 * k, cy - 0.3 * k),
    ]
    q.CGContextSetLineJoin(ctx, q.kCGLineJoinMiter)
    q.CGContextSetLineCap(ctx, q.kCGLineCapSquare)
    with _saved(ctx):
        _glow(ctx, _alpha(color, 0.9 * alpha), 20.0)
        _stroke(ctx, _alpha(color, alpha), max(3.0, k * 0.11))
        _polyline(ctx, points)
        q.CGContextStrokePath(ctx)
    _stroke(ctx, _alpha(CORE, 0.85 * alpha), max(1.0, k * 0.035))
    _polyline(ctx, points)
    q.CGContextStrokePath(ctx)


def _cross(ctx: Any, cx: float, cy: float, k: float, alpha: float = 1.0) -> None:
    q = _q()
    d = 0.34 * k
    q.CGContextSetLineCap(ctx, q.kCGLineCapSquare)
    for color, width, blur in ((SIGNAL, max(3.0, k * 0.1), 20.0), (CORE, max(1.0, k * 0.03), 0.0)):
        with _saved(ctx):
            if blur:
                _glow(ctx, _alpha(SIGNAL, 0.9 * alpha), blur)
            _stroke(ctx, _alpha(color, alpha * (0.85 if color is CORE else 1.0)), width)
            q.CGContextBeginPath(ctx)
            q.CGContextMoveToPoint(ctx, cx - d, cy - d)
            q.CGContextAddLineToPoint(ctx, cx + d, cy + d)
            q.CGContextMoveToPoint(ctx, cx + d, cy - d)
            q.CGContextAddLineToPoint(ctx, cx - d, cy + d)
            q.CGContextStrokePath(ctx)


def _fingerprint(ctx: Any, cx: float, cy: float, r: float, color: tuple[float, ...]) -> None:
    """A Touch ID glyph: nested open arcs (no emoji, no rounded box)."""
    q = _q()
    q.CGContextSetLineCap(ctx, q.kCGLineCapButt)
    for index, frac in enumerate((0.22, 0.44, 0.66, 0.88)):
        _stroke(ctx, _alpha(color, 1.0 - index * 0.12), max(1.2, r * 0.07))
        start = math.radians(200 - index * 8)
        end = math.radians(340 + index * 8 + 180)
        _arc(ctx, cx, cy + r * 0.08, r * frac, start, end)
        q.CGContextStrokePath(ctx)


def _thinking_head(now: float, motion: bool) -> float:
    """The brand's thinking comet: one eased turn every 7 s (still at the top without motion)."""
    if not motion:
        return -math.pi / 2 + 0.6
    phase = (now % 7.0) / 7.0
    eased = phase - math.sin(2 * math.pi * phase) / (2 * math.pi) * 0.6
    return -math.pi / 2 + 2 * math.pi * eased


def paint_backdrop(ctx: Any, lay: Layout, scene: Scene, now: float, motion: bool) -> None:
    """What changes only with the phase: the grid, the stage light, the header, the footer,
    and the failure flash."""
    q = _q()
    w, h = lay.width, lay.height
    grid = max(40.0, lay.radius * 0.24)
    _stroke(ctx, _alpha(LINE, 0.5), 1.0)
    q.CGContextBeginPath(ctx)
    x = (w / 2) % grid
    while x < w:
        q.CGContextMoveToPoint(ctx, x, 0)
        q.CGContextAddLineToPoint(ctx, x, h)
        x += grid
    y = lay.cy % grid
    while y < h:
        q.CGContextMoveToPoint(ctx, 0, y)
        q.CGContextAddLineToPoint(ctx, w, y)
        y += grid
    q.CGContextStrokePath(ctx)
    # the stage: light behind the ring
    tint = SIGNAL if scene.phase == "failed" else EMBER
    components = [*_alpha(tint, 0.22), *_alpha(SIGNAL, 0.07), *_alpha(VOID, 0.0)]
    gradient = q.CGGradientCreateWithColorComponents(_rgb_space(), components, [0.0, 0.5, 1.0], 3)
    q.CGContextDrawRadialGradient(
        ctx, gradient, (lay.cx, lay.cy), 0, (lay.cx, lay.cy), lay.outer * 2.1, 0
    )
    # faint beams from the floor
    floor = lay.footer_y - lay.small_size * 2.2
    for index, (fx, height, alpha) in enumerate(
        ((0.08, 0.55, 0.10), (0.2, 0.35, 0.07), (0.8, 0.4, 0.07), (0.92, 0.6, 0.10))
    ):
        bx = w * fx
        beam = q.CGGradientCreateWithColorComponents(
            _rgb_space(),
            [
                *_alpha(SIGNAL if index % 2 else EMBER, 0.0),
                *_alpha(SIGNAL if index % 2 else EMBER, alpha),
            ],
            [0.0, 1.0],
            2,
        )
        with _saved(ctx):
            q.CGContextClipToRect(ctx, q.CGRectMake(bx - 1.5, floor - h * height, 3.0, h * height))
            q.CGContextDrawLinearGradient(ctx, beam, (bx, floor - h * height), (bx, floor), 0)
    line = q.CGGradientCreateWithColorComponents(
        _rgb_space(),
        [*_alpha(SIGNAL, 0.0), *_alpha(FLARE, 0.55), *_alpha(SIGNAL, 0.0)],
        [0.0, 0.5, 1.0],
        3,
    )
    with _saved(ctx):
        q.CGContextClipToRect(ctx, q.CGRectMake(0, floor - 0.75, w, 1.5))
        q.CGContextDrawLinearGradient(ctx, line, (0, floor), (w, floor), 0)
    # HUD corners
    inset, arm = 22.0, 26.0
    _stroke(ctx, _alpha(LINE2, 0.9), 1.5)
    for px, py, dx, dy in (
        (inset, inset, 1, 1),
        (w - inset, inset, -1, 1),
        (inset, h - inset, 1, -1),
        (w - inset, h - inset, -1, -1),
    ):
        _polyline(ctx, [(px, py + dy * arm), (px, py), (px + dx * arm, py)])
        q.CGContextStrokePath(ctx)
    # header: the mark and "guard", the purpose on the right
    size = lay.small_size
    mark_r = size * 0.95
    header = lay.header_y + mark_r + 4
    mx = inset + 22 + mark_r
    _mark(ctx, mx, header, mark_r)
    _text(
        "guard",
        mx + mark_r + 12,
        header,
        size=size * 1.3,
        color=CORE,
        weight="semibold",
        kern=1.5,
        align="left",
    )
    lit = SIGNAL if scene.phase != "passed" else FLARE
    right = w - inset - 22
    width = _text(
        scene.purpose,
        right,
        header,
        size=size,
        color=_alpha(CORE, 0.85),
        weight="semibold",
        kern=size * 0.22,
        align="right",
    )
    _fill(ctx, lit)
    q.CGContextFillRect(
        ctx, q.CGRectMake(right - width - size * 1.5, header - size * 0.3, size * 0.6, size * 0.6)
    )
    _stroke(ctx, _alpha(LINE, 0.9), 1.0)
    _polyline(ctx, [(inset + 22, header + mark_r + 12), (w - inset - 22, header + mark_r + 12)])
    q.CGContextStrokePath(ctx)
    _fill(ctx, _alpha(SIGNAL, 0.9))
    q.CGContextFillRect(
        ctx, q.CGRectMake(right - width, header + mark_r + 11, min(width, 120.0), 2.0)
    )
    # footer: the Esc chip, the privacy line
    if scene.phase == "running" and scene.cancel:
        cx, cy, cw, ch = lay.chip
        _fill(ctx, _alpha(BG2, 0.85))
        _chamfer(ctx, cx, cy, cw, ch, ch * 0.35)
        q.CGContextFillPath(ctx)
        _stroke(ctx, _alpha(LINE2, 1.0), 1.0)
        _chamfer(ctx, cx, cy, cw, ch, ch * 0.35)
        q.CGContextStrokePath(ctx)
        _text(
            scene.cancel,
            cx + cw / 2,
            cy + ch / 2,
            size=size,
            color=_alpha(CORE, 0.8),
            weight="semibold",
            kern=size * 0.2,
        )
    if scene.privacy:
        _text(
            scene.privacy,
            inset + 22,
            lay.footer_y + lay.chip[3] * 0.2,
            size=size * 0.9,
            color=_alpha(MUTED, 0.8),
            weight="medium",
            kern=size * 0.15,
            align="left",
        )
    # the failure flash
    if scene.phase == "failed" and motion and scene.since_result is not None:
        flash = max(0.0, 1.0 - scene.since_result / FLASH_SECONDS)
        if flash > 0:
            _fill(ctx, _alpha(SIGNAL, 0.2 * flash))
            q.CGContextFillRect(ctx, q.CGRectMake(0, 0, w, h))


def paint_hud(ctx: Any, lay: Layout, scene: Scene, image: Any, now: float, motion: bool) -> None:
    """The animated middle: the picture, the rings, the comet, the triangles and the lines."""
    q = _q()
    cx, cy, r = lay.cx, lay.cy, lay.radius
    result = scene.phase != "running"
    # the picture
    with _saved(ctx):
        _circle(ctx, cx, cy, r)
        q.CGContextClip(ctx)
        _fill(ctx, BG2)
        q.CGContextFillRect(ctx, q.CGRectMake(cx - r, cy - r, 2 * r, 2 * r))
        if image is not None:
            iw, ih = q.CGImageGetWidth(image), q.CGImageGetHeight(image)
            dh = 2 * r
            dw = iw * dh / ih
            if dw < 2 * r:
                dw, dh = 2 * r, ih * 2 * r / iw
            x0, y0 = cx - dw / 2, cy - dh / 2
            with _saved(ctx):
                q.CGContextTranslateCTM(ctx, x0 + dw, y0 + dh)
                q.CGContextScaleCTM(ctx, -1, -1)  # mirrored, and upright on the y-down context
                q.CGContextSetInterpolationQuality(ctx, q.kCGInterpolationMedium)
                q.CGContextDrawImage(ctx, q.CGRectMake(0, 0, dw, dh), image)
        # scan lines and the depth vignette
        _stroke(ctx, _alpha(VOID, 0.16), 1.0)
        q.CGContextBeginPath(ctx)
        y = cy - r
        while y < cy + r:
            q.CGContextMoveToPoint(ctx, cx - r, y)
            q.CGContextAddLineToPoint(ctx, cx + r, y)
            y += 3.0
        q.CGContextStrokePath(ctx)
        vignette = q.CGGradientCreateWithColorComponents(
            _rgb_space(),
            [*_alpha(VOID, 0.0), *_alpha(VOID, 0.0), *_alpha(VOID, 0.7)],
            [0.0, 0.62, 1.0],
            3,
        )
        q.CGContextDrawRadialGradient(ctx, vignette, (cx, cy), 0, (cx, cy), r, 0)
        if motion and not result:
            sweep = cy - r + ((now % 2.8) / 2.8) * 2 * r
            band = q.CGGradientCreateWithColorComponents(
                _rgb_space(),
                [*_alpha(FLARE, 0.0), *_alpha(FLARE, 0.16), *_alpha(FLARE, 0.0)],
                [0.0, 0.8, 1.0],
                3,
            )
            q.CGContextDrawLinearGradient(ctx, band, (cx, sweep - 26), (cx, sweep + 2), 0)
        if result:
            _fill(ctx, _alpha(VOID, 0.62))
            q.CGContextFillRect(ctx, q.CGRectMake(cx - r, cy - r, 2 * r, 2 * r))
    # guide ticks on the picture's edge
    _ticks(ctx, cx, cy, r - r * 0.09, 4, r * 0.06, 1.5, _alpha(FLARE, 0.55), -math.pi / 2)
    # the instrument rings
    turn = (now % 80.0) / 80.0 * 2 * math.pi if motion else 0.0
    back = -(now % 120.0) / 120.0 * 2 * math.pi if motion else 0.0
    _ticks(ctx, cx, cy, lay.dial, 120, 4.0, 1.0, _alpha(FLARE, 0.32), turn)
    _ticks(ctx, cx, cy, lay.dial, 12, 10.0, 1.6, _alpha(FLARE, 0.7), turn)
    _stroke(ctx, _alpha(SIGNAL, 0.4), 1.0)
    _circle(ctx, cx, cy, lay.outer)
    q.CGContextStrokePath(ctx)
    _ticks(ctx, cx, cy, lay.outer, 4, -7.0, 1.6, _alpha(SIGNAL, 0.8), back + math.pi / 4)
    # corner brackets around the picture
    b, arm = lay.ring + r * 0.12, r * 0.14
    _stroke(ctx, _alpha(LINE2, 0.9), 1.2)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        px, py = cx + dx * b, cy + dy * b
        _polyline(ctx, [(px, py - dy * arm), (px, py), (px - dx * arm, py)])
        q.CGContextStrokePath(ctx)
    # the neon ring, the countdown or the result
    ring_w = max(2.5, r * 0.018)
    if scene.phase == "passed":
        fill = (
            1.0
            if not motion or scene.since_result is None
            else min(1.0, scene.since_result / FILL_SECONDS)
        )
        _neon_ring(ctx, cx, cy, lay.ring, ring_w, glow=10.0)
        with _glowing(ctx, _alpha(FLARE, 0.95), 22.0):
            _stroke(ctx, EMBER, ring_w * 2.6)
            _arc(
                ctx, cx, cy, lay.comet, -math.pi / 2, -math.pi / 2 + 2 * math.pi * max(0.001, fill)
            )
            q.CGContextStrokePath(ctx)
        _stroke(ctx, _alpha(CORE, 0.8), ring_w * 0.7)
        _arc(ctx, cx, cy, lay.comet, -math.pi / 2, -math.pi / 2 + 2 * math.pi * max(0.001, fill))
        q.CGContextStrokePath(ctx)
    elif scene.phase == "failed":
        flash = 0.0
        if motion and scene.since_result is not None:
            flash = max(0.0, 1.0 - scene.since_result / FLASH_SECONDS)
        _neon_ring(
            ctx,
            cx,
            cy,
            lay.ring,
            ring_w * (1 + flash),
            glow=12.0 + 18.0 * flash,
            tint=SIGNAL,
            strength=1.0,
        )
        _stroke(ctx, _alpha(SIGNAL, 0.35 + 0.5 * flash), ring_w)
        _circle(ctx, cx, cy, lay.comet)
        q.CGContextStrokePath(ctx)
    else:
        _neon_ring(ctx, cx, cy, lay.ring, ring_w)
        if scene.countdown is not None:
            urgent = scene.countdown <= 0.3
            colors = (SIGNAL, SIGNAL) if urgent else (FLARE, EMBER)
            span = 2 * math.pi * scene.countdown
            if span > 0.02:
                head = -math.pi / 2 + span
                _comet(ctx, cx, cy, lay.comet, head, span, ring_w * 1.25, colors, floor=0.3)
        else:
            _comet(
                ctx,
                cx,
                cy,
                lay.comet,
                _thinking_head(now, motion),
                math.radians(84),
                ring_w * 1.25,
                (FLARE, EMBER),
            )
    # the step
    glyph = scene.glyph
    if glyph == "check":
        _check(ctx, cx, cy, r * 0.9, FLARE)
    elif glyph == "cross":
        _cross(ctx, cx, cy, r * 0.9)
    elif glyph in ("left", "right", "up", "down"):
        center = {"left": lay.left, "right": lay.right, "up": lay.up, "down": lay.down}[glyph]
        size = lay.tri
        _triangle(ctx, center[0], center[1], size, glyph, solid=True)
        if scene.double:
            dx = {"left": -1, "right": 1}.get(glyph, 0) * size * 0.75
            dy = {"up": -1, "down": 1}.get(glyph, 0) * size * 0.75
            _triangle(ctx, center[0] + dx, center[1] + dy, size * 0.8, glyph, solid=True, alpha=0.8)
        if glyph in ("left", "right"):
            sign = -1 if glyph == "left" else 1
            for index in range(3):
                wave = ((now * 1.6) % 1.0) if motion else 0.5
                lit = max(0.0, 1.0 - abs(wave - index / 3.0) * 3.0) if motion else 0.0
                ex = cx + sign * (lay.outer + size * (0.12 + index * 0.18))
                if abs(ex - center[0]) > size * 0.55:
                    _triangle(ctx, ex, cy, size * 0.32, glyph, solid=False, alpha=0.3 + 0.6 * lit)
    elif glyph == "look":
        pulse = 0.65 + 0.35 * math.sin(now * 2 * math.pi / 1.6) if motion else 1.0
        _triangle(ctx, lay.up[0], lay.up[1], lay.tri * 0.9, "up", solid=False, alpha=pulse)
    # the lines
    glow_color = {"passed": FLARE, "failed": SIGNAL}.get(scene.phase, EMBER)
    headline_color = FLARE if scene.phase == "passed" else CORE
    _text(
        scene.headline,
        cx,
        lay.headline_y,
        size=lay.headline_size,
        color=headline_color,
        weight="bold",
        kern=lay.headline_size * 0.16,
        glow=(_alpha(glow_color, 0.85), 18.0),
    )
    if scene.hint:
        _text(
            scene.hint,
            cx,
            lay.hint_y,
            size=lay.hint_size,
            color=FLARE,
            weight="semibold",
            kern=lay.hint_size * 0.18,
            glow=(_alpha(EMBER, 0.6), 10.0),
        )
    if scene.phase == "failed" and scene.detail:
        _text(
            scene.detail,
            cx,
            lay.hint_y - lay.hint_size * 0.7,
            size=lay.hint_size,
            color=_alpha(CORE, 0.85),
            weight="regular",
            mono=False,
            wrap=min(lay.width - 80, lay.outer * 3.0),
        )
    elif scene.samples is not None and scene.phase == "running":
        count, needed = scene.samples
        _text(
            scene.detail,
            cx,
            lay.detail_y,
            size=lay.small_size,
            color=_alpha(FLARE, 0.9),
            weight="semibold",
            kern=lay.small_size * 0.2,
        )
        seg_w, seg_h, gap = lay.small_size * 1.9, lay.small_size * 0.5, lay.small_size * 0.35
        total = needed * seg_w + (needed - 1) * gap
        x = cx - total / 2
        y = lay.detail_y + lay.small_size * 1.25
        for index in range(needed):
            skew = seg_h * 0.8
            points = [(x + skew, y), (x + seg_w, y), (x + seg_w - skew, y + seg_h), (x, y + seg_h)]
            if index < count:
                with _saved(ctx):
                    _glow(ctx, _alpha(EMBER, 0.8), 8.0)
                    _fill(ctx, _mix(EMBER, FLARE, index / max(1, needed - 1)))
                    _polyline(ctx, points, close=True)
                    q.CGContextFillPath(ctx)
            else:
                _stroke(ctx, _alpha(LINE2, 1.0), 1.0)
                _polyline(ctx, points, close=True)
                q.CGContextStrokePath(ctx)
            x += seg_w + gap


def paint_compact(ctx: Any, lay: Layout, scene: Scene, now: float, motion: bool) -> None:
    """The Touch ID panel: a chamfered Void plate, the glyph in a small ring, three lines."""
    q = _q()
    w, h = lay.width, lay.height
    cut = 16.0
    with _saved(ctx):
        _glow(ctx, _alpha(SIGNAL, 0.5), 16.0)
        _fill(ctx, _alpha(VOID, 0.95))
        _chamfer(ctx, 6, 6, w - 12, h - 12, cut)
        q.CGContextFillPath(ctx)
    _stroke(ctx, _alpha(SIGNAL, 0.85), 1.0)
    _chamfer(ctx, 6, 6, w - 12, h - 12, cut)
    q.CGContextStrokePath(ctx)
    cx, cy, r = lay.cx, lay.cy, lay.radius
    if scene.phase == "passed":
        _neon_ring(ctx, cx, cy, lay.ring, 2.0, glow=10.0, tint=EMBER)
        _check(ctx, cx, cy, r * 1.1, FLARE)
    elif scene.phase == "failed":
        _neon_ring(ctx, cx, cy, lay.ring, 2.0, glow=12.0, tint=SIGNAL)
        _cross(ctx, cx, cy, r * 1.1)
    else:
        _neon_ring(ctx, cx, cy, lay.ring, 2.0, glow=8.0)
        _comet(
            ctx,
            cx,
            cy,
            lay.comet,
            _thinking_head(now, motion),
            math.radians(84),
            2.2,
            (FLARE, EMBER),
        )
        _fingerprint(ctx, cx, cy, r * 0.85, FLARE)
    tx = cx + lay.outer + 20
    _text(
        scene.purpose,
        tx,
        h * 0.27,
        size=lay.small_size,
        color=_alpha(FLARE, 0.8),
        weight="semibold",
        kern=2.0,
        align="left",
    )
    color = FLARE if scene.phase == "passed" else CORE
    glow = {"passed": FLARE, "failed": SIGNAL}.get(scene.phase, EMBER)
    _text(
        scene.headline,
        tx,
        h * 0.5,
        size=lay.headline_size,
        color=color,
        weight="bold",
        kern=3.0,
        align="left",
        glow=(_alpha(glow, 0.8), 12.0),
    )
    detail = scene.detail
    if detail:
        mono = scene.phase == "running"
        _text(
            detail,
            tx,
            h * 0.74,
            size=lay.small_size if mono else lay.small_size * 1.1,
            color=_alpha(CORE, 0.75) if not mono else _alpha(FLARE, 0.9),
            weight="semibold" if mono else "regular",
            mono=mono,
            kern=1.6 if mono else 0.0,
            align="left",
        )


# -- offscreen -------------------------------------------------------------------------------


def render_png(
    path: Path,
    scene: Scene,
    image: Any = None,
    *,
    size: tuple[float, float] = (1512.0, 945.0),
    scale: float = 2.0,
    now: float = 0.0,
    motion: bool = True,
) -> Path:
    """Paint ``scene`` offscreen into a PNG (no window, no event loop): the cover over a dark
    stand-in for the desktop, or the Touch ID panel."""
    import AppKit  # type: ignore[import-not-found]
    import Foundation  # type: ignore[import-not-found]
    import Quartz as q  # type: ignore[import-not-found]

    width, height = size if scene.mode == "cover" else COMPACT_SIZE
    pw, ph = int(width * scale), int(height * scale)
    ctx = q.CGBitmapContextCreate(
        None, pw, ph, 8, 0, _rgb_space(), q.kCGImageAlphaPremultipliedLast
    )
    q.CGContextTranslateCTM(ctx, 0, ph)
    q.CGContextScaleCTM(ctx, scale, -scale)
    graphics = AppKit.NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, True)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(graphics)
    try:
        _fill(ctx, _hex("#2A2F3A"))
        q.CGContextFillRect(ctx, q.CGRectMake(0, 0, width, height))
        _fill(ctx, _hex("#3B4252"))
        q.CGContextFillRect(
            ctx, q.CGRectMake(width * 0.1, height * 0.12, width * 0.45, height * 0.6)
        )
        picture_image = picture(image) if image is not None else None
        if scene.mode == "cover":
            layout = cover_layout(width, height)
            _fill(ctx, _alpha(VOID, BACKGROUND_ALPHA))
            q.CGContextFillRect(ctx, q.CGRectMake(0, 0, width, height))
            paint_backdrop(ctx, layout, scene, now, motion)
            paint_hud(ctx, layout, scene, picture_image, now, motion)
        else:
            paint_compact(ctx, compact_layout(width, height), scene, now, motion)
    finally:
        AppKit.NSGraphicsContext.restoreGraphicsState()
    image_ref = q.CGBitmapContextCreateImage(ctx)
    url = Foundation.NSURL.fileURLWithPath_(str(path))
    destination = q.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    q.CGImageDestinationAddImage(destination, image_ref, None)
    if not q.CGImageDestinationFinalize(destination):
        raise OSError(f"could not write {path}")
    return Path(path)


# -- the demo --------------------------------------------------------------------------------


class _DemoClock:
    """A settable clock for snapshots."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def demo_snapshots(directory: Path, texts: dict[str, str], language: str) -> list[Path]:
    """The demo's key moments as PNGs in ``directory`` (offscreen; nothing opens)."""
    directory.mkdir(parents=True, exist_ok=True)
    clock = _DemoClock()
    written: list[Path] = []

    def shot(
        name: str,
        model: WindowModel,
        offset: tuple[float, float] = (0.0, 0.0),
        *,
        image: bool = True,
    ) -> None:
        frame = synthetic_frame(offset) if image else None
        written.append(render_png(directory / f"{name}.png", model.scene(), frame, now=clock.now))

    unlock = WindowModel(Intro("verify", "unlock", texts, language), clock=clock)
    shot("01-starting", unlock, image=False)
    unlock.step("look", clock.now + 12.0)
    unlock.hint("too_dark")
    clock.now += 2.0
    shot("02-look-too-dark", unlock)
    unlock.hint(None)
    unlock.step("turn_left", clock.now + 3.5)
    clock.now += 1.2
    shot("03-turn-left", unlock, demo_offset("turn_left", 1.2))
    unlock.result(True, "match")
    clock.now += 0.8
    shot("04-unlocked", unlock)
    step_up = WindowModel(
        Intro("verify", "step_up", texts, language, tool="robot.move"), clock=clock
    )
    step_up.step("turn_right", clock.now + 3.5)
    clock.now += 2.9
    shot("05-step-up-turn-right-late", step_up, demo_offset("turn_right", 2.9))
    step_up.result(False, "multiple_faces")
    clock.now += 0.1
    shot("06-step-up-failed", step_up)
    enroll = WindowModel(Intro("enroll", "enroll", texts, language), clock=clock)
    enroll.step("touch_id", None)
    shot("07-enroll-touch-id", enroll, image=False)
    enroll.step("turn_more", clock.now + 1.6)
    enroll.last_turn = "turn_left"
    enroll.samples(6, 10)
    clock.now += 0.5
    shot("08-enroll-turn-further", enroll, demo_offset("turn_more", 0.5))
    enroll.step("look_up", clock.now + 3.0)
    enroll.samples(8, 10)
    clock.now += 0.7
    shot("09-enroll-look-up", enroll, demo_offset("look_up", 0.7))
    enroll.result(False, "timeout")
    clock.now += 1.0
    shot("10-enroll-failed", enroll)
    return written


def play_demo(
    view: Any,
    texts: dict[str, str],
    language: str,
    stop: threading.Event,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Drive ``view`` through :func:`~tau_guard.window.demo_events` with synthetic frames at
    15 fps, until the script ends or ``stop`` is set."""
    began = clock()
    step, step_at = "starting", began
    frozen = False
    for at, name, args in demo_events(texts, language):
        while True:
            left = began + at - clock()
            if left <= 0:
                break
            if not frozen:
                view.frame(synthetic_frame(demo_offset(step, clock() - step_at)))
            if stop.wait(min(left, 1 / 15)):
                return
        if name == "step":
            step, step_at = args[0], clock()
            view.step(args[0], None if args[1] is None else clock() + args[1])
        elif name == "start":
            frozen = False
            step, step_at = "starting", clock()
            view.start(args[0])
        elif name == "result":
            frozen = True
            view.result(*args)
        else:
            getattr(view, name)(*args)


def main(argv: list[str] | None = None, *, stdin: Any = None) -> int:
    """``python -m tau_guard.overlay demo``: the request (``{"texts", "language",
    "snapshot"?}``) on stdin. Exit 0 when the demo ran (or the snapshots were written), 3 when
    no window can open here (the reason on stdout as JSON). ``probe`` prints ``{"ok",
    "reason"}`` without opening anything."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["probe"]:  # tau guard window: could a window open from here?
        reason = headless_reason() or gui_reason()
        print(json.dumps({"ok": reason is None, "reason": reason}))
        return 0
    if args[:1] != ["demo"]:
        print("usage: python -m tau_guard.overlay demo|probe < request.json", file=sys.stderr)
        return 2
    source = sys.stdin if stdin is None else stdin
    try:
        request = json.loads(source.read() or "{}")
    except ValueError:
        request = {}
    request = request if isinstance(request, dict) else {}
    raw = request.get("texts")
    texts = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    language = request.get("language") if request.get("language") in ("en", "tr") else "en"
    snapshot = request.get("snapshot")
    if isinstance(snapshot, str) and snapshot:
        written = demo_snapshots(Path(snapshot), texts, str(language))
        print(json.dumps({"ok": True, "written": [str(p) for p in written]}))
        return 0
    stop = threading.Event()
    first = demo_events(texts, str(language))[0][2][0]
    view, reason = open_view(first, on_cancel=stop.set)
    if view is None:
        print(json.dumps({"ok": False, "reason": reason}))
        return 3
    player = threading.Thread(
        target=play_demo, args=(view, texts, language, stop), name="tau-guard-demo", daemon=True
    )
    player.start()
    try:
        view.run()
    finally:
        stop.set()
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
