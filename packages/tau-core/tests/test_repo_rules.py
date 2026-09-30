"""Repository rules that must never regress (CLAUDE.md non-negotiables)."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"


def _source_files() -> list[Path]:
    return [p for p in PACKAGES.glob("*/src/**/*") if p.is_file() and "__pycache__" not in p.parts]


def _code_files() -> list[Path]:
    """Source files minus package data: ``templates/`` holds ``tau init``'s tau.toml and the
    model-id table, which are data like the repository's own ``tau.toml``."""
    return [p for p in _source_files() if "templates" not in p.parts]


def test_repo_root_found() -> None:
    assert (ROOT / "pyproject.toml").is_file()
    assert (PACKAGES / "tau-core").is_dir()


def test_no_model_ids_in_code() -> None:
    offenders = []
    for path in _code_files():
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


# -- the owner guard (issue 110, ADR 0008) -----------------------------------------------------

GUARD_NONE_ALLOWED = {
    Path("packages/tau-core/src/tau_core/channels/telegram.py"),
    Path("packages/tau-net/src/tau_net/turns.py"),
}
"""The identified in-hub channels, the only code that may opt out of the guard."""


def _python_sources() -> list[tuple[Path, ast.Module]]:
    return [
        (path.relative_to(ROOT), ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in _source_files()
        if path.suffix == ".py"
    ]


def _calls(tree: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_only_identified_channels_opt_out_of_the_guard() -> None:
    found: set[Path] = set()
    for path, tree in _python_sources():
        for call in _calls(tree):
            for keyword in call.keywords:
                value = keyword.value
                if (
                    keyword.arg == "guard"
                    and isinstance(value, ast.Constant)
                    and value.value is None
                ):
                    found.add(path)
    assert found <= GUARD_NONE_ALLOWED, f"guard=None outside the allowlist: {found}"
    assert found == GUARD_NONE_ALLOWED, "an identified channel stopped opting out"


def test_every_tier_gate_decides_about_the_guard() -> None:
    offenders = []
    for path, tree in _python_sources():
        for call in _calls(tree):
            if _called_name(call) == "TierGate":
                if not any(keyword.arg == "guard" for keyword in call.keywords):
                    offenders.append(f"{path}:{call.lineno}")
    assert offenders == [], f"TierGate( without guard=: {offenders}"


def test_no_channel_flag_or_variable_selects_a_channel() -> None:
    offenders = [
        p.relative_to(ROOT)
        for p in _code_files()
        if p.suffix == ".py"
        and re.search(r"--channel\b|TAU_CHANNEL", p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"a channel is chosen by code, never by a flag: {offenders}"
