"""Packaging rules: entry points, the public API, lazy camera imports, the message table."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import tau_guard
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_guard.strings import CLI_MESSAGES

PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE / "src" / "tau_guard"
ROOT = PACKAGE.parents[1]
LAZY_ONLY = {"cv2", "objc", "Quartz", "AVFoundation", "LocalAuthentication", "keyring", "numpy"}


def test_entry_points() -> None:
    points = {
        (ep.group, ep.name): ep.value for ep in metadata.distribution("tau-guard").entry_points
    }
    assert points == {
        ("tau.commands", "guard"): "tau_guard.cli:guard",
        ("tau.hub_services", "guard"): "tau_guard.service:make_service",
    }
    assert metadata.version("tau-guard") == tau_guard.__version__


def test_the_version_moves_in_lockstep_with_tau_core() -> None:
    core = tomllib.loads((ROOT / "packages/tau-core/pyproject.toml").read_text())
    mine = tomllib.loads((PACKAGE / "pyproject.toml").read_text())
    assert mine["project"]["version"] == core["project"]["version"]


def test_dependencies_follow_adr_0008() -> None:
    deps = tomllib.loads((PACKAGE / "pyproject.toml").read_text())["project"]["dependencies"]
    names = {re.split(r"[<>=;\s]", dep, maxsplit=1)[0].lower(): dep for dep in deps}
    assert {"tau-core", "numpy", "opencv-python-headless", "cryptography"} <= set(names)
    assert "<5" in names["opencv-python-headless"]
    for darwin_only in (
        "keyring",
        "pyobjc-framework-avfoundation",
        "pyobjc-framework-quartz",
        "pyobjc-framework-localauthentication",
    ):
        assert "sys_platform == 'darwin'" in names[darwin_only], darwin_only
    assert not any(
        name.startswith(("opencv-python", "opencv-contrib")) and name != "opencv-python-headless"
        for name in names
    )


def test_public_api_is_explicit() -> None:
    assert sorted(tau_guard.__all__) == sorted(set(tau_guard.__all__))
    for name in tau_guard.__all__:
        assert getattr(tau_guard, name) is not None, name


def test_camera_and_pyobjc_imports_are_lazy() -> None:
    """No module imports cv2, pyobjc, keyring or numpy at module level, so the package and its
    tests run on Linux CI and an inactive hub never loads them."""
    offenders = []
    for path in SOURCE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in LAZY_ONLY:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []


def test_importing_the_package_loads_no_camera_module() -> None:
    import subprocess

    code = (
        "import sys, tau_guard, tau_guard.service, tau_guard.cli, tau_guard.worker, "
        "tau_guard.cli_face, tau_guard.local, tau_guard.store, tau_guard.verify; "
        f"print(sorted(m for m in {sorted(LAZY_ONLY)!r} if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]", out.stderr


def test_the_worker_side_never_loads_tau_core() -> None:
    """The worker imports only what the face check needs: no tau-core, no strands."""
    import subprocess

    modules = "camera, engine, enroll, liveness, localauth, store, verify, worker"
    code = (
        f"import sys; from tau_guard import {modules}; "
        "print(sorted(m for m in ('tau_core', 'strands', 'cv2', 'numpy') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]", out.stderr


def test_the_wheel_ships_the_vendored_detector() -> None:
    project = tomllib.loads((PACKAGE / "pyproject.toml").read_text())
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/tau_guard"]
    models = SOURCE / "models"
    assert sorted(p.name for p in models.iterdir() if not p.name.startswith(".")) == [
        "LICENSE-yunet",
        "face_detection_yunet_2023mar.onnx",
    ]
    ignored = (ROOT / ".gitignore").read_text()
    assert "*.onnx" not in ignored and "models" not in ignored


def test_every_message_has_both_languages() -> None:
    for key, templates in CLI_MESSAGES.items():
        assert key.startswith("guard.cli."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_every_audit_event_has_a_label() -> None:
    from tau_guard.audit import EVENTS

    for event in EVENTS:
        assert f"guard.cli.log.event.{event}" in CLI_MESSAGES


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    for path in [*SOURCE.glob("*.py"), *(PACKAGE / "tests").glob("*.py"), PACKAGE / "README.md"]:
        if path.name in ("strings.py", "test_package.py"):  # the table, and this pattern
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


def test_the_package_ships_its_license_and_readme() -> None:
    assert "MIT License" in (PACKAGE / "LICENSE").read_text()
    readme = (PACKAGE / "README.md").read_text()
    assert "tau guard" in readme and "ADR 0008" in readme


def test_ci_and_release_build_the_package() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    release = (ROOT / ".github/workflows/release.yml").read_text()
    assert "uv build --package tau-guard" in ci
    assert "uv build --package tau-guard" in release
    assert "pypi-guard" in release
