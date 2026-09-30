"""Packaging rules: entry points, the public API, the message table, the persona template."""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import tau_net
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_net.strings import NET_MESSAGES

ROOT = Path(__file__).resolve().parents[3]


def test_entry_points() -> None:
    points = {(ep.group, ep.name): ep.value for ep in metadata.distribution("tau-net").entry_points}
    assert points == {
        ("tau.commands", "net"): "tau_net.cli:net",
        ("tau.hub_services", "net"): "tau_net.service:make_service",
        ("tau.tools", "net"): "tau_net.tools:TOOLS",
    }
    assert metadata.version("tau-net") == tau_net.__version__


def test_public_api_is_explicit() -> None:
    assert sorted(tau_net.__all__) == sorted(set(tau_net.__all__))
    for name in tau_net.__all__:
        assert hasattr(tau_net, name), name


def test_every_message_has_both_languages() -> None:
    for key, templates in NET_MESSAGES.items():
        assert key.startswith("net."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    source = Path(tau_net.__file__).parent
    for path in source.glob("*.py"):
        if path.name in {"strings.py", "spine_strings.py"}:
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


def test_the_public_note_template_holds_nothing_personal() -> None:
    template = (ROOT / "persona" / "net.example.md").read_text(encoding="utf-8")
    assert template.startswith("<!--")
    assert "made up" in template
    assert "@" not in template and "http" not in template
