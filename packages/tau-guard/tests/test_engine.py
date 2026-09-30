"""The face engine: YuNet rows, vectors, the vendored model and its checksum, SFace installs."""

from __future__ import annotations

import hashlib
import io
import math
import os
import random
import shutil
import stat
from pathlib import Path

import pytest
from tau_guard.engine import (
    SFACE_FILE,
    SFACE_SHA256,
    SFACE_URL,
    YUNET_SHA256,
    Face,
    FaceEngine,
    ModelChecksumError,
    ModelError,
    OpenCvFaceEngine,
    cosine,
    file_sha256,
    install_sface,
    iou,
    mean_vector,
    model_state,
    normalise,
    sface_path,
    vendored_yunet,
)
from tau_guard.liveness import Calibration
from tau_guard.testing import FakeEngine, FakeFrameSource, face_row
from tau_guard.verify import Policy, run_check

PACKAGE = Path(__file__).resolve().parents[1]


def test_face_geometry_from_a_yunet_row() -> None:
    face = Face.from_row(face_row(cx=300, iod=80, yaw=0.25))
    assert face.iod == pytest.approx(80)
    assert face.yaw == pytest.approx(0.25)
    assert Face.from_row(face.row()) == face
    squeezed = Face.from_row(face_row(cx=300, iod=80, yaw=0.25, scale_x=0.6))
    assert squeezed.iod == pytest.approx(48) and squeezed.yaw == pytest.approx(0.25)
    with pytest.raises(ValueError):
        Face.from_row([1.0] * 14)
    with pytest.raises(ValueError):
        Face.from_row([math.nan] * 15)


def test_iou_of_face_boxes() -> None:
    a = Face.from_row(face_row(cx=320))
    assert iou(a, a) == pytest.approx(1.0)
    assert iou(a, Face.from_row(face_row(cx=330))) > 0.8
    assert iou(a, Face.from_row(face_row(cx=600))) == 0.0


def test_embeddings_are_l2_normalised_and_compared_by_cosine() -> None:
    rng = random.Random(1)
    vector = normalise(rng.gauss(0, 3) for _ in range(128))
    assert math.fsum(v * v for v in vector) == pytest.approx(1.0)
    assert cosine(vector, vector) == pytest.approx(1.0)
    assert cosine(vector, tuple(-v for v in vector)) == pytest.approx(-1.0)
    mean = mean_vector([vector, vector])
    assert cosine(mean, vector) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        normalise([0.0] * 128)


def test_the_vendored_yunet_and_its_license_ship_in_the_package() -> None:
    path = vendored_yunet()
    assert path.is_file() and path.parent.name == "models"
    assert file_sha256(path) == YUNET_SHA256
    assert model_state(path, YUNET_SHA256) == "ok"
    license_text = (path.parent / "LICENSE-yunet").read_text()
    assert "MIT License" in license_text and "Shiqi Yu" in license_text


def test_yunet_sha256_is_checked_at_load(tmp_path: Path) -> None:
    changed = tmp_path / "yunet.onnx"
    shutil.copy(vendored_yunet(), changed)
    with changed.open("r+b") as handle:
        handle.seek(1000)
        byte = handle.read(1)
        handle.seek(1000)
        handle.write(bytes([byte[0] ^ 0xFF]))
    with pytest.raises(ModelChecksumError) as caught:
        OpenCvFaceEngine(None, yunet=changed)
    assert caught.value.expected == YUNET_SHA256
    with pytest.raises(ModelError) as missing:
        OpenCvFaceEngine(None, yunet=tmp_path / "nowhere.onnx")
    assert missing.value.reason == "missing"
    with pytest.raises(ModelError):  # an SFace file that is not the pinned one never loads
        OpenCvFaceEngine(changed)


def test_the_real_yunet_finds_no_face_in_a_blank_frame() -> None:
    import numpy as np

    engine = OpenCvFaceEngine(None)
    assert isinstance(engine, FaceEngine)
    for shade in (0, 128, 255):
        frame = np.full((480, 640, 3), shade, dtype=np.uint8)
        assert engine.detect(frame) == []
    frames = [
        __import__("tau_guard.camera", fromlist=["Frame"]).Frame(
            np.zeros((480, 640, 3), np.uint8), 100.0 + i / 30
        )
        for i in range(10)
    ]
    source = FakeFrameSource(frames)
    result = run_check(
        Policy("unlock", 0.5, 2, timeout=5),
        [0.0] * 127 + [1.0],
        Calibration(1, 0.4, 0.4),
        engine,
        source,
        rng=random.Random(1),
        emit=lambda progress: None,
    )
    assert result.reason in ("no_face", "too_dark") and not result.ok
    bright = [
        __import__("tau_guard.camera", fromlist=["Frame"]).Frame(
            np.full((480, 640, 3), 200, np.uint8), 100.0 + i / 30
        )
        for i in range(10)
    ]
    result = run_check(
        Policy("recheck", 0.55, 0, timeout=5),
        [0.0] * 127 + [1.0],
        Calibration(1, 0.4, 0.4),
        engine,
        FakeFrameSource(bright),
        rng=random.Random(1),
        emit=lambda progress: None,
    )
    assert result.reason == "no_face"
    assert source.closed


def test_the_fake_engine_satisfies_the_protocol() -> None:
    assert isinstance(FakeEngine(), FaceEngine)


def fake_model(tmp_path: Path, content: bytes = b"not really an onnx file") -> tuple[Path, str]:
    path = tmp_path / "download" / "model.onnx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def test_model_file_installs_offline_with_its_checksum(tmp_path: Path) -> None:
    source, digest = fake_model(tmp_path)
    data = tmp_path / "data"
    installed = install_sface(data, source=source, expected=digest)
    assert installed == sface_path(data) and installed.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(os.stat(data / "guard").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(installed.parent).st_mode) == 0o700
    assert model_state(installed, digest) == "ok"
    assert model_state(installed, SFACE_SHA256) == "mismatch"
    assert model_state(tmp_path / "none", SFACE_SHA256) == "missing"


def test_a_wrong_checksum_is_refused_and_not_kept(tmp_path: Path) -> None:
    source, _ = fake_model(tmp_path)
    data = tmp_path / "data"
    with pytest.raises(ModelChecksumError) as caught:
        install_sface(data, source=source)
    assert SFACE_SHA256 in str(caught.value) and "not kept" in str(caught.value)
    models = sface_path(data).parent
    assert list(models.iterdir()) == []  # neither the file nor a partial download stays


def test_a_download_is_checked_the_same_way(tmp_path: Path) -> None:
    content = b"x" * 3_000_000
    digest = hashlib.sha256(content).hexdigest()
    seen: list[str] = []

    def opener(url: str, timeout: float) -> io.BytesIO:
        seen.append(url)
        return io.BytesIO(content)

    progress: list[int] = []
    data = tmp_path / "data"
    path = install_sface(data, expected=digest, opener=opener, progress=progress.append)
    assert seen == [SFACE_URL] and path.name == SFACE_FILE
    assert progress[-1] == len(content)
    tampered = tmp_path / "data2"
    with pytest.raises(ModelChecksumError):
        install_sface(tampered, opener=lambda url, timeout: io.BytesIO(b"evil"))
    assert list(sface_path(tampered).parent.iterdir()) == []
    with pytest.raises(ModelError):
        install_sface(tmp_path / "data3", url="http://example.invalid/model.onnx")


def test_the_pinned_url_points_at_one_opencv_zoo_commit() -> None:
    assert SFACE_URL.startswith("https://media.githubusercontent.com/media/opencv/opencv_zoo/")
    assert "/47534e27c9851bb1128ccc0102f1145e27f23f98/" in SFACE_URL
    assert SFACE_URL.endswith("/face_recognition_sface/face_recognition_sface_2021dec.onnx")
