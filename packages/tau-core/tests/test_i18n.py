"""The message table (``tau_core.i18n``) and the shared slash commands (``tau_core.commands``)."""

from __future__ import annotations

import pytest
import tau_core
from tau_core import LANGUAGES, SLASH_COMMANDS, SlashCommand, command_hint, resolve_command, t
from tau_core.commands import help_lines, usage
from tau_core.i18n import DEFAULT_LANGUAGE, MESSAGES, register_messages

# -- the table ---------------------------------------------------------------------------------


def test_every_key_has_both_languages() -> None:
    assert LANGUAGES == ("en", "tr") and DEFAULT_LANGUAGE == "en"
    missing = {key: sorted(set(LANGUAGES) - set(templates)) for key, templates in MESSAGES.items()}
    assert {key: langs for key, langs in missing.items() if langs} == {}
    assert all("." in key for key in MESSAGES)  # dotted, stable keys


def test_placeholders_match_between_languages() -> None:
    import string

    fields = string.Formatter()
    for key, templates in MESSAGES.items():
        names = {
            language: {name for _, name, _, _ in fields.parse(text) if name}
            for language, text in templates.items()
        }
        assert names["en"] == names["tr"], key


def test_t_formats_and_falls_back() -> None:
    assert t("session.not_found", "en", session="x") == "Session not found: x."
    assert t("session.not_found", "tr", session="x") == "Oturum bulunamadı: x."
    assert t("session.not_found", session="x") == "Session not found: x."  # default English
    assert t("session.not_found", "de", session="x") == "Session not found: x."  # unknown → en
    assert t("tier.0") == "read" and t("tier.0", "tr") == "okuma"
    with pytest.raises(KeyError):
        t("no.such.key")


def test_register_messages_adds_and_extends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MESSAGES, "plugin.hello", {"en": "Hello {name}"})
    register_messages({"plugin.hello": {"tr": "Merhaba {name}"}, "plugin.bye": {"en": "Bye"}})
    try:
        assert t("plugin.hello", "tr", name="x") == "Merhaba x"
        assert t("plugin.bye", "tr") == "Bye"  # Turkish falls back to English
        with pytest.raises(ValueError):
            register_messages({"plugin.only_tr": {"tr": "yok"}})
    finally:
        MESSAGES.pop("plugin.bye", None)


def test_tui_keys_are_present() -> None:
    for key in (
        "tui.placeholder",
        "tui.header.profile",
        "tui.pane.chat",
        "tui.pane.events",
        "tui.busy",
        "tui.unknown_command",
        "tui.approval.title",
        "tui.approval.approve",
        "tui.approval.reject",
        "tui.approval.hint",
        "tui.key.quit",
        "tui.lang.switched",
        "tui.cancelled",
    ):
        assert key in MESSAGES


# -- slash commands ----------------------------------------------------------------------------


def test_command_names_and_aliases() -> None:
    assert [c.name for c in SLASH_COMMANDS] == [
        "help",
        "tools",
        "sessions",
        "resume",
        "new",
        "session",
        "lang",
        "quit",
    ]
    by_name = {c.name: c for c in SLASH_COMMANDS}
    assert by_name["help"].aliases == ("yardım", "yardim", "?")
    assert by_name["tools"].aliases == ("araçlar", "araclar")
    assert by_name["quit"].aliases == ("çık", "cik", "exit")
    assert by_name["resume"].argument == "[n|id]" and by_name["lang"].argument == "en|tr"
    assert all(c.help_key in MESSAGES for c in SLASH_COMMANDS)
    assert isinstance(by_name["help"], SlashCommand)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("/help", ("help", "")),
        ("/?", ("help", "")),
        ("/YARDIM", ("help", "")),
        ("/ARAÇLAR", ("tools", "")),
        ("/Devam 2", ("resume", "2")),
        ("  /resume   20260929-120000-abcd  ", ("resume", "20260929-120000-abcd")),
        ("/dil tr", ("lang", "tr")),
        ("/exit", ("quit", "")),
        ("/çık", ("quit", "")),
        ("/cik", ("quit", "")),
        ("/nope", None),
        ("help", None),
        ("/", None),
    ],
)
def test_resolve_command(line: str, expected: tuple[str, str] | None) -> None:
    assert resolve_command(line) == expected


def test_hint_and_help_lines() -> None:
    hint = command_hint()
    assert hint == "/help, /tools, /sessions, /resume, /new, /session, /lang, /quit"
    assert command_hint("tr") == hint  # canonical names only, never aliases
    assert "devam" not in hint and "araçlar" not in hint
    assert usage(SLASH_COMMANDS[3]) == "/resume [n|id]"
    en, tr = help_lines("en"), help_lines("tr")
    assert len(en) == len(tr) == len(SLASH_COMMANDS)
    assert en[0].startswith("  /help ") and en[0].rstrip().endswith("list the commands")
    assert tr[-1].rstrip().endswith("çıkar")


def test_public_api_exports() -> None:
    for name in (
        "t",
        "Language",
        "LANGUAGES",
        "UiConfig",
        "SlashCommand",
        "SLASH_COMMANDS",
        "resolve_command",
        "command_hint",
    ):
        assert name in tau_core.__all__ and hasattr(tau_core, name)
