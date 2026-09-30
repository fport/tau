"""Packaging rules: entry points, the public API, the message table, privacy of definitions."""

from __future__ import annotations

import re
import subprocess
from importlib import metadata
from pathlib import Path

import pytest
import tau_sub
from tau_core import Config
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_sub import SubRegistry, parse, tool_catalog
from tau_sub.strings import SUB_MESSAGES

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]


def test_entry_points() -> None:
    points = {(ep.group, ep.name): ep.value for ep in metadata.distribution("tau-sub").entry_points}
    assert points == {
        ("tau.commands", "sub"): "tau_sub.cli:sub",
        ("tau.tools", "sub"): "tau_sub.tools:TOOLS",
        ("tau.subs", "sub"): "tau_sub.network:public_subs",
    }
    assert metadata.version("tau-sub") == tau_sub.__version__


def test_the_tau_command_mounts_sub() -> None:
    from click.testing import CliRunner
    from tau_core.cli import cli

    result = CliRunner().invoke(cli, ["sub", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("new", "list", "show", "edit", "remove", "chat", "ask"):
        assert command in result.output


def test_public_api_is_explicit() -> None:
    assert sorted(tau_sub.__all__) == sorted(set(tau_sub.__all__))
    for name in tau_sub.__all__:
        assert hasattr(tau_sub, name), name


def test_every_message_has_both_languages() -> None:
    for key, templates in SUB_MESSAGES.items():
        assert key.startswith("sub."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    for path in Path(tau_sub.__file__).parent.glob("*.py"):
        if path.name == "strings.py":
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


def test_definitions_are_gitignored() -> None:
    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "persona/subs/coach.md"], cwd=ROOT, timeout=30
        ).returncode
        tracked = subprocess.run(
            ["git", "ls-files", "persona/subs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")
    if tracked.returncode != 0:
        pytest.skip("not a git checkout")
    assert ignored == 0
    assert tracked.stdout.split() == []


def test_the_example_is_valid_and_holds_nothing_personal(config: Config) -> None:
    path = PACKAGE / "examples" / "coach.md"
    text = path.read_text(encoding="utf-8")
    example = parse("coach", text, catalog=tool_catalog(config))
    assert example.tools == ("current_time",) and example.public is False
    assert "made-up content" in text
    assert "@" not in text and "http" not in text and "/Users/" not in text
    # it works as a definition once copied into persona/subs/
    registry = SubRegistry(config)
    registry.directory.mkdir(parents=True)
    (registry.directory / "coach.md").write_text(text, encoding="utf-8")
    assert registry.get("coach") == example
