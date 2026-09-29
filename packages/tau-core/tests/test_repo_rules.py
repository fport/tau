"""Repository rules that must never regress (CLAUDE.md non-negotiables)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"


def _source_files() -> list[Path]:
    return [p for p in PACKAGES.glob("*/src/**/*") if p.is_file() and "__pycache__" not in p.parts]


def test_repo_root_found() -> None:
    assert (ROOT / "pyproject.toml").is_file()
    assert (PACKAGES / "tau-core").is_dir()


def test_no_model_ids_in_code() -> None:
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "claude-" in text or "anthropic.claude" in text:
            offenders.append(path.relative_to(ROOT))
    assert offenders == [], f"model ids belong in tau.toml, not code: {offenders}"


def test_no_litellm_dependency() -> None:
    files = list(ROOT.glob("pyproject.toml")) + list(PACKAGES.glob("**/pyproject.toml"))
    files += [ROOT / "uv.lock"] if (ROOT / "uv.lock").is_file() else []
    offenders = [
        p.relative_to(ROOT) for p in files if "litellm" in p.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], f"litellm must never be a Python dependency: {offenders}"


def test_no_auto_approve() -> None:
    offenders = [
        p.relative_to(ROOT)
        for p in _source_files()
        if "AutoApprove" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], f"tier-2 approval is never bypassed: {offenders}"


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [ROOT / name for name in out.decode().split("\0") if name]


def test_no_personal_paths_in_tracked_files() -> None:
    home_path = re.compile("/" + "Users/[A-Za-z0-9_.-]+|/" + "home/[a-z][a-z0-9_-]+/")
    offenders = []
    for path in _tracked_files():
        if path.name == "uv.lock" or not path.is_file() or path.suffix in {".png", ".jpg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if home_path.search(text):
            offenders.append(path.relative_to(ROOT))
    assert offenders == [], f"absolute personal paths in tracked files: {offenders}"
