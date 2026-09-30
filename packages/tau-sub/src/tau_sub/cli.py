"""``tau sub``: the owner's commands for sub-taus (``tau.commands`` entry point ``sub``).

Every command reads ``tau.toml`` and ``.env`` like the rest of tau (``--home``, ``TAU_HOME``,
``TAU_DATA_DIR``). Output lines go through ``tau_core.i18n`` in the configured UI language;
help texts and error lines are English. Exit codes: 0 ok, 1 error with one line on stderr,
2 when the configuration itself cannot be loaded.

``tau sub chat`` is a line REPL like ``tau chat``: the reply streams under ``/name>``, tool
calls and notices use tau-core's terminal rendering, and tier-2 calls ask on stdin through
``TerminalApprover``. ``tau sub ask`` is one turn; when stdin is not a terminal nobody can
answer an approval, so every tier-2 call is refused.

Tests pass replacements through the click context object: ``sub_model`` (role → model),
``sub_approver``, ``sub_tools`` (the tool catalog), ``sub_store`` (the session store),
``sub_input`` (the REPL's input function), ``sub_interactive`` (may ``ask`` prompt?) and
``sub_editor`` (what ``edit`` opens the file with).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import click
from strands.types.exceptions import SessionException
from tau_core import (
    Approver,
    Config,
    ConfigError,
    MissingCredentials,
    TauAgent,
    TerminalApprover,
    TextDelta,
    TurnEnd,
    configure_logging,
    reset_logging,
    resolve_command,
    t,
    tier_of,
)
from tau_core.channels.terminal import render_turn_event
from tau_core.cli import help_option

from tau_sub import strings as _strings  # noqa: F401  (registers the message keys)
from tau_sub._files import FILE_MODE
from tau_sub.agent import SubConversation, last_session
from tau_sub.approval import RefusingApprover
from tau_sub.definition import (
    DEFAULT_ROLE,
    ROLES,
    SubRegistry,
    SubTau,
    SubTauError,
    SubTauExists,
    SubTauNotFound,
    render,
    template,
    validate,
    validate_name,
)
from tau_sub.draft import draft_sub

__all__ = ["run_chat", "sub"]

BUILD_ERRORS = (SubTauError, ConfigError, MissingCredentials, SessionException, OSError, ValueError)
CHAT_COMMANDS = ("help", "tools", "new", "session", "quit")
CHAT_HINT = ", ".join(f"/{name}" for name in CHAT_COMMANDS)


def not_interactive_note(name: str) -> str:
    """The refusal note of ``tau sub ask`` without a terminal (fixed English, the model reads
    it)."""
    return (
        f"Tier-2 tools need an interactive terminal: the owner can run `tau sub chat {name}` "
        "to approve them."
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
    click.echo(f"tau sub: {message}", err=True)
    ctx.exit(1)
    raise AssertionError("unreachable")  # pragma: no cover


class _Say:
    def __init__(self, config: Config):
        self.language = config.ui.language

    def text(self, key: str, /, **kwargs: Any) -> str:
        return t(key, self.language, **kwargs)

    def __call__(self, key: str, /, *, err: bool = False, **kwargs: Any) -> None:
        click.echo(t(key, self.language, **kwargs), err=err)


def _registry(ctx: click.Context, config: Config) -> SubRegistry:
    return SubRegistry(config, tools=_obj(ctx).get("sub_tools"))


def _split(csv: str | None) -> tuple[str, ...] | None:
    if csv is None:
        return None
    return tuple(part.strip() for part in csv.split(",") if part.strip())


def _save(ctx: click.Context, registry: SubRegistry, sub: SubTau, *, force: bool) -> Path:
    try:
        return registry.save(sub, force=force)
    except SubTauError as exc:
        _fail(ctx, exc)
    except OSError as exc:
        _fail(ctx, f"{registry.path(sub.name)} could not be written: {exc.strerror or exc}")


def _confirm(text: str) -> bool:
    try:
        return click.confirm(text, default=False)
    except click.Abort:
        click.echo()
        return False


@click.group(
    name="sub",
    help="Sub-taus: small named specialists of your tau (/coach, /landing, ...), each with its "
    "own persona, model role, tool list and sessions. Definitions live in "
    "persona/subs/<name>.md: TOML front matter between '+++' lines, then the persona text.",
    short_help="Specialists of your tau (/coach, /landing, ...).",
)
@help_option()
def sub() -> None:
    pass


# -- definitions -------------------------------------------------------------------------------


@sub.command(
    name="new",
    help="Create a sub-tau. Without --describe it writes a template to edit; with --describe the "
    "brain role drafts the about line, the persona and the tool list, which you read before "
    "anything is written. Options you pass win over the draft. An existing definition is "
    "never replaced without --force.",
    short_help="Create a sub-tau (from a template or a description).",
)
@help_option()
@click.argument("name")
@click.option("--about", metavar="TEXT", help="One line (at most 200 characters): what it does.")
@click.option(
    "--role", type=click.Choice(ROLES), default=None, help=f"Model role (default: {DEFAULT_ROLE})."
)
@click.option(
    "--tools", "tools_csv", metavar="A,B", help="Tool names from the catalog, comma-separated."
)
@click.option(
    "--public",
    is_flag=True,
    help="Let your contacts reach it over the tau network as <address>/<name> and list it "
    "in the universe.",
)
@click.option(
    "--describe", metavar="TEXT", help="Let the brain role draft it from this description."
)
@click.option(
    "--allow-tier2",
    is_flag=True,
    help="Let the draft keep tier-2 tools (they still ask for approval on every call).",
)
@click.option("-y", "--yes", is_flag=True, help="Write the draft without asking.")
@click.option("--force", is_flag=True, help="Replace an existing definition.")
@click.pass_context
def new_command(
    ctx: click.Context,
    name: str,
    about: str | None,
    role: str | None,
    tools_csv: str | None,
    public: bool,
    describe: str | None,
    allow_tier2: bool,
    yes: bool,
    force: bool,
) -> None:
    config = _config(ctx)
    say = _Say(config)
    registry = _registry(ctx, config)
    try:
        path = registry.path(validate_name(name))
    except SubTauError as exc:
        _fail(ctx, exc)
    if registry.exists(name) and not force:
        _fail(ctx, SubTauExists(name, path))
    tools = _split(tools_csv)
    if describe is None:
        sub_tau = template(
            name, about=about, role=role or DEFAULT_ROLE, tools=tools or (), public=public
        )
        path = _save(ctx, registry, sub_tau, force=force)
        say("sub.new.created", name=name, path=path)
        say("sub.new.next", name=name)
        return

    say("sub.new.drafting", name=name, err=True)
    factory = _obj(ctx).get("sub_model")
    try:
        draft = asyncio.run(
            draft_sub(
                config,
                name,
                describe,
                catalog=registry.catalog(),
                allow_tier2=allow_tier2,
                model=factory("brain") if factory is not None else None,
            )
        )
        sub_tau = validate(
            SubTau(
                name=name,
                about=about or draft.about,
                persona=draft.persona,
                role=role or DEFAULT_ROLE,
                tools=tools if tools is not None else draft.tools,
                public=public,
            ),
            catalog=registry.catalog(),
        )
    except (SubTauError, ConfigError, MissingCredentials) as exc:
        _fail(ctx, exc)
    say("sub.new.draft_header", path=path)
    click.echo()
    click.echo(render(sub_tau))
    for tool, reason in draft.dropped if tools is None else ():
        say("sub.new.dropped", tool=tool, reason=say.text(f"sub.reason.{reason}"))
    if not yes and not _confirm(say.text("sub.new.confirm")):
        say("sub.new.not_written")
        return
    path = _save(ctx, registry, sub_tau, force=force)
    say("sub.new.created", name=name, path=path)
    say("sub.new.next", name=name)


def _tools_text(registry: SubRegistry, sub_tau: SubTau, say: _Say) -> str:
    if not sub_tau.tools:
        return say.text("sub.none")
    catalog = registry.catalog()
    parts = []
    for tool in sub_tau.tools:
        tier = int(tier_of(catalog[tool])) if tool in catalog else "?"
        parts.append(f"{tool} (tier {tier})")
    return ", ".join(parts)


@sub.command(name="list", help="List the sub-taus: name, role, tools, public, last session.")
@help_option()
@click.pass_context
def list_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    registry = _registry(ctx, config)
    subs, broken = registry.scan()
    if not subs and not broken:
        say("sub.list.none")
        return
    by_name = {sub_tau.name: sub_tau for sub_tau in subs}
    for name in registry.names():
        sub_tau = by_name.get(name)
        if sub_tau is None:
            error = broken.get(name)
            if error is not None:
                say("sub.list.broken", name=name, error=" ".join(str(error).split()))
            continue
        say(
            "sub.list.row",
            name=name,
            role=sub_tau.role,
            tools=", ".join(sub_tau.tools) or say.text("sub.none"),
            public=say.text("sub.yes" if sub_tau.public else "sub.no"),
            session=last_session(config, name) or say.text("sub.none"),
        )
        say("sub.list.about", about=sub_tau.about)


@sub.command(name="show", help="Show one sub-tau: its settings and its persona text.")
@help_option()
@click.argument("name")
@click.pass_context
def show_command(ctx: click.Context, name: str) -> None:
    config = _config(ctx)
    say = _Say(config)
    registry = _registry(ctx, config)
    try:
        sub_tau = registry.get(name)
    except SubTauError as exc:
        _fail(ctx, exc)
    say("sub.show.title", name=name, path=registry.path(name))
    say("sub.show.about", about=sub_tau.about)
    say("sub.show.role", role=sub_tau.role)
    say("sub.show.tools", tools=_tools_text(registry, sub_tau, say))
    say("sub.show.public", public=say.text("sub.yes" if sub_tau.public else "sub.no"))
    say("sub.show.public_note", note=sub_tau.public_note or say.text("sub.none"))
    say("sub.show.session", session=last_session(config, name) or say.text("sub.none"))
    click.echo()
    say("sub.show.persona")
    click.echo(sub_tau.persona)


def _default_editor(path: Path) -> None:
    click.edit(filename=str(path))


@sub.command(
    name="edit",
    help="Open the definition in $EDITOR, then check it. An invalid file is reported and "
    "left as you saved it.",
)
@help_option()
@click.argument("name")
@click.pass_context
def edit_command(ctx: click.Context, name: str) -> None:
    config = _config(ctx)
    say = _Say(config)
    registry = _registry(ctx, config)
    try:
        path = registry.path(name)
    except SubTauError as exc:
        _fail(ctx, exc)
    if not path.is_file():
        _fail(ctx, SubTauNotFound(name, path))
    before = path.read_bytes()
    editor: Callable[[Path], None] = _obj(ctx).get("sub_editor") or _default_editor
    editor(path)
    with contextlib.suppress(OSError):
        os.chmod(path, FILE_MODE)  # an editor may save a new file with the default mode
    try:
        registry.get(name)
    except SubTauError as exc:
        _fail(ctx, exc)
    changed = path.read_bytes() != before
    say("sub.edit.valid" if changed else "sub.edit.unchanged", name=name)


@sub.command(
    name="remove",
    help="Remove a sub-tau's definition. Its sessions and its state under TAU_DATA_DIR are "
    "kept: nothing else is deleted.",
)
@help_option()
@click.argument("name")
@click.option("-y", "--yes", is_flag=True, help="Remove without asking.")
@click.pass_context
def remove_command(ctx: click.Context, name: str, yes: bool) -> None:
    config = _config(ctx)
    say = _Say(config)
    registry = _registry(ctx, config)
    try:
        path = registry.path(name)
        if not path.is_file():
            raise SubTauNotFound(name, path)
    except SubTauError as exc:
        _fail(ctx, exc)
    if not yes and not _confirm(say.text("sub.remove.confirm", name=name)):
        say("sub.remove.kept")
        return
    try:
        registry.remove(name)
    except SubTauError as exc:
        _fail(ctx, exc)
    say("sub.remove.done", path=path, name=name)


# -- conversations -----------------------------------------------------------------------------


async def render_turn(
    agent: TauAgent, prompt: str, *, language: str, prefix: str | None, events_err: bool = False
) -> str:
    """Stream one turn to the terminal; returns the turn's stop reason."""
    in_text = False
    stop_reason = "end_turn"
    async for event in agent.stream(prompt):
        if isinstance(event, TextDelta):
            if not in_text:
                if prefix:
                    click.echo(click.style(prefix, bold=True), nl=False)
                in_text = True
            click.echo(event.text, nl=False)
            continue
        if isinstance(event, TurnEnd):
            stop_reason = event.stop_reason
            continue
        line = render_turn_event(event, language)
        if line is None:
            continue
        if in_text:
            click.echo()
            in_text = False
        click.echo(click.style(line, dim=True), err=events_err)
    if in_text:
        click.echo()
    return stop_reason


def _open(
    ctx: click.Context, config: Config, name: str, approver: Approver, *, new: bool
) -> SubConversation:
    obj = _obj(ctx)
    try:
        return SubConversation(
            config,
            name,
            approver=approver,
            new=new,
            session_store=obj.get("sub_store"),
            model_factory=obj.get("sub_model"),
            tools=obj.get("sub_tools"),
        )
    except BUILD_ERRORS as exc:
        _fail(ctx, exc)


def _setup_logging(ctx: click.Context, config: Config) -> None:
    configure_logging(config.logs_dir, verbose=bool(_obj(ctx).get("verbose")))
    ctx.call_on_close(reset_logging)


def _chat_command(conversation: SubConversation, text: str, say: _Say) -> bool:
    """Run one slash command; ``False`` means leave the chat."""
    resolved = resolve_command(text)
    command = resolved[0] if resolved is not None else text[1:].strip().partition(" ")[0]
    name = conversation.sub.name
    if command == "quit":
        return False
    if command == "help":
        say("sub.chat.help")
    elif command == "tools":
        tools = conversation.agent.catalog.tools()
        if not tools:
            say("sub.tools.none", name=name)
        for index, tool in enumerate(tools):
            if index == 0:
                say("sub.tools.header", name=name, n=len(tools))
            tier = int(tier_of(tool))
            click.echo(f"  {tool.tool_name}  tier {tier} · {say.text(f'tier.{tier}')}")
    elif command == "new":
        try:
            session = conversation.new_session()
        except BUILD_ERRORS as exc:
            click.echo(" ".join(str(exc).split()))
        else:
            say("sub.chat.new", session=session)
    elif command == "session":
        say("sub.chat.session", session=conversation.session_id, n=len(conversation.agent.messages))
    else:
        say("sub.chat.unsupported", command=command, hint=CHAT_HINT)
    return True


def _refresh(conversation: SubConversation, say: _Say) -> None:
    name = conversation.sub.name
    try:
        changed = conversation.refresh()
    except BUILD_ERRORS as exc:
        click.echo(say.text("sub.chat.reload_failed", name=name, error=" ".join(str(exc).split())))
        return
    if changed == "prompt":
        click.echo(click.style(say.text("sub.chat.prompt_reloaded", name=name), dim=True))
    elif changed == "rebuilt":
        click.echo(click.style(say.text("sub.chat.rebuilt", name=name), dim=True))


def _shutdown(loop: asyncio.AbstractEventLoop) -> None:
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()


def run_chat(
    conversation: SubConversation, say: _Say, *, input_func: Callable[[str], str] = input
) -> None:
    """Read lines until ``/quit``, Ctrl-D or Ctrl-C; one turn per line."""
    language = say.language
    say(
        "sub.chat.ready",
        name=conversation.sub.name,
        session=conversation.session_id,
        hint=CHAT_HINT,
    )
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                line = input_func(t("chat.prompt", language))
            except (EOFError, KeyboardInterrupt):
                click.echo()
                break
            text = line.strip()
            if not text:
                continue
            if text.startswith("/"):
                if not _chat_command(conversation, text, say):
                    break
                continue
            _refresh(conversation, say)
            prefix = say.text("sub.chat.reply_prefix", name=conversation.sub.name)
            try:
                loop.run_until_complete(
                    render_turn(conversation.agent, text, language=language, prefix=prefix)
                )
            except KeyboardInterrupt:
                click.echo()
                click.echo(click.style(f"  ℹ {t('chat.interrupted', language)}", dim=True))
                if getattr(conversation.approver, "pending", False):
                    # An approval prompt still blocks on stdin in a worker thread; waiting for
                    # it would hang the exit.
                    sys.stdout.flush()
                    os._exit(130)
                break
    finally:
        conversation.close()
        _shutdown(loop)


@sub.command(
    name="chat",
    help="Talk to a sub-tau in the terminal. It continues its last session unless --new is "
    "given; tier-2 tools ask for approval here.",
)
@help_option()
@click.argument("name")
@click.option("--new", "new", is_flag=True, help="Start a new session.")
@click.pass_context
def chat_command(ctx: click.Context, name: str, new: bool) -> None:
    config = _config(ctx)
    say = _Say(config)
    _setup_logging(ctx, config)
    obj = _obj(ctx)
    approver: Approver = obj.get("sub_approver") or TerminalApprover(language=say.language)
    conversation = _open(ctx, config, name, approver, new=new)
    if sys.stdin.isatty():
        with contextlib.suppress(ImportError):
            import readline  # noqa: F401  (line editing and history for input())
    run_chat(conversation, say, input_func=obj.get("sub_input") or input)


@sub.command(
    name="ask",
    help="Ask a sub-tau one question and print its answer. It continues its last session "
    "unless --new is given. A tier-2 tool asks for approval when stdin is a terminal and is "
    "refused otherwise.",
)
@help_option()
@click.argument("name")
@click.argument("words", nargs=-1, required=True, metavar="TEXT...")
@click.option("--new", "new", is_flag=True, help="Start a new session.")
@click.pass_context
def ask_command(ctx: click.Context, name: str, words: tuple[str, ...], new: bool) -> None:
    config = _config(ctx)
    say = _Say(config)
    _setup_logging(ctx, config)
    obj = _obj(ctx)
    question = " ".join(words).strip()
    if not question:
        _fail(ctx, "the question is empty")
    interactive = obj.get("sub_interactive")
    if interactive is None:
        interactive = sys.stdin.isatty()
    approver: Approver | None = obj.get("sub_approver")
    if approver is None:
        approver = (
            TerminalApprover(language=say.language)
            if interactive
            else RefusingApprover(not_interactive_note(name))
        )
    conversation = _open(ctx, config, name, approver, new=new)
    try:
        stop_reason = asyncio.run(
            render_turn(
                conversation.agent, question, language=say.language, prefix=None, events_err=True
            )
        )
    finally:
        conversation.close()
    if stop_reason in ("error", "busy"):
        ctx.exit(1)
