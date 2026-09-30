"""Opt-in tests with the real models (``uv run pytest -m models packages/tau-guard``).

Skipped by default and in CI. They need SFace and a few public-domain portraits (official US
government photos from the ``ageitgey/face_recognition`` repository), fetched by pinned URL and
checked by sha256 into a cache outside the repo:

- ``TAU_GUARD_TEST_CACHE``: the cache directory (default ``~/.cache/tau-guard-tests``);
- ``TAU_GUARD_SFACE``: a local SFace file to install instead of downloading it (the same sha256
  check as ``tau guard setup --model-file``).

No face image is ever written into the repository, and LFW is never used.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tau_guard.camera import Frame
from tau_guard.engine import (
    SFACE_FILE,
    SFACE_SHA256,
    SFACE_URL,
    OpenCvFaceEngine,
    cosine,
    install_sface,
    mean_vector,
    sface_path,
)
from tau_guard.liveness import Calibration
from tau_guard.testing import FakeFrameSource
from tau_guard.verify import (
    STEP_UP_THRESHOLD,
    UNLOCK_THRESHOLD,
    Policy,
    counts_as_second,
    observe,
    run_check,
)

pytestmark = pytest.mark.models

COMMIT = "9f3061aaeed9a8756d2c970f5dfe066617a8281d"
BASE = f"https://raw.githubusercontent.com/ageitgey/face_recognition/{COMMIT}/"
IMAGES = {
    "obama": (
        "examples/obama.jpg",
        "0930e3aa8cae5920329c0c8cbc6a2ab70f47b0e67b432875beaa95cbf7e741f6",
    ),
    "obama2": (
        "examples/obama2.jpg",
        "a7efcc907375274796f39646510704aa86672d59f6d5469d69af3c85590976a6",
    ),
    "obama3": (
        "tests/test_images/obama3.jpg",
        "76ac6bf97c36dc2da0ad16a537d6a5ac1b10f48d49aac29a0cca9a17cdbc3ca3",
    ),
    "biden": (
        "examples/biden.jpg",
        "3c17508bb91554c637a2eabddfae790e5bb1caba93130814fc2ac50be9760c4c",
    ),
}
"""Official portraits (US government works, public domain), pinned to one commit."""
REPO = Path(__file__).resolve().parents[3]


def cache_dir() -> Path:
    root = Path(os.environ.get("TAU_GUARD_TEST_CACHE") or "~/.cache/tau-guard-tests").expanduser()
    root = root.resolve()
    assert REPO not in root.parents and root != REPO, "the model cache must be outside the repo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def fetch(url: str, sha256: str, target: Path) -> Path:
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
        return target
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (pinned https)
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    assert actual == sha256, f"{url}: sha256 {actual} is not the pinned {sha256}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> OpenCvFaceEngine:
    data_dir = tmp_path_factory.mktemp("data")
    local = os.environ.get("TAU_GUARD_SFACE")
    source = Path(local) if local else fetch(SFACE_URL, SFACE_SHA256, cache_dir() / SFACE_FILE)
    installed = install_sface(data_dir, source=source)
    assert installed == sface_path(data_dir)
    return OpenCvFaceEngine(installed)


@pytest.fixture(scope="module")
def images() -> dict[str, Any]:
    import cv2

    loaded = {}
    for name, (path, sha) in IMAGES.items():
        file = fetch(BASE + path, sha, cache_dir() / "portraits" / Path(path).name)
        image = cv2.imread(str(file))
        assert image is not None, name
        loaded[name] = fit(image)
    return loaded


def fit(image: Any, width: int = 640) -> Any:
    import cv2

    height = int(image.shape[0] * width / image.shape[1])
    return cv2.resize(image, (width, height))


def embedding(engine: OpenCvFaceEngine, image: Any) -> tuple[float, ...]:
    obs = observe(engine, image, 0.0)
    assert obs.quality and obs.embedding is not None, "no quality face in the portrait"
    return obs.embedding


def test_genuine_and_impostor_cosines_fall_on_the_right_sides(
    engine: OpenCvFaceEngine, images: dict[str, Any]
) -> None:
    owner = {name: embedding(engine, images[name]) for name in ("obama", "obama2", "obama3")}
    template = mean_vector([owner["obama"], owner["obama2"]])
    genuine = cosine(owner["obama3"], template)
    impostor = cosine(embedding(engine, images["biden"]), template)
    print(f"\ngenuine {genuine:.3f}  impostor {impostor:.3f}")
    assert genuine >= UNLOCK_THRESHOLD
    assert impostor < UNLOCK_THRESHOLD and impostor < STEP_UP_THRESHOLD
    pair = cosine(owner["obama"], owner["obama3"])
    assert pair >= 0.45 and abs(math.fsum(v * v for v in template) - 1) < 1e-9


def warp_frames(
    image: Any, kind: str, *, fps: float = 30.0, seconds: float = 12.0
) -> Iterator[Frame]:
    """A still held up to the camera: frontal for a second, then turned about the vertical
    axis again and again (``scale``: x squeezed around the face; ``perspective``: one side
    farther away), as someone rotating a printed photo or a phone would."""
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    canvas_w, canvas_h = 960, max(720, height + 40)
    for index in range(int(seconds * fps)):
        t = index / fps
        angle = 0.0 if t < 1.0 else 40.0 * math.sin((t - 1.0) * math.pi / 1.2)
        squeeze = math.cos(math.radians(angle))
        canvas = np.full((canvas_h, canvas_w, 3), 90, np.uint8)
        x0, y0 = (canvas_w - width) // 2, (canvas_h - height) // 2
        if kind == "scale":
            new_w = max(8, int(width * squeeze))
            squeezed = cv2.resize(image, (new_w, height))
            left = x0 + (width - new_w) // 2
            canvas[y0 : y0 + height, left : left + new_w] = squeezed
        else:
            near = 0.12 * math.sin(math.radians(angle))
            src = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
            dx = width * (1 - squeeze) / 2
            dst = np.float32(
                [
                    [x0 + dx, y0 + height * max(0.0, near)],
                    [x0 + width - dx, y0 + height * max(0.0, -near)],
                    [x0 + width - dx, y0 + height * (1 - max(0.0, -near))],
                    [x0 + dx, y0 + height * (1 - max(0.0, near))],
                ]
            )
            matrix = cv2.getPerspectiveTransform(src, dst)
            canvas = cv2.warpPerspective(
                image, matrix, (canvas_w, canvas_h), dst=canvas, borderMode=cv2.BORDER_TRANSPARENT
            )
        yield Frame(canvas, 100.0 + t)


@pytest.mark.parametrize("kind", ["scale", "perspective"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_turned_still_fails_the_challenge(
    engine: OpenCvFaceEngine, images: dict[str, Any], kind: str, seed: int
) -> None:
    template = mean_vector(
        [embedding(engine, images["obama"]), embedding(engine, images["obama2"])]
    )
    yaws: list[float] = []

    def explain(obs: Any, phase: str, machine: Any) -> None:
        if obs.primary is not None:
            yaws.append(obs.primary.yaw)

    result = run_check(
        Policy("unlock", UNLOCK_THRESHOLD, 2),
        template,
        Calibration(1, 0.45, 0.45),
        engine,
        FakeFrameSource(lambda: warp_frames(images["obama"], kind)),
        rng=random.Random(seed),
        emit=lambda progress: None,
        explain=explain,
    )
    spread = max(yaws) - min(yaws) if yaws else 0.0
    print(f"\n{kind} seed {seed}: {result.reason}; yaw proxy spread {spread:.3f}")
    assert not result.ok and result.reason == "spoof"


def face_patch(engine: OpenCvFaceEngine, image: Any, iod: float) -> Any:
    """The portrait's face, cropped with a margin and scaled to eye distance ``iod``."""
    import cv2

    face = max(engine.detect(image), key=lambda f: f.iod)
    scale = iod / face.iod
    cx, cy = face.x + face.w / 2, face.y + face.h / 2
    half = max(face.w, face.h)
    top, left = max(0, int(cy - half)), max(0, int(cx - half))
    crop = image[top : int(cy + half), left : int(cx + half)]
    return cv2.resize(
        crop, (max(8, int(crop.shape[1] * scale)), max(8, int(crop.shape[0] * scale)))
    )


def test_a_two_face_composite_counts_the_second_face_only_when_it_is_large(
    engine: OpenCvFaceEngine, images: dict[str, Any]
) -> None:
    import numpy as np

    owner = face_patch(engine, images["obama"], 100.0)
    seen: list[tuple[float, float, bool]] = []
    for share in (0.25, 0.35, 0.5, 0.7, 0.9):
        other = face_patch(engine, images["biden"], 100.0 * share)
        canvas = np.full((720, 1280, 3), 110, np.uint8)
        canvas[40 : 40 + owner.shape[0], 60 : 60 + owner.shape[1]] = owner
        h, w = other.shape[:2]
        canvas[80 : 80 + h, 1200 - w : 1200] = other
        obs = observe(engine, canvas, 0.0)
        faces = sorted(engine.detect(canvas), key=lambda face: face.iod, reverse=True)
        assert faces, share
        primary = faces[0]
        second = faces[1] if len(faces) > 1 else None
        expected = second is not None and counts_as_second(primary, second)
        assert obs.crowd is expected
        seen.append((share, second.iod / primary.iod if second else 0.0, obs.crowd))
    print("\n" + "  ".join(f"{s:.2f}: {r:.2f} {'crowd' if c else 'ignored'}" for s, r, c in seen))
    assert not seen[0][2] and seen[-1][2]  # the smallest is ignored, the largest counts
