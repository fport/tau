"""Packaging rules: entry points, the public API, the message table, the build."""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import tau_routines
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_routines.strings import ROUTINE_MESSAGES

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]


def test_entry_points() -> None:
    points = {
        (ep.group, ep.name): ep.value for ep in metadata.distribution("tau-routines").entry_points
    }
    assert points == {
        ("tau.hub_services", "routines"): "tau_routines.service:make_service",
        ("tau.commands", "routine"): "tau_routines.cli:routine",
        ("tau.tools", "routines"): "tau_routines.tools:TOOLS",
    }
    assert metadata.version("tau-routines") == tau_routines.__version__ == "0.1.0"


def test_the_tau_command_mounts_routine() -> None:
    from click.testing import CliRunner
    from tau_core.cli import cli

    result = CliRunner().invoke(cli, ["routine", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("add", "edit", "list", "pause", "resume", "remove", "log"):
        assert command in result.output


def test_public_api_is_explicit() -> None:
    assert sorted(tau_routines.__all__) == sorted(set(tau_routines.__all__))
    for name in tau_routines.__all__:
        assert hasattr(tau_routines, name), name


def test_every_message_has_both_languages() -> None:
    for key, templates in ROUTINE_MESSAGES.items():
        assert key.startswith("routine."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    for path in Path(tau_routines.__file__).parent.glob("*.py"):
        if path.name == "strings.py":
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


def test_only_the_engine_mentions_a_guard_opt_out() -> None:
    """The AST rule is ``test_repo_rules.py`` in tau-core; this keeps the text honest too."""
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in Path(tau_routines.__file__).parent.glob("*.py")
    }
    assert [name for name, text in sources.items() if "guard=None" in text] == ["engine.py"]


def test_the_package_ships_its_license_and_readme() -> None:
    assert "MIT License" in (PACKAGE / "LICENSE").read_text(encoding="utf-8")
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    assert "tau routine add" in readme and "ADR 0015" in readme


def test_ci_builds_the_package() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv build --package tau-routines" in ci
    root = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"tau-routines"' in root and "tau-routines = { workspace = true }" in root
