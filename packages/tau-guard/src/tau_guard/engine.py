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

:class:`Face` is one YuNet row (box, five landmarks, score, and the size of the frame it came
from) with the geometry the checks use: the eye distance (:attr:`Face.iod`) and the head pose
(:attr:`Face.pose`: yaw and pitch in degrees, see :func:`head_pose`). :class:`FaceEngine` is
the seam: :class:`OpenCvFaceEngine` is the real one, and tests pass a fake that returns
synthetic YuNet rows and embeddings.

**Head pose** (issue 127). ``cv2.solvePnP`` fits the five landmarks to a generic head,
:data:`HEAD_MODEL`, seen by a pinhole camera with the focal length equal to the frame width and
the principal point in the middle of the frame (``SOLVEPNP_ITERATIVE``, started from a frontal
pose at the distance the eye distance implies). The yaw is positive when the face turns toward
the image's right edge (the nose moves right of the eyes: the sign of the old yaw proxy
``(nose_x - eye_mid_x) / eye distance``, so a calibration sign stored with the proxy still holds).
:attr:`HeadPose.fit` is the root mean square reprojection error in eye distances: a flat picture
turned about the vertical axis only squeezes its landmarks, which then stop fitting a head.

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
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import IO, Any, Protocol, runtime_checkable

__all__ = [
    "DETECT_THRESHOLD",
    "EMBEDDING_DIM",
    "FRAME_SIZE",
    "HEAD_MODEL",
    "SFACE_FILE",
    "SFACE_NAME",
    "SFACE_SHA256",
    "SFACE_URL",
    "YUNET_FILE",
    "YUNET_SHA256",
    "Face",
    "FaceEngine",
    "HeadPose",
    "ModelChecksumError",
    "ModelError",
    "OpenCvFaceEngine",
    "cosine",
    "file_sha256",
    "head_pose",
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
Point3 = tuple[float, float, float]

FRAME_SIZE = (640, 480)
"""The camera's frame size (:mod:`tau_guard.camera`); a :class:`Face` without a ``size`` is
taken to come from such a frame."""

HEAD_MODEL: tuple[Point3, ...] = (
    (-32.0, -37.0, 38.0),  # right eye centre (the subject's right: the image's left)
    (32.0, -37.0, 38.0),  # left eye centre
    (0.0, 0.0, 0.0),  # nose tip
    (-28.0, 28.0, 32.0),  # right mouth corner
    (28.0, 28.0, 32.0),  # left mouth corner
)
"""A generic adult head: YuNet's five landmarks in millimetres, in YuNet's row order, with the
nose tip at the origin and the axes of the camera looking at a frontal face (x toward the
image's right edge, y down, z away from the camera).

- **x and y** are the median layout of YuNet 2023mar's own landmarks on frontal portraits,
  scaled to a 64 mm eye distance: the eyes 37 mm above the nose tip, the mouth corners 28 mm
  below it and 56 mm apart (a frontal face fits the model; anthropometric means are an
  interpupillary distance of about 63 mm and a mouth width of 50-54 mm).
- **z** comes from MediaPipe's metric canonical face model (``canonical_face_model.obj``,
  Apache-2.0): the eye centres (the mean of each eye's contour) lie 38 mm and the mouth corners
  (landmarks 61 and 291) 32 mm behind the nose tip (landmark 1).

Checked against MediaPipe's own head pose (its 468-point mesh) on 18 real faces: the yaw from
this model agrees with a slope of 1.02 and a correlation of 0.83."""


@dataclass(frozen=True)
class HeadPose:
    """The head's orientation from :func:`head_pose`: ``yaw`` (positive: the face turns toward
    the image's right edge) and ``pitch`` (positive: up) in degrees, and ``fit``, the root mean
    square reprojection error of the five landmarks divided by the eye distance (``inf`` when
    there is no pose)."""

    yaw: float
    pitch: float
    fit: float

    def fits(self, limit: float) -> bool:
        """The landmarks fit a head within ``limit`` eye distances."""
        return self.fit <= limit


NO_POSE = HeadPose(0.0, 0.0, math.inf)


@dataclass(frozen=True)
class Face:
    """One YuNet detection: ``[x, y, w, h, re_x, re_y, le_x, le_y, nose_x, nose_y, mouth_r_x,
    mouth_r_y, mouth_l_x, mouth_l_y, score]`` in frame pixels, and the ``size`` (width, height)
    of the frame it was found in (``None``: :data:`FRAME_SIZE`)."""

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
    size: tuple[int, int] | None = None

    @classmethod
    def from_row(cls, row: Sequence[float], *, size: tuple[int, int] | None = None) -> Face:
        """A face from a YuNet row; raises ``ValueError`` for a short or non-finite row."""
        values = [float(value) for value in list(row)[:15]]
        if len(values) < 15 or not all(math.isfinite(value) for value in values):
            raise ValueError("a YuNet row has 15 finite numbers")
        v = values
        return cls(
            v[0], v[1], v[2], v[3], (v[4], v[5]), (v[6], v[7]), (v[8], v[9]), (v[10], v[11]),
            (v[12], v[13]), v[14], size,
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
    def landmarks(self) -> tuple[Point, ...]:
        """The five landmarks in :data:`HEAD_MODEL`'s order."""
        return (self.right_eye, self.left_eye, self.nose, self.mouth_right, self.mouth_left)

    @cached_property
    def pose(self) -> HeadPose:
        """The head pose (:func:`head_pose`), computed once per face."""
        return head_pose(self.landmarks, self.size or FRAME_SIZE)

    @property
    def yaw(self) -> float:
        """The head's yaw in degrees (:attr:`pose`)."""
        return self.pose.yaw

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)


def head_pose(landmarks: Sequence[Point], size: tuple[int, int]) -> HeadPose:
    """The pose of the head whose five landmarks (YuNet's order) were seen in a frame of
    ``size`` (width, height): ``cv2.solvePnP`` against :data:`HEAD_MODEL`, the camera's focal
    length equal to the width and its principal point in the middle of the frame. The fit starts
    from a frontal head at the distance the eye distance implies (``SOLVEPNP_ITERATIVE`` with
    that guess; EPnP is too noisy on five points). A degenerate face or a failed fit gives a
    pose whose ``fit`` is infinite."""
    points = [(float(x), float(y)) for x, y in landmarks]
    width, height = float(size[0]), float(size[1])
    if len(points) != 5 or width <= 0 or height <= 0:
        return NO_POSE
    iod = math.dist(points[0], points[1])
    if iod <= 1e-6:
        return NO_POSE
    cv2 = import_cv2()
    import numpy as np  # type: ignore[import-not-found]

    model = np.array(HEAD_MODEL, dtype=np.float64)
    image = np.array(points, dtype=np.float64).reshape(-1, 1, 2)
    focal, cx, cy = width, width / 2, height / 2
    camera = np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]])
    eyes = focal * math.dist(HEAD_MODEL[0][:2], HEAD_MODEL[1][:2]) / iod
    distance = max(eyes - HEAD_MODEL[0][2], eyes / 2)  # the nose tip's, for a frontal head
    nose_x, nose_y = points[2]
    rvec = np.zeros((3, 1))
    tvec = np.array([[(nose_x - cx) * distance / focal], [(nose_y - cy) * distance / focal]])
    tvec = np.vstack([tvec, [[distance]]])
    try:
        ok, rvec, tvec = cv2.solvePnP(
            model, image, camera, None, rvec, tvec, True, cv2.SOLVEPNP_ITERATIVE
        )
    except cv2.error:
        return NO_POSE
    if not ok or not np.all(np.isfinite(rvec)) or not np.all(np.isfinite(tvec)):
        return NO_POSE
    projected, _ = cv2.projectPoints(model, rvec, tvec, camera, None)
    error = projected.reshape(-1, 2) - image.reshape(-1, 2)
    fit = math.sqrt(float((error**2).sum(axis=1).mean())) / iod
    rotation, _ = cv2.Rodrigues(rvec)
    forward = -rotation[:, 2]  # where the face looks (the model's -z), in camera coordinates
    yaw = math.degrees(math.atan2(float(forward[0]), float(-forward[2])))
    pitch = math.degrees(math.atan2(float(-forward[1]), math.hypot(forward[0], forward[2])))
    if not all(math.isfinite(value) for value in (yaw, pitch, fit)):
        return NO_POSE
    return HeadPose(yaw, pitch, fit)


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
                faces.append(Face.from_row(row, size=(width, height)))
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
