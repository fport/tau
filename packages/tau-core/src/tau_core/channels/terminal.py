"""Terminal channel: ``tau chat``, a line-based REPL.

The reply streams under ``tau>``; tool calls show as indented lines; tier-2 calls ask on stdin
through :class:`TerminalApprover`. Slash commands are the shared spec in
:mod:`tau_core.commands` (``/help``, ``/tools``, ``/sessions``, ``/resume``, ``/new``,
``/session``, ``/compact``, ``/clear``, ``/status``, ``/model``, ``/lang``, ``/settings``,
``/quit`` plus their aliases), one handler each in :data:`HANDLERS`. The REPL runs one thing
at a time, so a command can never overlap a turn; the TUI's "busy" refusals have no
counterpart here.
Every string a person reads comes from :func:`tau_core.i18n.t` in ``ReplState.language``.
"""

from __future__ import annotations

import asyncio
import getpass
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
    Throttled,
    ToolFinished,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
    build_agent,
)
from tau_core.approval import Approver, TerminalApprover
from tau_core.cli import help_option
from tau_core.commands import command_hint, help_lines, resolve_command
from tau_core.compaction import (
    CompactionError,
    compaction_title,
    record_compaction,
    seed_messages,
    summarize,
)
from tau_core.config import Config, ConfigError
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES, t
from tau_core.logs import configure_logging
from tau_core.models import MissingCredentials
from tau_core.sessions import SessionStore, open_session_store
from tau_core.settings import (
    KEEP,
    clear_credential,
    load_document,
    report_lines,
    save_document,
    set_credential,
    set_role,
    set_ui_language,
    validate,
)
from tau_core.status import describe_model, role_lines, status_report, stored_role
from tau_core.tiers import tier_of

LIST_LIMIT = 10
SCAN_LIMIT = 100  # empty sessions are skipped, so look further back than the list shows
DEFAULT_ROLE = "brain"
CLEAR_SCREEN = "\x1b[2J\x1b[H"
"""ANSI: erase the whole screen, cursor to the top-left."""


@dataclass
class ReplState:
    config: Config
    store: SessionStore
    approver: Approver
    agent: TauAgent
    console: Console
    role: str = DEFAULT_ROLE
    role_pinned: bool = False
    """``--role`` was given: a resumed session's stored role never overrides it."""
    running: bool = True
    language: str = DEFAULT_LANGUAGE
    last_listing: list[str] = field(default_factory=list)
    """Session ids of the last ``/sessions`` listing, so ``/resume n`` can refer to it."""

    def say(self, key: str, **kwargs: object) -> None:
        self.console.print(t(key, self.language, **kwargs))


CommandHandler = Callable[[ReplState, str], Awaitable[None]]


def render_turn_event(event: TurnEvent, language: str = DEFAULT_LANGUAGE) -> str | None:
    """The terminal line for a tool, throttle or notice event; ``None`` for text, reasoning,
    tool progress and turn ends."""
    if isinstance(event, Throttled):
        return f"  ⏳ {t('notice.throttled', language, seconds=f'{event.delay_seconds:g}')}"
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


def _switch_to(
    state: ReplState,
    session_id: str | None,
    *,
    role: str | None = None,
    seed_messages: list | None = None,
) -> bool:
    """Replace the agent with one on ``session_id`` (a fresh one when ``None``).

    ``role`` overrides the current role (``/model``); otherwise a resumed session's stored role
    is used unless ``--role`` pinned one. ``seed_messages`` is the initial history of a fresh
    session (``/compact``). On any failure the message is printed and the agent is unchanged.
    """
    from strands.types.exceptions import SessionException

    if role is None:
        role = state.role
        if session_id is not None and not state.role_pinned:
            role = stored_role(state.store, session_id, state.config) or state.role
    try:
        agent = build_agent(
            config=state.config,
            role=role,
            approver=state.approver,
            session_store=state.store,
            session_id=session_id,
            channel="terminal",
            seed_messages=seed_messages,
        )
    except (MissingCredentials, ConfigError) as exc:
        state.console.print(str(exc))
        return False
    except (SessionException, OSError, ValueError) as exc:
        state.say("session.open_failed", error=exc)
        return False
    agent.carry_over(state.agent)  # a rebuild on the same session keeps its pending repair
    state.agent.close()
    state.agent = agent
    state.role = role
    return True


def _ready_banner(state: ReplState) -> None:
    state.say(
        "chat.ready",
        profile=state.config.profile,
        session=state.agent.session_id,
        hint=command_hint(state.language),
    )


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


async def cmd_clear(state: ReplState, arg: str) -> None:
    """``/clear``: erase the screen and print the ready banner again. The session and the
    agent are untouched: ``--resume`` shows the history again."""
    state.console.print(CLEAR_SCREEN, end="")
    _ready_banner(state)
    state.say("clear.done", n=len(state.agent.messages))


async def cmd_compact(state: ReplState, arg: str) -> None:
    """``/compact [focus]``: summarize the session with the agent's own model, open a new
    session seeded with the summary and continue there. The old session stays in the store;
    the two are linked through ``compacted_from`` / ``compacted_to`` in their metadata."""
    old = state.agent
    n = len(old.messages)
    if n:
        state.say("compact.started", n=n)
    try:
        summary = await summarize(old, focus=arg or None)
    except CompactionError as exc:
        state.say("compact.failed", error=exc)
        return
    title = compaction_title(old)
    if not _switch_to(state, None, seed_messages=seed_messages(summary, old.session_id)):
        return
    record_compaction(
        state.store,
        previous=old.session_id,
        new=state.agent.session_id,
        title=title,
        role=state.role,
    )
    state.say("compact.done", n=n, session=state.agent.session_id, previous=old.session_id)
    state.console.print(summary, style="dim")


async def cmd_status(state: ReplState, arg: str) -> None:
    """``/status``: profile, session, model, context, tools, UI language, versions, hub."""
    for line in await status_report(state.agent, language=state.language):
        state.console.print(line)


async def cmd_model(state: ReplState, arg: str) -> None:
    """``/model [role]``: without an argument, the roles of ``tau.toml`` with the current one
    marked; with one, rebuild the agent on the same session with that role and remember it in
    the session's metadata, so ``/resume`` and ``--resume`` come back on the same role."""
    if not arg:
        for line in role_lines(state.agent, state.language):
            state.console.print(line)
        return
    if arg not in state.config.roles:
        state.say("model.unknown", role=arg, roles=", ".join(state.config.roles))
        return
    if arg != state.role and not _switch_to(state, state.agent.session_id, role=arg):
        return
    state.store.write_meta(state.agent.session_id, role=arg)
    state.say("model.current", role=arg, provider=describe_model(state.agent).provider)


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


def _reload_after_save(state: ReplState, *, rebuild: bool) -> None:
    """Re-read the saved files; with ``rebuild``, replace the agent on the same session so a
    changed role, credential or profile takes effect. A file that no longer loads, or an agent
    that cannot be built, is reported and the current agent keeps running."""
    try:
        state.config = validate(state.config.home)
    except ConfigError as exc:
        state.say("settings.saved_not_reloaded", error=exc)
        return
    if not rebuild:
        state.say("settings.saved")
        return
    if _switch_to(state, state.agent.session_id):
        state.say("settings.saved_reloaded")


async def cmd_settings(state: ReplState, arg: str) -> None:
    """``/settings``: the bootstrap config (roles, credential status, language, profile,
    context, files) and how to change it; ``/settings language|profile|model|set|clear …``
    write ``tau.toml`` or ``.env`` through :mod:`tau_core.settings` and rebuild the agent.
    A credential value is read with ``getpass`` and never echoed or printed."""
    home = state.config.home
    words = arg.split()
    if not words:
        for line in report_lines(state.config, language=state.language):
            state.console.print(line)
        return
    key, values = words[0].casefold(), words[1:]
    try:
        if key == "language" and len(values) == 1:
            doc = load_document(home)
            set_ui_language(doc, values[0])
            save_document(home, doc)
            _reload_after_save(state, rebuild=False)
            state.language = values[0]
            if isinstance(state.approver, TerminalApprover):
                state.approver.language = values[0]
            state.say("lang.switched", language=values[0])
        elif key == "profile" and len(values) == 1:
            set_credential(home, "TAU_PROFILE", values[0], export=True)
            _reload_after_save(state, rebuild=True)
        elif key == "model" and len(values) == 3:
            role, provider, model_id = values
            doc = load_document(home)
            set_role(doc, role, provider, model_id, max_tokens=KEEP, fallback=KEEP)
            save_document(home, doc)
            _reload_after_save(state, rebuild=True)
        elif key == "set" and len(values) == 1:
            name = values[0]
            value = getpass.getpass(t("settings.enter_value", state.language, name=name))
            if not value.strip():
                state.say("settings.credential_empty", name=name)
                return
            set_credential(home, name, value, export=True)
            state.say("settings.credential_set", name=name)
            _reload_after_save(state, rebuild=True)
        elif key == "clear" and len(values) == 1:
            name = values[0]
            if clear_credential(home, name, export=True):
                state.say("settings.credential_cleared", name=name)
                _reload_after_save(state, rebuild=True)
            else:
                state.say("settings.credential_absent", name=name)
        else:
            state.say("settings.usage")
    except (ConfigError, ValueError, OSError) as exc:
        state.say("settings.invalid", error=exc)


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
    "compact": cmd_compact,
    "clear": cmd_clear,
    "status": cmd_status,
    "model": cmd_model,
    "lang": cmd_lang,
    "settings": cmd_settings,
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
    _ready_banner(state)
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
    "--role",
    default=None,
    metavar="ROLE",
    help=f"Model role to use (default: {DEFAULT_ROLE}, or the role a resumed session "
    "remembers from /model).",
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
def chat(ctx: click.Context, role: str | None, resume: str | None, session_id: str | None) -> None:
    obj = ctx.find_object(dict) or {}
    console = Console(markup=False, emoji=False, highlight=False, soft_wrap=True)
    role_pinned = role is not None
    try:
        config = Config.load(obj.get("home"))
        if obj.get("profile"):
            config = config.with_overrides(profile=obj["profile"])
        configure_logging(config.logs_dir, verbose=bool(obj.get("verbose")))
        store = open_session_store(config)
        if not role_pinned:
            role = stored_role(store, session_id, config) or DEFAULT_ROLE
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
        role_pinned=role_pinned,
        language=config.ui.language,
    )
    run_repl(state, resume=resume)
