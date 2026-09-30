"""The camera: built-in selection over fake enumerations, permissions, warm-up, the time limit
and release on every path (including SIGTERM). No test opens a real camera."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from tau_guard.camera import (
    BUILTIN_TYPE,
    MAX_OPEN_SECONDS,
    VERIFIED_OPENCV,
    WARMUP_FRAMES,
    AVFoundationCamera,
    AVFoundationDevices,
    CameraError,
    Device,
    FrameSource,
    check_permission,
    fourcc,
    opencv_order,
    opened,
    select_device,
)
from tau_guard.testing import FakeFrameSource

EXTERNAL = "AVCaptureDeviceTypeExternal"
BUILTIN = Device("47B4B64B-7067-4B9C-AD2B-AE273A71F4B5", "MacBook Pro Camera", BUILTIN_TYPE, "bltn")
IPHONE = Device("0A8C1F2E-0000-4000-8000-000000000001", "iPhone Camera", EXTERNAL, "othr")
OBS = Device("7626645E-4425-469E-9D8B-97E0FA59AC75", "OBS Virtual Camera", EXTERNAL, "virt")
SNEAKY = Device("00000000-0000-0000-0000-000000000000", "Fake Built-in", BUILTIN_TYPE, "virt")
USB = Device("0x1420000005ac8600", "USB Camera", EXTERNAL, "usb ")


def test_fourcc() -> None:
    assert fourcc(0x626C746E) == "bltn" and fourcc(0x6F746872) == "othr"


def test_the_index_follows_opencvs_uniqueid_order() -> None:
    devices = [BUILTIN, IPHONE, OBS]  # video list order as AVFoundation gives it
    assert [d.name for d in opencv_order(devices)] == [
        "iPhone Camera",
        "MacBook Pro Camera",
        "OBS Virtual Camera",
    ]
    assert select_device(devices) == (1, BUILTIN)
    assert select_device([OBS, BUILTIN]) == (0, BUILTIN)


def test_only_a_bltn_built_in_wide_angle_camera_is_picked() -> None:
    for devices in ([IPHONE], [OBS], [SNEAKY], [USB], [IPHONE, OBS, SNEAKY, USB], []):
        with pytest.raises(CameraError) as caught:
            select_device(devices)
        assert caught.value.reason == "camera_unavailable"
    assert select_device([SNEAKY, BUILTIN, USB])[1] == BUILTIN


def test_a_camera_id_names_another_device() -> None:
    assert select_device([BUILTIN, USB], USB.unique_id) == (0, USB)
    with pytest.raises(CameraError):
        select_device([BUILTIN], USB.unique_id)


def test_an_ambiguous_camera_list_refuses() -> None:
    twin = Device("99999999-0000-4000-8000-000000000009", "Second Built-in", BUILTIN_TYPE, "bltn")
    same_id = Device(BUILTIN.unique_id, "OBS Virtual Camera", EXTERNAL, "virt")
    for devices, camera in (
        ([BUILTIN, twin], "builtin"),  # two devices claim to be the built-in camera
        ([BUILTIN, same_id], "builtin"),  # another device copies its uniqueID
        ([same_id, BUILTIN], "builtin"),
        ([USB, USB], USB.unique_id),
    ):
        with pytest.raises(CameraError) as caught:
            select_device(devices, camera)
        assert caught.value.reason == "camera_unavailable"
    copied = Device(IPHONE.unique_id, "iPhone (muxed)", EXTERNAL, "othr")
    assert select_device([IPHONE, copied, BUILTIN]) == (2, BUILTIN)  # others may repeat


def test_a_non_ascii_unique_id_refuses() -> None:
    odd = Device("cam\u00e9ra", "odd", BUILTIN_TYPE, "bltn")
    with pytest.raises(CameraError):
        select_device([BUILTIN, odd])


def test_the_enumeration_is_pinned_to_the_installed_opencv() -> None:
    """The index recipe was read from OpenCV's ``cap_avfoundation_mac.mm`` for these series; a
    new OpenCV series needs that source read again before this list grows."""
    import cv2

    assert cv2.__version__.startswith(VERIFIED_OPENCV), cv2.__version__


class Permission:
    def __init__(self, status: int) -> None:
        self._status = status
        self.requests = 0

    def status(self) -> int:
        return self._status

    def request(self) -> None:
        self.requests += 1


@pytest.mark.parametrize(
    ("status", "reason", "requests"),
    [(0, "permission_pending", 1), (1, "camera_denied", 0), (2, "camera_denied", 0)],
)
def test_permission_status(status: int, reason: str, requests: int) -> None:
    permission = Permission(status)
    with pytest.raises(CameraError) as caught:
        check_permission(permission)
    assert caught.value.reason == reason and permission.requests == requests
    check_permission(Permission(3))


class Devices:
    def __init__(self, *lists: list[Device]) -> None:
        self.lists = list(lists)
        self.calls = 0

    def devices(self) -> list[Device]:
        self.calls += 1
        return list(self.lists[min(self.calls - 1, len(self.lists) - 1)])


class Capture:
    def __init__(self, index: int, *, opens: bool = True, fail_reads: bool = False) -> None:
        self.index = index
        self.opens = opens
        self.fail_reads = fail_reads
        self.reads = 0
        self.released = 0

    def isOpened(self) -> bool:  # noqa: N802 (cv2's name)
        return self.opens

    def read(self) -> tuple[bool, object]:
        self.reads += 1
        return (False, None) if self.fail_reads else (True, f"frame-{self.reads}")

    def set(self, prop: int, value: float) -> bool:
        return True

    def release(self) -> None:
        self.released += 1


class Clock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        self.t += 0.1
        return self.t


def camera(devices: Devices, *, capture: Capture | None = None, status: int = 3, **kw):
    made: list[Capture] = []

    def factory(index: int) -> Capture:
        cap = capture or Capture(index)
        cap.index = index
        made.append(cap)
        return cap

    cam = AVFoundationCamera(
        devices=devices, permission=Permission(status), capture=factory, clock=Clock(), **kw
    )
    return cam, made


def test_open_uses_the_built_in_index_drops_warm_up_frames_and_releases() -> None:
    cam, made = camera(Devices([IPHONE, BUILTIN, OBS]))
    assert isinstance(cam, FrameSource)
    with opened(cam) as frames:
        first = next(frames)
    (cap,) = made
    assert cap.index == 1 and cam.device == BUILTIN
    assert first.image == f"frame-{WARMUP_FRAMES + 1}"
    assert cap.released == 1
    assert cam.open_seconds is not None and cam.open_seconds > 0


def test_a_changed_device_list_after_the_open_aborts() -> None:
    cam, made = camera(Devices([BUILTIN, OBS], [BUILTIN, OBS, IPHONE]))
    with pytest.raises(CameraError) as caught, opened(cam):
        pass
    assert caught.value.reason == "camera_unavailable"
    assert made[0].released == 1 and made[0].reads == 0


def test_a_camera_that_does_not_open_is_released() -> None:
    cap = Capture(0, opens=False)
    cam, _ = camera(Devices([BUILTIN]), capture=cap)
    with pytest.raises(CameraError) as caught, opened(cam):
        pass
    assert caught.value.reason == "camera_unavailable" and cap.released == 1


def test_no_frames_during_the_warm_up_is_camera_busy() -> None:
    cap = Capture(0, fail_reads=True)
    cam, _ = camera(Devices([BUILTIN]), capture=cap)
    with pytest.raises(CameraError) as caught, opened(cam):
        pass
    assert caught.value.reason == "camera_busy" and cap.released == 1


def test_permission_is_checked_before_anything_opens() -> None:
    for status, reason in ((0, "permission_pending"), (2, "camera_denied")):
        cam, made = camera(Devices([BUILTIN]), status=status)
        with pytest.raises(CameraError) as caught, opened(cam):
            pass
        assert caught.value.reason == reason and made == []


def test_the_camera_stays_open_at_most_twenty_seconds() -> None:
    assert MAX_OPEN_SECONDS == 20.0
    cam, made = camera(Devices([BUILTIN]))
    assert cam.stops_at is None
    with opened(cam) as frames:
        seen = list(frames)
    assert cam.opened_at is not None and len(seen) > 50  # the fake capture never runs dry
    assert seen[-1].at - cam.opened_at <= MAX_OPEN_SECONDS < seen[-1].at - cam.opened_at + 0.5
    assert cam.stops_at == cam.opened_at + MAX_OPEN_SECONDS  # what the check plans around
    assert all(frame.at < cam.stops_at for frame in seen)
    assert made[0].released == 1


def test_release_happens_when_the_consumer_raises() -> None:
    cam, made = camera(Devices([BUILTIN]))
    with pytest.raises(RuntimeError), opened(cam) as frames:
        next(frames)
        raise RuntimeError("the engine broke")
    assert made[0].released == 1


def test_fake_sources_close_on_every_path() -> None:
    source = FakeFrameSource([], open_error=CameraError("camera_denied"))
    with pytest.raises(CameraError), opened(source):
        pass
    assert source.closed
    source = FakeFrameSource([], read_error=OSError("gone"))
    with pytest.raises(OSError), opened(source) as frames:
        next(frames)
    assert source.closed


def test_sigterm_releases_the_camera(tmp_path: Path) -> None:
    """The worker turns SIGTERM into an exception, so ``opened`` releases in ``finally``."""
    marker = tmp_path / "released"
    started = tmp_path / "started"
    script = textwrap.dedent(
        f"""
        import signal, time
        from pathlib import Path
        from tau_guard import worker
        from tau_guard.camera import Frame, opened
        signal.signal(signal.SIGTERM, worker._on_term)

        class Endless:
            def open(self):
                Path({str(started)!r}).write_text("on")
            def read(self):
                time.sleep(0.01)
                return Frame(None, time.monotonic())
            def close(self):
                Path({str(marker)!r}).write_text("released")

        try:
            with opened(Endless()) as frames:
                for _ in frames:
                    pass
        except worker.Terminated:
            raise SystemExit(143)
        """
    )
    process = subprocess.Popen([sys.executable, "-c", script])
    try:
        deadline = time.monotonic() + 30
        while not started.exists():
            assert time.monotonic() < deadline, "the fake camera never opened"
            time.sleep(0.02)
        os.kill(process.pid, signal.SIGTERM)
        assert process.wait(timeout=30) == 143
    finally:
        if process.poll() is None:
            process.kill()
    assert marker.read_text() == "released"


def test_the_pyobjc_device_list_maps_fields() -> None:
    class Dev:
        def __init__(self, uid: str, kind: str, transport: int) -> None:
            self.uid, self.kind, self.transport = uid, kind, transport

        def uniqueID(self) -> str:  # noqa: N802
            return self.uid

        def localizedName(self) -> str:  # noqa: N802
            return "cam"

        def deviceType(self) -> str:  # noqa: N802
            return self.kind

        def transportType(self) -> int:  # noqa: N802
            return self.transport

        def manufacturer(self) -> str:
            return "Apple Inc."

    class AV:
        AVMediaTypeVideo = "vide"
        AVMediaTypeMuxed = "muxx"

        class AVCaptureDevice:
            @staticmethod
            def devicesWithMediaType_(media: str) -> list[Dev]:  # noqa: N802
                if media == "vide":
                    return [Dev("B", BUILTIN_TYPE, 0x626C746E)]
                return [Dev("A", "AVCaptureDeviceTypeExternal", 0x6F746872)]

    devices = AVFoundationDevices(AV).devices()
    assert [(d.unique_id, d.transport) for d in devices] == [("B", "bltn"), ("A", "othr")]
    assert select_device(devices) == (1, devices[0])
