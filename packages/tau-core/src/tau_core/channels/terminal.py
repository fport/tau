"""Terminal channel: ``tau chat``, a line-based REPL.

The reply streams under ``tau>``; tool calls show as indented lines; tier-2 calls ask on stdin
through :class:`TerminalApprover`. Slash commands are the shared spec in
:mod:`tau_core.commands` (``/help``, ``/tools``, ``/sessions``, ``/resume``, ``/new``,
``/session``, ``/compact``, ``/clear``, ``/status``, ``/model``, ``/lang``, ``/settings``,
``/guard``, ``/quit`` plus their aliases), one handler each in :data:`HANDLERS`. The REPL runs
one thing at a time, so a command can never overlap a turn; the TUI's "busy" refusals have no
counterpart here.
Every string a person reads comes from :func:`tau_core.i18n.t` in ``ReplState.language``.

With an owner guard (ADR 0008) the REPL shows a lock prompt while the guard is not unlocked:
entering it clears the screen and the scrollback (a terminal that ignores ``\x1b[3J`` keeps
its scrollback), Enter on an empty line unlocks and prints every challenge step, Ctrl-C during
an attempt cancels it and keeps the REPL, and only :data:`~tau_core.guard.ALLOWED_WHILE_LOCKED`
commands run. The state is read again before every prompt; a turn the guard refused
(``TurnEnd("locked")``) returns to the lock prompt, and a ``recheck`` refusal runs the passive
check and resends the prompt. Step-up challenge steps arrive as ``guard`` events on the agent's
bus and print under the tool call.
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
from tau_core.events import AgentEvent
from tau_core.guard import (
    ALLOWED_WHILE_LOCKED,
    DISCOVER,
    VERDICT_REASONS,
    Guard,
    GuardProgress,
    GuardStatus,
    GuardVerdict,
    admission_reason,
    guard_status_line,
    process_client_id,
    resolve_guard,
)
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
CLEAR_ALL = "\x1b[2J\x1b[3J\x1b[H"
"""ANSI: erase the screen and the scrollback, cursor to the top-left (the lock prompt)."""
COUNTED_FAILURES = frozenset({"no_match", "spoof", "multiple_faces"})
"""Verdict reasons that count as a failed attempt (ADR 0008 decision 13)."""


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
    guard: Guard | None = None
    """The owner guard (ADR 0008), resolved once per process and passed to every build. While
    it is ``None`` it is resolved again before every build and prompt (one stat), so a guard
    set up after the start is found at once."""
    locked: bool = False
    """The lock prompt is showing."""
    lock_seq: int = -1
    """The guard's ``seq`` when the lock prompt was entered: the prompt leaves by itself only
    when the guard reports ``unlocked`` with another ``seq`` (another channel unlocked)."""
    guard_failures: int = 0
    """Failed attempts this REPL saw since the last unlock (the hub may count more)."""
    last_status: GuardStatus | None = None
    pending_resume: str | None = None
    """``--resume`` waits until the first unlock (a resumed session prints its title)."""

    def say(self, key: str, **kwargs: object) -> None:
        self.console.print(t(key, self.language, **kwargs))

    def current_guard(self) -> Guard | None:
        """The process's guard; resolved again while there is none."""
        if self.guard is None:
            self.guard = resolve_guard(self.config)
        return self.guard


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
    guard = state.current_guard()
    try:
        agent = build_agent(
            config=state.config,
            role=role,
            approver=state.approver,
            session_store=state.store,
            session_id=session_id,
            channel="terminal",
            seed_messages=seed_messages,
            guard=guard if guard is not None else DISCOVER,
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
            value = getpass.getpass(t("settings.enter_value", state.language, name=name)).strip()
            if not value:
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


async def cmd_guard(state: ReplState, arg: str) -> None:
    """``/guard [lock|unlock]``: the guard's state, a lock (the lock prompt follows), or, while
    unlocked, a note that there is nothing to unlock. While locked, ``/guard unlock`` is an
    unlock attempt; :func:`run_repl` runs it so Ctrl-C can cancel it."""
    guard = state.current_guard()
    if guard is None:
        state.say("guard.cmd.off")
        return
    word = arg.strip().casefold()
    if not word:
        status = await guard.status()
        state.last_status = status
        state.console.print(guard_status_line(status, state.language))
    elif word == "lock":
        await guard.lock(channel="terminal", client_id=process_client_id(), trigger="command")
        status = await guard.status()
        state.last_status = status
        if status.state == "locked":
            _enter_lock(state, status)
        else:
            state.say("guard.cmd.lock_failed")
    elif word == "unlock":
        state.say("guard.cmd.already_unlocked")
    else:
        state.say("guard.cmd.usage")


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
    "guard": cmd_guard,
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


# -- the owner guard ----------------------------------------------------------------------------


def progress_text(progress: GuardProgress, language: str = DEFAULT_LANGUAGE) -> str:
    """One challenge step ("Turn your head left."), with a live hint ("It is too dark.")."""
    try:
        text = t(f"guard.progress.{progress.step}", language)
    except KeyError:
        text = str(progress.step)
    if progress.hint in VERDICT_REASONS:
        text = f"{text} {t(f'guard.verdict.{progress.hint}', language)}"
    return text


def verdict_text(verdict: GuardVerdict, language: str = DEFAULT_LANGUAGE) -> str:
    """Why an attempt did not pass, with "try again in N s" for a cooldown."""
    reason = verdict.reason if verdict.reason in VERDICT_REASONS else "error"
    text = t(f"guard.verdict.{reason}", language)
    if verdict.retry_after:
        text = f"{text} {t('guard.retry_after', language, seconds=f'{verdict.retry_after:.0f}')}"
    return text


def _enter_lock(state: ReplState, status: GuardStatus | None) -> None:
    """Show the lock prompt: clear the screen and the scrollback, then the banner."""
    state.locked = True
    state.lock_seq = status.seq if status is not None else -1
    state.console.print(CLEAR_ALL, end="")
    if status is not None:
        state.console.print(guard_status_line(status, state.language))
    state.say("guard.prompt.banner")


def _failures(state: ReplState) -> int:
    hub = state.last_status.failures if state.last_status is not None else 0
    return max(hub, state.guard_failures)


def _leave_lock(state: ReplState, loop: asyncio.AbstractEventLoop, method: str | None) -> None:
    """Unlocked: the notice with the failure count, the ready banner, a pending ``--resume``.
    Nothing is sent to the model."""
    state.locked = False
    state.say("guard.unlocked", method=method or "—", failures=_failures(state))
    state.guard_failures = 0
    _ready_banner(state)
    resume, state.pending_resume = state.pending_resume, None
    if resume is not None:
        loop.run_until_complete(cmd_resume(state, resume))


def _check_guard(state: ReplState, loop: asyncio.AbstractEventLoop) -> None:
    """Read the guard's state before a prompt and enter or leave the lock prompt."""
    guard = state.current_guard()
    if guard is None:
        return
    status = loop.run_until_complete(guard.status())
    state.last_status = status
    if status.state != "unlocked":
        if not state.locked:
            _enter_lock(state, status)
        elif status.seq != state.lock_seq:
            state.lock_seq = status.seq  # still locked after a change (a failed attempt)
    elif state.locked and status.seq != state.lock_seq:
        _leave_lock(state, loop, status.method)  # another channel unlocked


def _attempt(
    state: ReplState, loop: asyncio.AbstractEventLoop, kind: str = "unlock"
) -> GuardVerdict | None:
    """One unlock (or passive ``recheck``) attempt, printing every step. Ctrl-C cancels it and
    returns ``None``; the REPL keeps running."""
    guard = state.guard
    assert guard is not None
    language = state.language

    def on_progress(progress: GuardProgress) -> None:
        state.console.print(f"  ◉ {progress_text(progress, language)}")

    if kind == "recheck":
        state.console.print(f"  ◉ {t('guard.recheck', language)}")
    task = loop.create_task(
        guard.unlock(
            channel="terminal", client_id=process_client_id(), kind=kind, on_progress=on_progress
        )
    )
    try:
        verdict = loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        loop.run_until_complete(asyncio.wait({task}))
        if not task.cancelled():
            task.exception()  # retrieved, so nothing is logged as never retrieved
        loop.run_until_complete(guard.cancel(client_id=process_client_id()))
        state.console.print()
        state.console.print(f"  ✗ {t('guard.verdict.cancelled', language)}")
        return None
    if not verdict.ok:
        if verdict.reason in COUNTED_FAILURES:
            state.guard_failures += 1
        state.console.print(f"  ✗ {verdict_text(verdict, language)}")
    return verdict


def _unlock(state: ReplState, loop: asyncio.AbstractEventLoop) -> None:
    """Enter on an empty line (or ``/guard unlock``) at the lock prompt."""
    verdict = _attempt(state, loop)
    if verdict is not None and verdict.ok:
        _leave_lock(state, loop, verdict.method)
        return
    if state.guard is not None:
        state.last_status = loop.run_until_complete(state.guard.status())
        state.lock_seq = state.last_status.seq
    state.say("guard.prompt.retry")


def _locked_line(state: ReplState, loop: asyncio.AbstractEventLoop, text: str) -> None:
    """A line typed at the lock prompt: Enter unlocks; only the allowed commands run."""
    if not text:
        _unlock(state, loop)
        return
    if not text.startswith("/"):
        state.say("guard.prompt.not_sent")
        return
    resolved = resolve_command(text)
    if resolved is None:
        loop.run_until_complete(dispatch_slash(state, text))  # the unknown-command answer
        return
    name, arg = resolved
    if name == "guard" and arg.strip().casefold() == "unlock":
        _unlock(state, loop)
    elif name in ALLOWED_WHILE_LOCKED:
        loop.run_until_complete(dispatch_slash(state, text))
    else:
        state.say("guard.cmd.refused", command=name)


def _still_unlocked(state: ReplState, loop: asyncio.AbstractEventLoop) -> bool:
    """Right before a command that is not allowed while locked: the guard may have locked
    while the line was typed. ``False`` after entering the lock prompt."""
    guard = state.current_guard()
    if guard is None:
        return True
    status = loop.run_until_complete(guard.status())
    state.last_status = status
    if status.state == "unlocked":
        return True
    _enter_lock(state, status)
    return False


# -- turns and the loop ----------------------------------------------------------------------


async def run_turn(state: ReplState, prompt: str) -> str | None:
    """Stream one turn. Returns the guard's reason when it refused the turn
    (``TurnEnd("locked")``), else ``None``. Step-up challenge steps print from the agent's
    ``guard`` events while the tool waits."""
    console = state.console
    agent = state.agent
    language = state.language
    in_text = False
    refused: list[str] = []
    locked = False

    def line(text: str) -> None:
        nonlocal in_text
        if in_text:
            console.print()
            in_text = False
        console.print(text)

    def on_event(event: AgentEvent) -> None:
        if event.kind != "guard" or event.session_id not in (None, agent.session_id):
            return
        data = event.data
        action = data.get("action")
        if action == "refused" and "tool" not in data:
            refused.append(str(data.get("reason")))
        elif action == "step_up" and data.get("phase") == "start":
            line(f"  ◉ {t('guard.step_up.start', language)}")
        elif action == "step_up" and data.get("phase") == "end":
            key = "guard.step_up.passed" if data.get("ok") is True else "guard.step_up.failed"
            line(f"  {'✓' if data.get('ok') is True else '✗'} {t(key, language)}")
        elif action == "challenge":
            step = GuardProgress(
                step=str(data.get("step")), seq=0, deadline=None, hint=data.get("hint")
            )
            line(f"  ◉ {progress_text(step, language)}")

    unsubscribe = agent.events.subscribe(on_event)
    try:
        async for event in agent.stream(prompt):
            if isinstance(event, TextDelta):
                if not in_text:
                    console.print(t("chat.reply_prefix", language), end="", style="bold")
                    in_text = True
                console.print(event.text, end="")
                continue
            if isinstance(event, TurnEnd):
                locked = event.stop_reason == "locked"
                continue
            rendered = render_turn_event(event, language)
            if rendered is None:
                continue
            if in_text:
                console.print()
                in_text = False
            console.print(rendered, style="dim")
    finally:
        unsubscribe()
    if in_text:
        console.print()
    if locked:
        return refused[-1] if refused else "error"
    return None


def _turn(state: ReplState, loop: asyncio.AbstractEventLoop, prompt: str) -> None:
    """One prompt: a ``recheck`` refusal runs the passive check once and resends the prompt;
    any other refusal returns to the lock prompt."""
    reason = loop.run_until_complete(run_turn(state, prompt))
    if reason == "recheck" and state.current_guard() is not None:
        verdict = _attempt(state, loop, kind="recheck")
        if verdict is not None and verdict.ok:
            reason = loop.run_until_complete(run_turn(state, prompt))
    if reason is None or state.current_guard() is None:
        return
    guard = state.guard
    assert guard is not None
    status = loop.run_until_complete(guard.status())
    state.last_status = status
    _enter_lock(state, status)
    # the refusal notice went with the cleared screen: say it again under the banner
    state.console.print(f"  ℹ {t(f'guard.refused.{admission_reason(reason)}', state.language)}")


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
    """Read lines until ``/quit``, Ctrl-D or Ctrl-C; the lock prompt while the guard is not
    unlocked."""
    console = state.console
    loop = asyncio.new_event_loop()
    try:
        guard = state.current_guard()
        try:
            status = loop.run_until_complete(guard.status()) if guard is not None else None
        except KeyboardInterrupt:
            console.print()
            state.running = False
            status = None
        state.last_status = status
        if not state.running:
            pass
        elif status is not None and status.state != "unlocked":
            state.pending_resume = resume
            _enter_lock(state, status)
        else:
            _ready_banner(state)
            if resume is not None:
                loop.run_until_complete(cmd_resume(state, resume))
        first = True
        while state.running:
            try:
                if not first:
                    _check_guard(state, loop)
                first = False
                prompt = "guard.prompt.prompt" if state.locked else "chat.prompt"
                line = input_func(t(prompt, state.language))
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            text = line.strip()
            try:
                if state.locked:
                    _locked_line(state, loop, text)
                    continue
                if not text:
                    continue
                if text.startswith("/"):
                    resolved = resolve_command(text)
                    name = resolved[0] if resolved is not None else None
                    if name is None or name in ALLOWED_WHILE_LOCKED or _still_unlocked(state, loop):
                        loop.run_until_complete(dispatch_slash(state, text))
                    else:
                        state.say("guard.cmd.refused", command=name)
                else:
                    _turn(state, loop, text)
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
        guard = resolve_guard(config)  # once per process; every build gets the same object
        agent = build_agent(
            config=config,
            role=role,
            approver=approver,
            session_id=session_id,
            session_store=store,
            channel="terminal",
            guard=guard if guard is not None else DISCOVER,
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
        guard=guard,
    )
    run_repl(state, resume=resume)
