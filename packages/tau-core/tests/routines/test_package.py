"""The routines component of tau-core: entry points, the public API, the message table."""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import tau_core.routines
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_core.routines.strings import ROUTINE_MESSAGES

PACKAGE = Path(__file__).resolve().parents[2]  # packages/tau-core


def test_entry_points() -> None:
    points = {
        (ep.group, ep.name): ep.value for ep in metadata.distribution("tau-core").entry_points
    }
    assert points[("tau.hub_services", "routines")] == "tau_core.routines.service:make_service"
    assert points[("tau.commands", "routine")] == "tau_core.routines.cli:routine"
    assert points[("tau.tools", "routines")] == "tau_core.routines.tools:TOOLS"


def test_the_tau_command_mounts_routine() -> None:
    from click.testing import CliRunner
    from tau_core.cli import cli

    result = CliRunner().invoke(cli, ["routine", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("add", "edit", "list", "pause", "resume", "remove", "log"):
        assert command in result.output


def test_public_api_is_explicit() -> None:
    assert sorted(tau_core.routines.__all__) == sorted(set(tau_core.routines.__all__))
    for name in tau_core.routines.__all__:
        assert hasattr(tau_core.routines, name), name


def test_every_message_has_both_languages() -> None:
    for key, templates in ROUTINE_MESSAGES.items():
        assert key.startswith("routine."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    for path in Path(tau_core.routines.__file__).parent.glob("*.py"):
        if path.name == "strings.py":
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


def test_only_the_engine_mentions_a_guard_opt_out() -> None:
    """The AST rule is ``test_repo_rules.py`` in tau-core; this keeps the text honest too."""
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in Path(tau_core.routines.__file__).parent.glob("*.py")
    }
    assert [name for name, text in sources.items() if "guard=None" in text] == ["engine.py"]


def test_the_core_readme_documents_routines() -> None:
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    assert "tau routine add" in readme and "ADR 0015" in readme
