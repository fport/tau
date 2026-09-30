"""The camera (ADR 0008 decision 12): only the built-in camera, opened for one attempt at most.

- **Device.** By default only the built-in camera is used: the device of type
  ``AVCaptureDeviceTypeBuiltInWideAngleCamera`` whose transport is ``bltn``. ``[component.guard]
  camera`` may name another device by its uniqueID instead. Continuity Camera (an iPhone,
  transport ``othr``) and virtual cameras (OBS and the like) are never picked by default: keeping
  them out is the only defence against injected frames.
- **Index.** OpenCV's AVFoundation backend lists ``devicesWithMediaType:video`` followed by
  ``devicesWithMediaType:muxed`` and sorts that list by ``uniqueID`` (NSString ``compare:``,
  ``cap_avfoundation_mac.mm`` in 4.x and 5.x); the cv2 index is the device's position in it
  (:func:`opencv_order`, :func:`select_device`). Python's string order equals ``compare:`` for
  ASCII, so a non-ASCII uniqueID refuses (``camera_unavailable``). The list is enumerated again
  right after ``isOpened()``; any change aborts with ``camera_unavailable``, because the index
  may then point at another device. :data:`VERIFIED_OPENCV` names the OpenCV series whose
  enumeration was checked, and a test pins it to the installed one.
- **Permission.** The worker reads ``authorizationStatusForMediaType_`` itself (OpenCV is told
  to stay out with ``OPENCV_AVFOUNDATION_SKIP_AUTH=1``): ``0`` (not determined) requests access
  and answers ``permission_pending``; ``1`` (restricted) and ``2`` (denied) answer
  ``camera_denied``; ``3`` goes on.
- **Frames.** 640x480, the first :data:`WARMUP_FRAMES` frames are dropped (exposure), the
  camera stays open for at most :data:`MAX_OPEN_SECONDS` (counted from the open, warm-up
  included, whatever ``verify_timeout_seconds`` says; :attr:`AVFoundationCamera.stops_at` tells
  the check when the frames stop), and :func:`opened` releases it in ``finally`` on every path.
  The worker turns SIGTERM into an exception, so a kill from the hub releases it too; after
  SIGKILL the system stops the capture with the process.

:class:`FrameSource` is the seam: :class:`AVFoundationCamera` is the real source, and tests
pass fakes (``tau_guard.testing``). Issue 043 may reuse the source. pyobjc and cv2 load lazily.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "BUILTIN",
    "BUILTIN_TRANSPORT",
    "BUILTIN_TYPE",
    "MAX_OPEN_SECONDS",
    "VERIFIED_OPENCV",
    "WARMUP_FRAMES",
    "AVFoundationCamera",
    "AVFoundationDevices",
    "AVFoundationPermission",
    "CameraError",
    "Device",
    "DeviceList",
    "Frame",
    "FrameSource",
    "Permission",
    "check_permission",
    "fourcc",
    "opencv_order",
    "opened",
    "select_device",
]

BUILTIN = "builtin"
BUILTIN_TYPE = "AVCaptureDeviceTypeBuiltInWideAngleCamera"
BUILTIN_TRANSPORT = "bltn"
WARMUP_FRAMES = 5
MAX_OPEN_SECONDS = 20.0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
VERIFIED_OPENCV = ("4.14",)
"""OpenCV series whose AVFoundation device order (video + muxed, sorted by uniqueID) was read in
its source. Moving to another series means reading ``cap_avfoundation_mac.mm`` again."""

NOT_DETERMINED, RESTRICTED, DENIED, AUTHORIZED = 0, 1, 2, 3
CAMERA_REASONS = ("camera_unavailable", "camera_denied", "permission_pending", "camera_busy")


class CameraError(Exception):
    """The camera cannot be used; ``reason`` is one of :data:`CAMERA_REASONS`."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class Device:
    unique_id: str
    name: str
    device_type: str
    transport: str
    """The transport FourCC as four characters (``bltn``, ``othr``, ``usb ``, ``virt``)."""
    manufacturer: str = ""

    @property
    def builtin(self) -> bool:
        return self.device_type == BUILTIN_TYPE and self.transport == BUILTIN_TRANSPORT


@dataclass(frozen=True)
class Frame:
    image: Any
    at: float
    """Monotonic seconds when the frame was read."""


def fourcc(value: int) -> str:
    """An AVFoundation transport type (a 32-bit FourCC) as text: ``0x626C746E`` → ``bltn``."""
    try:
        return int(value).to_bytes(4, "big").decode("latin-1")
    except (OverflowError, ValueError):
        return "????"


def opencv_order(devices: Sequence[Device]) -> list[Device]:
    """The devices in OpenCV's index order: the given (video, then muxed) list sorted by
    uniqueID. Raises :class:`CameraError` for a non-ASCII uniqueID, whose order Python and
    NSString ``compare:`` might not agree on."""
    for device in devices:
        if not device.unique_id.isascii():
            raise CameraError("camera_unavailable", "a camera has a non-ASCII uniqueID")
    return sorted(devices, key=lambda device: device.unique_id)


def select_device(devices: Sequence[Device], camera: str = BUILTIN) -> tuple[int, Device]:
    """``(cv2 index, device)`` for the ``[component.guard] camera`` setting: ``builtin`` picks
    the built-in wide-angle camera on transport ``bltn``, anything else the device with that
    uniqueID. Raises :class:`CameraError` (``camera_unavailable``) when there is none."""
    ordered = opencv_order(devices)
    if camera == BUILTIN:
        chosen = [device for device in ordered if device.builtin]
    else:
        chosen = [device for device in ordered if device.unique_id == camera]
    if not chosen:
        raise CameraError("camera_unavailable", f"no camera matches {camera!r}")
    return ordered.index(chosen[0]), chosen[0]


@runtime_checkable
class DeviceList(Protocol):
    def devices(self) -> list[Device]:
        """Video devices followed by muxed devices, as AVFoundation lists them."""
        ...


@runtime_checkable
class Permission(Protocol):
    def status(self) -> int:
        """``AVAuthorizationStatus`` for video: 0 not determined, 1 restricted, 2 denied,
        3 authorized."""
        ...

    def request(self) -> None:
        """Ask for camera access (the answer comes later, in the system's prompt)."""
        ...


def check_permission(permission: Permission) -> None:
    """Raise :class:`CameraError` unless camera access is authorized; ask when it was never
    decided."""
    status = permission.status()
    if status == AUTHORIZED:
        return
    if status == NOT_DETERMINED:
        permission.request()
        raise CameraError("permission_pending", "camera access requested")
    raise CameraError("camera_denied", f"authorization status {status}")


@runtime_checkable
class FrameSource(Protocol):
    """A camera for one attempt: :meth:`open`, then :meth:`read` until ``None``, then
    :meth:`close` (use :func:`opened`, which closes on every path)."""

    def open(self) -> None:
        """Raises :class:`CameraError`."""
        ...

    def read(self) -> Frame | None:
        """The next frame, ``None`` once the source is done (time limit, read failure)."""
        ...

    def close(self) -> None: ...


@contextmanager
def opened(source: FrameSource) -> Iterator[Iterator[Frame]]:
    """Open ``source`` and yield its frames; it is closed in ``finally``, whatever happens
    (including an open that fails half-way and the worker's SIGTERM exception)."""
    try:
        source.open()
        yield _frames(source)
    finally:
        source.close()


def _frames(source: FrameSource) -> Iterator[Frame]:
    while True:
        frame = source.read()
        if frame is None:
            return
        yield frame


# -- macOS ---------------------------------------------------------------------------------------


class AVFoundationDevices:
    """:class:`DeviceList` through pyobjc (enumeration only; nothing is opened)."""

    def __init__(self, av: Any | None = None) -> None:
        if av is None:
            import AVFoundation as av  # type: ignore[import-not-found,no-redef]
        self._av = av

    def devices(self) -> list[Device]:
        av = self._av
        found: list[Device] = []
        for media in (av.AVMediaTypeVideo, av.AVMediaTypeMuxed):
            for device in av.AVCaptureDevice.devicesWithMediaType_(media) or []:
                found.append(
                    Device(
                        unique_id=str(device.uniqueID()),
                        name=str(device.localizedName() or ""),
                        device_type=str(device.deviceType() or ""),
                        transport=fourcc(int(device.transportType())),
                        manufacturer=str(device.manufacturer() or ""),
                    )
                )
        return found


class AVFoundationPermission:
    """:class:`Permission` through pyobjc."""

    def __init__(self, av: Any | None = None) -> None:
        if av is None:
            import AVFoundation as av  # type: ignore[import-not-found,no-redef]
        self._av = av

    def status(self) -> int:
        av = self._av
        return int(av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo))

    def request(self) -> None:
        av = self._av
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            av.AVMediaTypeVideo, lambda granted: None
        )


class AVFoundationCamera:
    """The built-in camera (or ``camera``) through ``cv2.VideoCapture(index,
    CAP_AVFOUNDATION)``. ``devices``, ``permission``, ``capture`` (a ``VideoCapture`` factory
    taking the index) and ``clock`` are injectable for tests."""

    def __init__(
        self,
        camera: str = BUILTIN,
        *,
        devices: DeviceList | None = None,
        permission: Permission | None = None,
        capture: Callable[[int], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_open: float = MAX_OPEN_SECONDS,
        warmup: int = WARMUP_FRAMES,
    ) -> None:
        self.camera = camera
        self._devices = devices
        self._permission = permission
        self._capture_factory = capture
        self._clock = clock
        self.max_open = max_open
        self.warmup = warmup
        self.device: Device | None = None
        self.opened_at: float | None = None
        self.closed_at: float | None = None
        self._cap: Any = None
        self._deadline = 0.0

    def _default_capture(self, index: int) -> Any:
        from tau_guard.engine import import_cv2

        cv2 = import_cv2()
        cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        return cap

    def open(self) -> None:
        devices = self._devices or AVFoundationDevices()
        permission = self._permission or AVFoundationPermission()
        check_permission(permission)
        listed = devices.devices()
        before = [device.unique_id for device in opencv_order(listed)]
        index, device = select_device(listed, self.camera)
        factory = self._capture_factory or self._default_capture
        self.opened_at = self._clock()
        self._deadline = self.opened_at + self.max_open
        self._cap = factory(index)
        if not self._cap.isOpened():
            raise CameraError("camera_unavailable", f"camera index {index} did not open")
        after = [d.unique_id for d in opencv_order(devices.devices())]
        if after != before:
            raise CameraError("camera_unavailable", "the camera list changed during the open")
        self.device = device
        self._configure()
        good = 0
        for _ in range(self.warmup):
            ok, _image = self._cap.read()
            good += bool(ok)
        if self.warmup and not good:
            raise CameraError("camera_busy", "no frame during the warm-up")

    def _configure(self) -> None:
        try:
            from tau_guard.engine import import_cv2

            cv2 = import_cv2()
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        except Exception:  # a fake capture in tests, or a property the device refuses
            pass

    def read(self) -> Frame | None:
        if self._cap is None or self._clock() >= self._deadline:
            return None
        ok, image = self._cap.read()
        if not ok or image is None:
            return None
        return Frame(image, self._clock())

    def close(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            finally:
                self.closed_at = self._clock()

    @property
    def stops_at(self) -> float | None:
        """When :meth:`read` stops delivering frames (the :data:`MAX_OPEN_SECONDS` cap), on
        the frames' clock; ``None`` before the open. The check plans its steps around it."""
        return self._deadline if self.opened_at is not None else None

    @property
    def open_seconds(self) -> float | None:
        """How long the camera was (or has been) on; ``None`` if it was never switched on."""
        if self.opened_at is None:
            return None
        end = self.closed_at if self.closed_at is not None else self._clock()
        return max(0.0, end - self.opened_at)
