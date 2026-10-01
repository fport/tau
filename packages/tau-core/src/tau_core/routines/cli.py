"""``tau routine``: the owner's commands for routines (``tau.commands`` entry point ``routine``).

``add`` and ``edit`` (when the trigger, the tool or the arguments change) ask for one tier-2
approval of the ``add_routine`` call through a :class:`~tau_core.TierGate`, with the terminal's
approver and the owner guard (``resolve_guard``), exactly as a chat turn would: the request
shows the whole definition in plain words, and an approval on a guarded Mac needs the guard's
step-up too. Without an interactive terminal nobody can answer, so the registration is
refused. ``list``, ``pause``, ``resume``, ``remove`` and ``log`` change nothing a routine does
and ask nothing.

Every command reads ``tau.toml`` and ``.env`` like the rest of tau (``--home``, ``TAU_HOME``,
``TAU_DATA_DIR``). Output lines go through ``tau_core.i18n`` in the configured UI language;
help texts and error lines are English. Exit codes: 0 ok, 1 error or not approved (one line on
stderr), 2 when the configuration cannot be loaded.

Tests pass replacements through the click context object: ``routine_approver``,
``routine_guard``, ``routine_tools`` (the tool catalog) and ``routine_clock``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable
from typing import Any, NoReturn

import click

from tau_core import (
    Approver,
    Config,
    ConfigError,
    EventBus,
    TerminalApprover,
    TierGate,
    ToolCatalog,
    resolve_guard,
    t,
)
from tau_core.cli import help_option
from tau_core.guard import process_client_id
from tau_core.i18n import MESSAGES
from tau_core.routines import strings as _strings  # noqa: F401  (registers the message keys)
from tau_core.routines.engine import RefusingApprover
from tau_core.routines.model import ID_RE, Routine, canonical_json, parse_time
from tau_core.routines.registration import (
    RoutineContext,
    register,
    remove,
    rename,
    set_enabled,
)
from tau_core.routines.settings import RoutineConfigError, RoutineError
from tau_core.routines.store import find_routine
from tau_core.routines.tools import add_routine, using
from tau_core.routines.triggers import parse_trigger

__all__ = ["NOT_INTERACTIVE_NOTE", "routine"]

CHANNEL = "terminal"
TIME_FORMAT = "%d.%m.%Y %H:%M"
NOT_INTERACTIVE_NOTE = (
    "Routines are approved in an interactive terminal: the owner can run `tau routine add` there."
)


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _config(ctx: click.Context) -> Config:
    obj = _obj(ctx)
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
    if obj.get("profile"):
        config = config.with_overrides(profile=obj["profile"])
    return config


def _fail(ctx: click.Context, error: BaseException | str) -> NoReturn:
    message = " ".join(str(error).split()) or type(error).__name__
    click.echo(f"tau routine: {message}", err=True)
    ctx.exit(1)
    raise AssertionError("unreachable")  # pragma: no cover


def _context(ctx: click.Context, config: Config) -> RoutineContext:
    obj = _obj(ctx)
    try:
        return RoutineContext.from_config(
            config, tools=obj.get("routine_tools"), clock=obj.get("routine_clock")
        )
    except RoutineConfigError as exc:
        click.echo(f"tau routine: {exc}", err=True)
        ctx.exit(2)
        raise AssertionError("unreachable") from exc  # pragma: no cover


class _Say:
    def __init__(self, config: Config):
        self.language = config.ui.language

    def text(self, key: str, /, **kwargs: Any) -> str:
        return t(key, self.language, **kwargs)

    def __call__(self, key: str, /, *, err: bool = False, **kwargs: Any) -> None:
        click.echo(t(key, self.language, **kwargs), err=err)


def _approver(ctx: click.Context, config: Config) -> Approver:
    given = _obj(ctx).get("routine_approver")
    if given is not None:
        return given
    if sys.stdin.isatty():
        return TerminalApprover(language=config.ui.language)
    return RefusingApprover(NOT_INTERACTIVE_NOTE)


def _gate(ctx: click.Context, config: Config) -> TierGate:
    """The gate of one registration: the ``add_routine`` tool alone, the terminal's approver
    and the owner guard of this configuration (its step-up follows an approval)."""
    guard = _obj(ctx).get("routine_guard") or resolve_guard(config)
    return TierGate(
        ToolCatalog([add_routine]),
        _approver(ctx, config),
        EventBus(),
        session_id=None,
        channel=CHANNEL,
        guard=guard,
        client_id=process_client_id(),
    )


def _value(raw: str, declared: Any) -> Any:
    """A ``NAME=VALUE`` value: kept as text for a string argument, else read as JSON when it
    is JSON (``3``, ``true``, ``[1, 2]``) and as text when it is not."""
    if declared == "string":
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _arguments(
    ctx: click.Context,
    context: RoutineContext,
    tool: str,
    pairs: Iterable[str],
    args_json: str | None,
    base: dict[str, Any],
) -> dict[str, Any]:
    arguments = dict(base)
    if args_json is not None:
        try:
            parsed = json.loads(args_json)
        except ValueError as exc:
            _fail(ctx, f"--args is not valid JSON: {exc}")
        if not isinstance(parsed, dict):
            _fail(ctx, '--args must be a JSON object, for example \'{"action": "lamp on"}\'.')
        arguments = parsed
    agent_tool = context.catalog.get(tool)
    spec = getattr(agent_tool, "tool_spec", None) or {}
    properties = ((spec.get("inputSchema") or {}).get("json") or {}).get("properties") or {}
    for pair in pairs:
        name, sep, raw = pair.partition("=")
        name = name.strip()
        if not sep or not name:
            _fail(ctx, f"{pair!r} is not NAME=VALUE.")
        arguments[name] = _value(raw, (properties.get(name) or {}).get("type"))
    return arguments


def _when(context: RoutineContext, say: _Say, routine: Routine) -> str:
    upcoming = context.next_run(routine)
    if upcoming is None:
        return say.text("routine.none")
    return f"{context.local(upcoming):{TIME_FORMAT}}"


def _same_trigger(text: str, routine: Routine) -> bool:
    try:
        return parse_trigger(text) == routine.trigger
    except RoutineError:
        return False


def _register(ctx: click.Context, config: Config, context: RoutineContext, draft: Any) -> Any:
    gate = _gate(ctx, config)
    with using(context):
        try:
            return asyncio.run(register(draft, gate=gate, store=context.store, clock=context.clock))
        except (RoutineError, OSError) as exc:
            _fail(ctx, exc)


@click.group(
    name="routine",
    help="Routines: one tool call with fixed arguments that the hub runs on a clock, without a "
    "model, the cloud or you at the Mac (lamps on at 07:00 on weekdays). Registering one, or "
    "changing what it does, is one approval; its firings never ask again. Triggers: 'daily "
    "07:00', 'daily 07:00 weekdays', 'daily 18:30 mon,wed,fri', 'once 2026-10-05 07:00', "
    "'every 15 minutes' (at least 5). State lives in TAU_DATA_DIR/routines/.",
    short_help="Tool calls on a clock (lamps on at 07:00).",
)
@help_option()
def routine() -> None:
    pass


@routine.command(
    name="add",
    help="Register a routine: TRIGGER, the TOOL it runs and its arguments as NAME=VALUE pairs "
    "(a value is read as JSON when it is JSON, except for text arguments) or as --args JSON. "
    "Asks for one approval that shows the whole definition.",
    short_help="Register a routine (one approval).",
)
@help_option()
@click.argument("trigger")
@click.argument("tool")
@click.argument("pairs", nargs=-1, metavar="[NAME=VALUE]...")
@click.option("--name", metavar="TEXT", help="A short name (default: the tool and trigger).")
@click.option("--args", "args_json", metavar="JSON", help="All arguments as one JSON object.")
@click.pass_context
def add_command(
    ctx: click.Context,
    trigger: str,
    tool: str,
    pairs: tuple[str, ...],
    name: str | None,
    args_json: str | None,
) -> None:
    config = _config(ctx)
    say = _Say(config)
    context = _context(ctx, config)
    arguments = _arguments(ctx, context, tool, pairs, args_json, base={})
    try:
        draft = context.draft(trigger=trigger, tool=tool, arguments=arguments, name=name or "")
    except RoutineError as exc:
        _fail(ctx, exc)
    outcome = _register(ctx, config, context, draft)
    stored = outcome.routine
    if stored is None:
        say("routine.add.rejected", err=True)
        ctx.exit(1)
    say(
        "routine.add.done",
        id=stored.id,
        name=stored.name,
        trigger=stored.trigger.text,
        tool=stored.tool,
        next=_when(context, say, stored),
    )


@routine.command(
    name="edit",
    help="Change a routine (by id or name). A new --name alone is free; a new --trigger, "
    "--tool or arguments (NAME=VALUE pairs on top of the current ones, or --args to replace "
    "them) asks for the approval again, and a rejection leaves the routine as it was. Without "
    "options, a routine that no longer matches its approval is offered for approval again.",
    short_help="Change a routine (a new call asks again).",
)
@help_option()
@click.argument("ref", metavar="ROUTINE")
@click.argument("pairs", nargs=-1, metavar="[NAME=VALUE]...")
@click.option("--name", metavar="TEXT", help="A new name (free).")
@click.option("--trigger", metavar="TRIGGER", help="A new trigger.")
@click.option("--tool", metavar="TOOL", help="A new tool (its arguments start empty).")
@click.option("--args", "args_json", metavar="JSON", help="All arguments as one JSON object.")
@click.pass_context
def edit_command(
    ctx: click.Context,
    ref: str,
    pairs: tuple[str, ...],
    name: str | None,
    trigger: str | None,
    tool: str | None,
    args_json: str | None,
) -> None:
    config = _config(ctx)
    say = _Say(config)
    context = _context(ctx, config)
    try:
        old = find_routine(context.store.load(), ref)
    except RoutineError as exc:
        _fail(ctx, exc)
    new_name = " ".join((name or "").split()) or old.name

    def rename_only() -> None:
        if new_name == old.name:
            say("routine.edit.nothing", err=True)
            ctx.exit(1)
        try:
            renamed = rename(context.store, old.id, new_name)
        except RoutineError as exc:
            _fail(ctx, exc)
        say("routine.edit.renamed", id=renamed.id, name=renamed.name)

    call_given = any(value is not None for value in (trigger, tool, args_json)) or bool(pairs)
    if not call_given and old.approved:
        rename_only()  # free: nothing the routine does changes
        return
    new_tool = tool or old.tool
    base = dict(old.arguments) if new_tool == old.tool else {}
    arguments = _arguments(ctx, context, new_tool, pairs, args_json, base=base)
    new_trigger = trigger or old.trigger
    unchanged = (
        new_tool == old.tool
        and canonical_json(arguments) == canonical_json(old.arguments)
        and (trigger is None or _same_trigger(trigger, old))
    )
    if unchanged and old.approved:
        rename_only()
        return
    try:
        draft = context.draft(
            trigger=new_trigger, tool=new_tool, arguments=arguments, name=new_name, replaces=old.id
        )
    except RoutineError as exc:
        _fail(ctx, exc)
    outcome = _register(ctx, config, context, draft)
    stored = outcome.routine
    if stored is None:
        say("routine.edit.rejected", err=True)
        ctx.exit(1)
    say(
        "routine.edit.done",
        id=stored.id,
        name=stored.name,
        trigger=stored.trigger.text,
        tool=stored.tool,
        next=_when(context, say, stored),
    )


@routine.command(name="list", help="List the routines with their state and next run.")
@help_option()
@click.pass_context
def list_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    context = _context(ctx, config)
    try:
        routines = context.store.load()
    except RoutineError as exc:
        _fail(ctx, exc)
    if not routines:
        say("routine.list.none")
        return
    for item in routines:
        arguments = " ".join(
            f"{key}={canonical_json(value)}" for key, value in item.arguments.items()
        )
        say(
            "routine.list.row",
            id=item.id,
            name=item.name,
            state=say.text(f"routine.state.{context.state(item)}"),
        )
        say(
            "routine.list.call",
            trigger=item.trigger.text,
            tool=item.tool,
            arguments=arguments or say.text("routine.no_arguments"),
        )
        say("routine.list.next", next=_when(context, say, item), failures=item.failures)
    say("routine.list.zone", zone=context.settings.zone_name)


def _switch(ctx: click.Context, ref: str, enabled: bool) -> None:
    config = _config(ctx)
    say = _Say(config)
    context = _context(ctx, config)
    try:
        changed = set_enabled(context.store, ref, enabled, context.now())
    except RoutineError as exc:
        _fail(ctx, exc)
    if not enabled:
        say("routine.pause.done", id=changed.id, name=changed.name)
        return
    say("routine.resume.done", id=changed.id, name=changed.name, next=_when(context, say, changed))
    if not changed.approved:
        say("routine.resume.unapproved", id=changed.id)


@routine.command(name="pause", help="Pause a routine (by id or name); nothing is asked.")
@help_option()
@click.argument("ref", metavar="ROUTINE")
@click.pass_context
def pause_command(ctx: click.Context, ref: str) -> None:
    _switch(ctx, ref, False)


@routine.command(
    name="resume",
    help="Resume a paused routine (by id or name); nothing is asked. What fell due while it "
    "was paused is skipped.",
)
@help_option()
@click.argument("ref", metavar="ROUTINE")
@click.pass_context
def resume_command(ctx: click.Context, ref: str) -> None:
    _switch(ctx, ref, True)


@routine.command(name="remove", help="Remove a routine (by id or name); nothing is asked.")
@help_option()
@click.argument("ref", metavar="ROUTINE")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
@click.pass_context
def remove_command(ctx: click.Context, ref: str, yes: bool) -> None:
    config = _config(ctx)
    say = _Say(config)
    context = _context(ctx, config)
    try:
        found = find_routine(context.store.load(), ref)
    except RoutineError as exc:
        _fail(ctx, exc)
    if not yes:
        try:
            confirmed = click.confirm(
                say.text("routine.remove.confirm", id=found.id, name=found.name), default=False
            )
        except click.Abort:
            click.echo()
            confirmed = False
        if not confirmed:
            say("routine.remove.kept")
            return
    try:
        removed = remove(context.store, found.id)
    except RoutineError as exc:
        _fail(ctx, exc)
    say("routine.remove.done", id=removed.id, name=removed.name)


@routine.command(
    name="log",
    help="Show the routine log: firings, missed firings, pauses and changes (of one routine "
    "when ROUTINE is given).",
)
@help_option()
@click.argument("ref", metavar="[ROUTINE]", required=False)
@click.option("-n", "--lines", "limit", type=click.IntRange(1, 1000), default=20, show_default=True)
@click.pass_context
def log_command(ctx: click.Context, ref: str | None, limit: int) -> None:
    config = _config(ctx)
    say = _Say(config)
    context = _context(ctx, config)
    routine_id = None
    if ref is not None:
        try:
            routine_id = find_routine(context.store.load(), ref).id
        except RoutineError as exc:
            if not ID_RE.match(ref):  # a removed routine is still in the log by its id
                _fail(ctx, exc)
            routine_id = ref
    entries = context.store.read_log(limit=limit, routine_id=routine_id)
    if not entries:
        say("routine.log.none")
        return
    for entry in entries:
        at = str(entry.get("at", ""))
        try:
            at = f"{context.local(parse_time(at, 'at')):{TIME_FORMAT}}"
        except RoutineError:
            pass
        status = str(entry.get("status", ""))
        key = f"routine.status.{status}"
        say(
            "routine.log.row",
            at=at,
            id=entry.get("id", "-"),
            name=entry.get("name", "-"),
            status=say.text(key) if key in MESSAGES else status,
            detail=entry.get("detail", ""),
        )
