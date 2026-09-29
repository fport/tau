"""Slash commands shared by the terminal REPL and the TUI.

The spec lives here (names, aliases, arguments, help keys); the handlers stay in each channel.
Canonical names are English; the Turkish aliases are accepted forever and never shown in hints.
"""

from __future__ import annotations

from dataclasses import dataclass

from tau_core.i18n import DEFAULT_LANGUAGE, t

__all__ = [
    "SLASH_COMMANDS",
    "SlashCommand",
    "command_hint",
    "help_lines",
    "resolve_command",
    "usage",
]


@dataclass(frozen=True)
class SlashCommand:
    name: str
    aliases: tuple[str, ...] = ()
    argument: str | None = None
    help_key: str = ""

    def matches(self, typed: str) -> bool:
        """``typed`` is the name without ``/``; matching is ``str.casefold`` on both sides."""
        folded = typed.casefold()
        return folded == self.name.casefold() or any(
            folded == alias.casefold() for alias in self.aliases
        )


SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("help", ("yardım", "yardim", "?"), None, "command.help"),
    SlashCommand("tools", ("araçlar", "araclar"), None, "command.tools"),
    SlashCommand("sessions", ("oturumlar",), None, "command.sessions"),
    SlashCommand("resume", ("devam",), "[n|id]", "command.resume"),
    SlashCommand("new", ("yeni",), None, "command.new"),
    SlashCommand("session", ("oturum",), None, "command.session"),
    SlashCommand("compact", ("özet", "ozet"), "[focus]", "command.compact"),
    SlashCommand("clear", ("temizle", "cls"), None, "command.clear"),
    SlashCommand("status", ("durum",), None, "command.status"),
    SlashCommand("model", ("rol",), "[role]", "command.model"),
    SlashCommand("lang", ("dil",), "en|tr", "command.lang"),
    SlashCommand("settings", ("ayarlar", "ayar"), "[key value]", "command.settings"),
    SlashCommand("quit", ("çık", "cik", "exit"), None, "command.quit"),
)


def resolve_command(line: str) -> tuple[str, str] | None:
    """``(canonical name, argument)`` for a typed slash line; ``None`` when it is not a command.

    ``"/Devam 2"`` → ``("resume", "2")``; ``"/x"`` and ``"hello"`` → ``None``. The argument is
    stripped and ``""`` when absent.
    """
    text = line.strip()
    if not text.startswith("/"):
        return None
    name, _, argument = text[1:].strip().partition(" ")
    for command in SLASH_COMMANDS:
        if command.matches(name):
            return command.name, argument.strip()
    return None


def usage(command: SlashCommand) -> str:
    """``/resume [n|id]`` — the canonical name with its argument placeholder."""
    return f"/{command.name}" + (f" {command.argument}" if command.argument else "")


def command_hint(language: str = DEFAULT_LANGUAGE) -> str:
    """The canonical command names, comma-separated: ``/help, /tools, ...`` (never aliases).

    ``language`` is accepted so hints can be localized later; the names themselves are fixed.
    """
    return ", ".join(f"/{command.name}" for command in SLASH_COMMANDS)


def help_lines(language: str = DEFAULT_LANGUAGE) -> list[str]:
    """One line per command: usage padded to a column, then its help text in ``language``."""
    width = max(len(usage(command)) for command in SLASH_COMMANDS)
    return [
        f"  {usage(command):<{width}}  {t(command.help_key, language)}"
        for command in SLASH_COMMANDS
    ]
