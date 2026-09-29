"""Slash-command handlers for the TUI (the spec is ``tau_core.commands``).

Each handler is ``async (app, argument) -> None``. Read-only commands run while a turn is
busy; ``/new`` and ``/resume`` are refused with a toast until the turn ends.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from tau_core import LANGUAGES, t, tier_of
from tau_core.commands import help_lines

from tau_tui.keys import hints_for_help
from tau_tui.sessions import format_session, recent_sessions

if TYPE_CHECKING:
    from tau_tui.app import TauApp

CommandHandler = Callable[["TauApp", str], Awaitable[None]]


def tool_lines(app: TauApp) -> list[str]:
    lang = app.language
    tools = app.agent.catalog.tools()
    if not tools:
        return [t("tools.none", lang)]
    lines = [t("tools.header", lang, n=len(tools))]
    for tool in tools:
        tier = int(tier_of(tool))
        description = (tool.tool_spec.get("description") or "").strip().splitlines()
        first = f" — {description[0]}" if description else ""
        lines.append(f"{tool.tool_name}  tier {tier} · {t(f'tier.{tier}', lang)}{first}")
    return lines


def help_card_lines(app: TauApp) -> list[str]:
    lang = app.language
    return [
        t("chat.help_header", lang),
        *help_lines(lang),
        "",
        t("tui.help.keys_header", lang),
        *hints_for_help(lang),
    ]


async def cmd_help(app: TauApp, argument: str) -> None:
    await app.transcript.add_info(help_card_lines(app))


async def cmd_tools(app: TauApp, argument: str) -> None:
    await app.transcript.add_info(tool_lines(app))


async def cmd_sessions(app: TauApp, argument: str) -> None:
    lang = app.language
    recent = recent_sessions(app.store, app.agent.session_id)
    app.last_listing = [s.session_id for s in recent]
    if not recent:
        await app.transcript.add_info([t("session.none_earlier", lang)])
        return
    now = app.clock()
    lines = [t("session.recent_header", lang)]
    for n, summary in enumerate(recent, start=1):
        lines.append(format_session(summary, n, lang, now, width=76, tz=app.tz))
    await app.transcript.add_info(lines)


async def cmd_resume(app: TauApp, argument: str) -> None:
    lang = app.language
    current = app.agent.session_id
    store = app.store
    if argument and not (argument.isascii() and argument.isdigit()):
        if argument == current:
            await app.transcript.add_notice(t("session.already_current", lang, session=current))
            return
        try:
            known = store is not None and store.read_session(argument) is not None
        except ValueError as exc:  # an id that is not a plain name
            await app.transcript.add_notice(str(exc))
            return
        if not known:
            await app.transcript.add_notice(t("session.not_found", lang, session=argument))
            return
        target = argument
    elif argument:
        listing = app.last_listing or [s.session_id for s in recent_sessions(store, current)]
        n = int(argument)
        if not 1 <= n <= len(listing):
            await app.transcript.add_notice(
                t("session.no_such_number", lang, n=n, count=len(listing))
            )
            return
        target = listing[n - 1]
        if target == current:
            await app.transcript.add_notice(t("session.already_current", lang, session=current))
            return
    else:
        recent = recent_sessions(store, current)
        if not recent:
            await app.transcript.add_notice(t("session.none_earlier", lang))
            return
        target = recent[0].session_id
    await app.switch_session(target)


async def cmd_new(app: TauApp, argument: str) -> None:
    await app.switch_session(None)


async def cmd_session(app: TauApp, argument: str) -> None:
    lang = app.language
    session_id = app.agent.session_id
    title = app.session_title(session_id) or t("session.untitled", lang)
    await app.transcript.add_info(
        [
            t("session.info.id", lang, session=session_id),
            t("session.info.title", lang, title=title),
            t("session.info.count", lang, n=len(app.agent.messages)),
            t("session.info.store", lang, store=app.agent.config.sessions.backend),
        ]
    )


async def cmd_lang(app: TauApp, argument: str) -> None:
    lang = app.language
    choices = "|".join(LANGUAGES)
    if not argument:
        await app.transcript.add_notice(t("lang.usage", lang, choices=choices, language=lang))
        return
    if argument not in LANGUAGES:
        await app.transcript.add_notice(t("lang.unknown", lang, language=argument, choices=choices))
        return
    app.language = argument
    app.notify(t("lang.switched", argument, language=argument))


async def cmd_quit(app: TauApp, argument: str) -> None:
    app.exit()


HANDLERS: dict[str, CommandHandler] = {
    "help": cmd_help,
    "tools": cmd_tools,
    "sessions": cmd_sessions,
    "resume": cmd_resume,
    "new": cmd_new,
    "session": cmd_session,
    "lang": cmd_lang,
    "quit": cmd_quit,
}

SWITCHING = frozenset({"new", "resume"})
"""Commands refused while a turn is busy."""
