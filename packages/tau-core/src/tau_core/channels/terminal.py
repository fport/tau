"""Terminal channel: ``tau chat``, a line-based REPL.

The reply streams under ``tau>``; tool calls show as indented lines; tier-2 calls ask on stdin
through :class:`TerminalApprover`. Slash commands are the shared spec in
:mod:`tau_core.commands` (``/help``, ``/tools``, ``/sessions``, ``/resume``, ``/new``,
``/session``, ``/lang``, ``/quit`` plus their aliases), one handler each in :data:`HANDLERS`.
Every string a person reads comes from :func:`tau_core.i18n.t` in ``ReplState.language``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import click
from rich.console import Console

from tau_core.agent import (
    Notice,
    TauAgent,
    TextDelta,
    ToolFinished,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
    build_agent,
)
from tau_core.approval import Approver, TerminalApprover
from tau_core.cli import help_option
from tau_core.commands import command_hint, help_lines, resolve_command
from tau_core.config import Config, ConfigError
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES, t
from tau_core.logs import configure_logging
from tau_core.models import MissingCredentials
from tau_core.sessions import SessionStore, open_session_store
from tau_core.tiers import tier_of

LIST_LIMIT = 10
SCAN_LIMIT = 100  # empty sessions are skipped, so look further back than the list shows


@dataclass
class ReplState:
    config: Config
    store: SessionStore
    approver: Approver
    agent: TauAgent
    console: Console
    role: str = "brain"
    running: bool = True
    language: str = DEFAULT_LANGUAGE
    last_listing: list[str] = field(default_factory=list)
    """Session ids of the last ``/sessions`` listing, so ``/resume n`` can refer to it."""

    def say(self, key: str, **kwargs: object) -> None:
        self.console.print(t(key, self.language, **kwargs))


CommandHandler = Callable[[ReplState, str], Awaitable[None]]


def render_turn_event(event: TurnEvent, language: str = DEFAULT_LANGUAGE) -> str | None:
    """The terminal line for a tool or notice event; ``None`` for text and turn ends."""
    if isinstance(event, ToolUseStarted):
        tier = "?" if event.tier is None else str(event.tier)
        return f"  ⚙ {event.tool} (tier {tier})"
    if isinstance(event, ToolFinished):
        if event.status == "rejected":
            return f"  ✗ {t('tool.rejected', language, tool=event.tool)}"
        mark = "✓" if event.status == "ok" else "✗"
        return f"  {mark} {event.tool}: {event.summary}"
    if isinstance(event, Notice):
        return f"  ℹ {event.text}"
    return None


# -- slash commands --------------------------------------------------------------------------


def _recent_sessions(state: ReplState) -> list:
    """Earlier sessions with messages, newest first, without the current one."""
    current = state.agent.session_id
    return [
        s
        for s in state.store.list_sessions(limit=SCAN_LIMIT)
        if s.session_id != current and s.message_count > 0
    ][:LIST_LIMIT]


def _switch_to(state: ReplState, session_id: str | None) -> bool:
    """Replace the agent with one on ``session_id`` (a fresh one when ``None``)."""
    from strands.types.exceptions import SessionException

    try:
        agent = build_agent(
            config=state.config,
            role=state.role,
            approver=state.approver,
            session_store=state.store,
            session_id=session_id,
            channel="terminal",
        )
    except (MissingCredentials, ConfigError) as exc:
        state.console.print(str(exc))
        return False
    except (SessionException, OSError, ValueError) as exc:
        state.say("session.open_failed", error=exc)
        return False
    state.agent.close()
    state.agent = agent
    return True


def _title_of(state: ReplState, session_id: str) -> str:
    from strands.types.exceptions import SessionException

    try:
        return str(state.store.read_meta(session_id).get("title") or "")
    except (SessionException, OSError, ValueError):
        return ""


async def cmd_help(state: ReplState, arg: str) -> None:
    """``/help``: every command with its one-line help."""
    state.say("chat.help_header")
    for line in help_lines(state.language):
        state.console.print(line)


async def cmd_sessions(state: ReplState, arg: str) -> None:
    """``/sessions``: list the 10 most recent earlier sessions, numbered for ``/resume n``."""
    from datetime import datetime

    from tau_core.persona import TIMEZONE

    def when(iso: str) -> str:
        try:
            return f"{datetime.fromisoformat(iso).astimezone(TIMEZONE):%d.%m.%Y %H:%M}"
        except ValueError:
            return iso or "?"

    recent = _recent_sessions(state)
    state.last_listing = [s.session_id for s in recent]
    if not recent:
        state.say("session.none_earlier")
        return
    state.say("session.recent_header")
    untitled = t("session.untitled", state.language)
    for n, s in enumerate(recent, start=1):
        count = t("session.messages", state.language, n=s.message_count)
        state.console.print(
            f"{n:>2}. {s.session_id}  {when(s.updated_at)}  {s.channel or '-'}  "
            f"{s.title or untitled} ({count})"
        )


async def cmd_resume(state: ReplState, arg: str) -> None:
    """``/resume [n|id]``: resume the most recent earlier session, the n-th of the last
    ``/sessions`` listing, or the session with that id. Nothing is listed here.

    Without a prior ``/sessions`` a number refers to the listing ``/sessions`` would print now.
    The resumed agent gets the stored messages back, so the model sees the whole conversation.
    """
    current = state.agent.session_id
    if arg and not (arg.isascii() and arg.isdigit()):
        if arg == current:
            state.say("session.already_current", session=current)
            return
        try:
            known = state.store.read_session(arg) is not None
        except ValueError as exc:  # an id that is not a plain name
            state.console.print(str(exc))
            return
        if not known:
            state.say("session.not_found", session=arg)
            return
        target = arg
    elif arg:
        listing = state.last_listing or [s.session_id for s in _recent_sessions(state)]
        n = int(arg)
        if not 1 <= n <= len(listing):
            state.say("session.no_such_number", n=n, count=len(listing))
            return
        target = listing[n - 1]
        if target == current:
            state.say("session.already_current", session=current)
            return
    else:
        recent = _recent_sessions(state)
        if not recent:
            state.say("session.none_earlier")
            return
        target = recent[0].session_id
    if not _switch_to(state, target):
        return
    title = _title_of(state, target) or t("session.untitled", state.language)
    state.say("session.resumed", title=title, session=target, n=len(state.agent.messages))


async def cmd_new(state: ReplState, arg: str) -> None:
    """``/new``: start a fresh session; the current one stays on record for ``/resume``."""
    if _switch_to(state, None):
        state.say("session.new", session=state.agent.session_id)


async def cmd_session(state: ReplState, arg: str) -> None:
    """``/session``: the current session id, title, message count and store backend."""
    from pathlib import Path

    from tau_core.sessions import FileSessionStore

    session_id = state.agent.session_id
    title = _title_of(state, session_id) or t("session.untitled", state.language)
    backend = state.config.sessions.backend
    if isinstance(state.store, FileSessionStore):
        root = state.store.root
        try:
            where = f"~/{root.relative_to(Path.home())}"
        except ValueError:
            where = str(root)
        backend = f"{backend} ({where})"
    state.say("session.info.id", session=session_id)
    state.say("session.info.title", title=title)
    state.say("session.info.count", n=len(state.agent.messages))
    state.say("session.info.store", store=backend)


async def cmd_tools(state: ReplState, arg: str) -> None:
    """``/tools``: the registered tools with their tiers."""
    tools = state.agent.catalog.tools()
    if not tools:
        state.say("tools.none")
        return
    state.say("tools.header", n=len(tools))
    for tool in tools:
        tier = tier_of(tool)
        description = (tool.tool_spec.get("description") or "").strip().splitlines()
        first_line = description[0] if description else ""
        label = t(f"tier.{int(tier)}", state.language)
        state.console.print(
            f"  {tool.tool_name}  tier {int(tier)} · {label}"
            + (f" — {first_line}" if first_line else "")
        )


async def cmd_lang(state: ReplState, arg: str) -> None:
    """``/lang en|tr``: switch the UI language for this run only."""
    choices = "|".join(LANGUAGES)
    if not arg:
        state.say("lang.usage", choices=choices, language=state.language)
        return
    if arg not in LANGUAGES:
        state.say("lang.unknown", language=arg, choices=choices)
        return
    state.language = arg
    if isinstance(state.approver, TerminalApprover):
        state.approver.language = arg
    state.say("lang.switched", language=arg)


async def cmd_quit(state: ReplState, arg: str) -> None:
    """``/quit``: leave the REPL."""
    state.running = False


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


async def dispatch_slash(state: ReplState, line: str) -> None:
    resolved = resolve_command(line)
    if resolved is None:
        name = line[1:].strip().partition(" ")[0]
        state.say("chat.unknown_command", name=name, hint=command_hint(state.language))
        return
    name, arg = resolved
    await HANDLERS[name](state, arg)


# -- turns and the loop ----------------------------------------------------------------------


async def run_turn(state: ReplState, prompt: str) -> None:
    console = state.console
    in_text = False
    async for event in state.agent.stream(prompt):
        if isinstance(event, TextDelta):
            if not in_text:
                console.print(t("chat.reply_prefix", state.language), end="", style="bold")
                in_text = True
            console.print(event.text, end="")
            continue
        if isinstance(event, TurnEnd):
            continue
        line = render_turn_event(event, state.language)
        if line is None:
            continue
        if in_text:
            console.print()
            in_text = False
        console.print(line, style="dim")
    if in_text:
        console.print()


def _shutdown(loop: asyncio.AbstractEventLoop) -> None:
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()


def run_repl(
    state: ReplState, *, resume: str | None = None, input_func: Callable[[str], str] = input
) -> None:
    """Read lines until ``/quit``, Ctrl-D or Ctrl-C."""
    console = state.console
    state.say(
        "chat.ready",
        profile=state.config.profile,
        session=state.agent.session_id,
        hint=command_hint(state.language),
    )
    loop = asyncio.new_event_loop()
    try:
        if resume is not None:
            loop.run_until_complete(cmd_resume(state, resume))
        while state.running:
            try:
                line = input_func(t("chat.prompt", state.language))
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            text = line.strip()
            if not text:
                continue
            try:
                if text.startswith("/"):
                    loop.run_until_complete(dispatch_slash(state, text))
                else:
                    loop.run_until_complete(run_turn(state, text))
            except KeyboardInterrupt:
                console.print()
                console.print(f"  ℹ {t('chat.interrupted', state.language)}", style="dim")
                if getattr(state.approver, "pending", False):
                    # An approval prompt is still blocking on stdin in a worker thread;
                    # waiting for it would hang the exit.
                    sys.stdout.flush()
                    os._exit(130)
                break
    finally:
        state.agent.close()
        _shutdown(loop)
    console.print("Goodbye.")


@click.command(name="chat", help="Chat with tau in the terminal.")
@help_option()
@click.option(
    "--role", default="brain", show_default=True, metavar="ROLE", help="Model role to use."
)
@click.option(
    "--resume",
    is_flag=False,
    flag_value="",
    default=None,
    metavar="[ID]",
    help="Resume an earlier session (same as /resume).",
)
@click.option("--session", "session_id", metavar="ID", help="Start with this session id.")
@click.pass_context
def chat(ctx: click.Context, role: str, resume: str | None, session_id: str | None) -> None:
    obj = ctx.find_object(dict) or {}
    console = Console(markup=False, emoji=False, highlight=False, soft_wrap=True)
    try:
        config = Config.load(obj.get("home"))
        if obj.get("profile"):
            config = config.with_overrides(profile=obj["profile"])
        configure_logging(config.logs_dir, verbose=bool(obj.get("verbose")))
        store = open_session_store(config)
        approver = TerminalApprover(language=config.ui.language)
        agent = build_agent(
            config=config,
            role=role,
            approver=approver,
            session_id=session_id,
            session_store=store,
            channel="terminal",
        )
    except (MissingCredentials, ConfigError) as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        return
    if sys.stdin.isatty():
        try:
            import readline  # noqa: F401  (line editing and history for input())
        except ImportError:
            pass
    state = ReplState(
        config=config,
        store=store,
        approver=approver,
        agent=agent,
        console=console,
        role=role,
        language=config.ui.language,
    )
    run_repl(state, resume=resume)
