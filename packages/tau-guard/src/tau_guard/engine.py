"""The face engine (ADR 0008 decision 12): YuNet finds faces, SFace turns a face into an embedding.

- **Detector.** YuNet 2023mar fp32 (MIT, 232 KB) ships in the wheel as
  ``tau_guard/models/face_detection_yunet_2023mar.onnx`` with ``LICENSE-yunet``. Its sha256 is
  checked every time it is loaded; a changed file refuses to load.
- **Recognizer.** SFace 2021dec fp32 (Apache-2.0, 38.7 MB) is not in the wheel. ``tau guard
  setup`` downloads it from :data:`SFACE_URL`, pinned to one opencv_zoo commit, or installs it
  offline from ``--model-file PATH`` (:func:`install_sface`), into
  ``TAU_DATA_DIR/guard/models/``. A file whose sha256 is not :data:`SFACE_SHA256` is refused and
  never kept, and its sha256 is checked again at every load.
- **Embeddings** are L2-normalised 128-d vectors and are compared by cosine similarity, which
  for unit vectors is the dot product (:func:`cosine`).

:class:`Face` is one YuNet row (box, five landmarks, score) with the geometry the checks use:
the eye distance (:attr:`Face.iod`) and the yaw proxy (:attr:`Face.yaw`,
``(nose_x - eye_mid_x) / iod``). :class:`FaceEngine` is the seam: :class:`OpenCvFaceEngine` is
the real one, and tests pass a fake that returns synthetic YuNet rows and embeddings.

Nothing here imports cv2 or numpy at module level; :func:`import_cv2` sets
``OPENCV_LOG_LEVEL=ERROR`` and ``OPENCV_AVFOUNDATION_SKIP_AUTH=1`` before the first import, so
no OpenCV output reaches a terminal and OpenCV never asks for camera access itself.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import IO, Any, Protocol, runtime_checkable

__all__ = [
    "DETECT_THRESHOLD",
    "EMBEDDING_DIM",
    "SFACE_FILE",
    "SFACE_NAME",
    "SFACE_SHA256",
    "SFACE_URL",
    "YUNET_FILE",
    "YUNET_SHA256",
    "Face",
    "FaceEngine",
    "ModelChecksumError",
    "ModelError",
    "OpenCvFaceEngine",
    "cosine",
    "file_sha256",
    "import_cv2",
    "install_sface",
    "iou",
    "mean_vector",
    "model_state",
    "normalise",
    "sface_path",
    "vendored_yunet",
]

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
SFACE_NAME = "sface-2021dec"
SFACE_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    "47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/"
    "face_recognition_sface_2021dec.onnx"
)
MODELS_DIR = "models"
"""Under ``TAU_DATA_DIR/guard/``."""
MAX_MODEL_BYTES = 64 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60.0
CHUNK = 1024 * 1024

DETECT_THRESHOLD = 0.75
"""YuNet's own score threshold: the lowest gate any frame uses (challenge frames). Identity
frames need 0.90 (:mod:`tau_guard.verify`)."""
NMS_THRESHOLD = 0.3
TOP_K = 50
EMBEDDING_DIM = 128
CV2_ENV = {"OPENCV_LOG_LEVEL": "ERROR", "OPENCV_AVFOUNDATION_SKIP_AUTH": "1"}


def import_cv2() -> Any:
    """``cv2``, imported after the environment that keeps OpenCV quiet and away from TCC."""
    os.environ.update(CV2_ENV)
    import cv2  # type: ignore[import-not-found]

    return cv2


# -- geometry --------------------------------------------------------------------------------------


Point = tuple[float, float]


@dataclass(frozen=True)
class Face:
    """One YuNet detection: ``[x, y, w, h, re_x, re_y, le_x, le_y, nose_x, nose_y, mouth_r_x,
    mouth_r_y, mouth_l_x, mouth_l_y, score]`` in frame pixels."""

    x: float
    y: float
    w: float
    h: float
    right_eye: Point
    left_eye: Point
    nose: Point
    mouth_right: Point
    mouth_left: Point
    score: float

    @classmethod
    def from_row(cls, row: Sequence[float]) -> Face:
        """A face from a YuNet row; raises ``ValueError`` for a short or non-finite row."""
        values = [float(value) for value in list(row)[:15]]
        if len(values) < 15 or not all(math.isfinite(value) for value in values):
            raise ValueError("a YuNet row has 15 finite numbers")
        v = values
        return cls(
            v[0], v[1], v[2], v[3], (v[4], v[5]), (v[6], v[7]), (v[8], v[9]), (v[10], v[11]),
            (v[12], v[13]), v[14],
        )  # fmt: skip

    def row(self) -> list[float]:
        """The YuNet row again (SFace's ``alignCrop`` takes it)."""
        return [
            self.x, self.y, self.w, self.h, *self.right_eye, *self.left_eye, *self.nose,
            *self.mouth_right, *self.mouth_left, self.score,
        ]  # fmt: skip

    @property
    def iod(self) -> float:
        """The eye distance in pixels."""
        return math.dist(self.right_eye, self.left_eye)

    @property
    def yaw(self) -> float:
        """The yaw proxy ``(nose_x - eye_mid_x) / iod``: a real head turn moves the nose out of
        the eyes' plane and changes it; a flat photo turned about the vertical axis scales every
        x distance alike and leaves it unchanged."""
        iod = self.iod
        if iod <= 1e-6:
            return 0.0
        return (self.nose[0] - (self.right_eye[0] + self.left_eye[0]) / 2) / iod

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)


def iou(a: Face, b: Face) -> float:
    """The intersection over union of two face boxes."""
    left, top = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


# -- vectors ---------------------------------------------------------------------------------------


def normalise(vector: Iterable[float]) -> tuple[float, ...]:
    """``vector`` scaled to length 1; raises ``ValueError`` for a zero or non-finite vector."""
    values = tuple(float(value) for value in vector)
    norm = math.sqrt(math.fsum(value * value for value in values))
    if not values or not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError("an embedding must be a non-zero finite vector")
    return tuple(value / norm for value in values)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two unit vectors (their dot product)."""
    if len(a) != len(b):
        raise ValueError("vectors of different length")
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def mean_vector(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """The renormalised mean of unit vectors (a template)."""
    if not vectors:
        raise ValueError("no vectors")
    size = len(vectors[0])
    sums = [math.fsum(vector[i] for vector in vectors) for i in range(size)]
    return normalise(sums)


# -- model files -----------------------------------------------------------------------------------


class ModelError(Exception):
    """A model file is missing, has the wrong checksum or could not be fetched.

    ``reason`` is ``missing``, ``checksum`` or ``download``; the message is plain English."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class ModelChecksumError(ModelError):
    """A model file whose sha256 is not the pinned one; it was not kept."""

    def __init__(self, name: str, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            "checksum",
            f"{name}: sha256 {actual} does not match the pinned {expected}; the file was not kept",
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vendored_yunet() -> Path:
    """The YuNet file inside the installed package."""
    return Path(str(resources.files("tau_guard") / MODELS_DIR / YUNET_FILE))


def sface_path(data_dir: Path) -> Path:
    """Where ``tau guard setup`` puts SFace: ``TAU_DATA_DIR/guard/models/<file>``."""
    return Path(data_dir) / "guard" / MODELS_DIR / SFACE_FILE


def model_state(path: Path, expected: str) -> str:
    """``ok``, ``missing`` or ``mismatch`` (a file whose sha256 is not ``expected``)."""
    try:
        actual = file_sha256(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "missing"
    return "ok" if actual == expected else "mismatch"


def checked(path: Path, expected: str, name: str) -> Path:
    """``path`` when its sha256 is ``expected``; raises :class:`ModelError` otherwise."""
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise ModelError("missing", f"{name}: {path} cannot be read ({exc})") from exc
    if actual != expected:
        raise ModelChecksumError(name, expected, actual)
    return Path(path)


def _secure(directory: Path) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def install_sface(
    data_dir: Path,
    *,
    source: Path | None = None,
    url: str = SFACE_URL,
    expected: str = SFACE_SHA256,
    opener: Callable[[str, float], IO[bytes]] | None = None,
    progress: Callable[[int], None] | None = None,
) -> Path:
    """Put SFace into ``TAU_DATA_DIR/guard/models/`` and return its path.

    ``source`` copies a local file (``--model-file``, offline); otherwise the file is fetched
    from ``url``. Either way it is written to a temporary file next to the target while its
    sha256 is computed, and renamed into place only when the checksum is ``expected``; a
    mismatch raises :class:`ModelChecksumError` and deletes the temporary file, so a bad file
    is never kept. ``progress(bytes_so_far)`` is called after every chunk."""
    guard = _secure(Path(data_dir) / "guard")
    models = _secure(guard / MODELS_DIR)
    target = models / SFACE_FILE
    fd, tmp_name = tempfile.mkstemp(prefix=f".{SFACE_FILE}.", suffix=".part", dir=models)
    tmp = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as out:
            try:
                stream = source.open("rb") if source is not None else _open(url, opener)
            except OSError as exc:
                where = str(source) if source is not None else url
                raise ModelError("download", f"SFace: {where} cannot be read ({exc})") from exc
            with stream:
                while True:
                    try:
                        chunk = stream.read(CHUNK)
                    except OSError as exc:
                        message = f"SFace: the download broke off ({exc})"
                        raise ModelError("download", message) from exc
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_MODEL_BYTES:
                        raise ModelError("download", "SFace: the file is far larger than expected")
                    digest.update(chunk)
                    out.write(chunk)
                    if progress is not None:
                        progress(size)
        actual = digest.hexdigest()
        if actual != expected:
            raise ModelChecksumError("SFace", expected, actual)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def _open(url: str, opener: Callable[[str, float], IO[bytes]] | None) -> IO[bytes]:
    if not url.startswith("https://"):
        raise ModelError("download", "SFace: the model URL must use https")
    if opener is not None:
        return opener(url, DOWNLOAD_TIMEOUT)
    return urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT)  # noqa: S310 (https only)


# -- the engine ------------------------------------------------------------------------------------


@runtime_checkable
class FaceEngine(Protocol):
    """What the checks need from a face engine. ``frame`` is whatever the frame source yields
    (a BGR image for the camera); ``crop`` is whatever :meth:`crop` returns."""

    model_sha256: str | None
    """The recognizer's sha256 (it binds the template), ``None`` without a recognizer."""

    def detect(self, frame: Any) -> list[Face]: ...

    def brightness(self, frame: Any, face: Face | None) -> float:
        """Mean grey level (0-255) of the face's box, or of the whole frame without a face."""
        ...

    def crop(self, frame: Any, face: Face) -> Any:
        """The aligned 112x112 face."""
        ...

    def sharpness(self, crop: Any) -> float:
        """Variance of the Laplacian of the aligned face."""
        ...

    def embed(self, crop: Any) -> tuple[float, ...]:
        """The L2-normalised embedding of the aligned face."""
        ...


class OpenCvFaceEngine:
    """YuNet and SFace through ``cv2.FaceDetectorYN`` and ``cv2.FaceRecognizerSF``.

    Both files are sha256-checked before OpenCV sees them. ``sface=None`` gives a detector
    only (``crop``, ``sharpness`` and ``embed`` then raise :class:`ModelError`)."""

    def __init__(self, sface: Path | None, *, yunet: Path | None = None) -> None:
        yunet_path = checked(yunet or vendored_yunet(), YUNET_SHA256, "YuNet")
        sface_file = checked(sface, SFACE_SHA256, "SFace") if sface is not None else None
        cv2 = import_cv2()
        self._cv2 = cv2
        self._size = (320, 320)
        self._detector = cv2.FaceDetectorYN.create(
            str(yunet_path), "", self._size, DETECT_THRESHOLD, NMS_THRESHOLD, TOP_K
        )
        self._recognizer = (
            cv2.FaceRecognizerSF.create(str(sface_file), "") if sface_file is not None else None
        )
        self.model_sha256: str | None = SFACE_SHA256 if sface_file is not None else None

    def detect(self, frame: Any) -> list[Face]:
        height, width = frame.shape[:2]
        if (width, height) != self._size:
            self._detector.setInputSize((width, height))
            self._size = (width, height)
        _, rows = self._detector.detect(frame)
        if rows is None:
            return []
        faces = []
        for row in rows.tolist():
            try:
                faces.append(Face.from_row(row))
            except ValueError:
                continue
        return faces

    def _gray(self, image: Any) -> Any:
        cv2 = self._cv2
        if getattr(image, "ndim", 2) == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image

    def brightness(self, frame: Any, face: Face | None) -> float:
        gray = self._gray(frame)
        if face is not None:
            height, width = gray.shape[:2]
            left, top = max(0, int(face.x)), max(0, int(face.y))
            right, bottom = min(width, int(face.x + face.w)), min(height, int(face.y + face.h))
            if right > left and bottom > top:
                return float(gray[top:bottom, left:right].mean())
        return float(gray.mean())

    def _need_recognizer(self) -> Any:
        if self._recognizer is None:
            raise ModelError("missing", "SFace is not loaded")
        return self._recognizer

    def crop(self, frame: Any, face: Face) -> Any:
        import numpy as np  # type: ignore[import-not-found]

        row = np.array(face.row(), dtype=np.float32)
        return self._need_recognizer().alignCrop(frame, row)

    def sharpness(self, crop: Any) -> float:
        cv2 = self._cv2
        return float(cv2.Laplacian(self._gray(crop), cv2.CV_64F).var())

    def embed(self, crop: Any) -> tuple[float, ...]:
        feature = self._need_recognizer().feature(crop)
        return normalise(feature.reshape(-1).tolist())
