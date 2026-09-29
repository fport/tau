"""Terminal channel: ``tau chat``, a line-based REPL.

The reply streams under ``tau>``; tool calls show as indented lines; tier-2 calls ask on stdin
through :class:`TerminalApprover`. Slash commands go through :data:`SLASH_COMMANDS`, one
function each. ``/devam``, ``/yeni`` and ``/oturum`` are placeholders until issue 007.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
from tau_core.config import Config, ConfigError
from tau_core.logs import configure_logging
from tau_core.models import MissingCredentials
from tau_core.sessions import SessionStore, open_session_store
from tau_core.tiers import Tier, tier_of

PROMPT = "sen> "
REPLY_PREFIX = "tau> "
NOT_YET_SESSIONS = "Henüz yok (issue 007)."
TIER_LABELS = {
    Tier.READ: "okuma",
    Tier.DIGITAL_WRITE: "dijital yazma, günlüğe yazılır",
    Tier.PHYSICAL: "fiziksel, onay gerekir",
}


@dataclass
class ReplState:
    config: Config
    store: SessionStore
    approver: Approver
    agent: TauAgent
    console: Console
    role: str = "brain"
    running: bool = True


SlashCommand = Callable[[ReplState, str], Awaitable[None]]


def render_turn_event(event: TurnEvent) -> str | None:
    """The terminal line for a tool or notice event; ``None`` for text and turn ends."""
    if isinstance(event, ToolUseStarted):
        tier = "?" if event.tier is None else str(event.tier)
        return f"  ⚙ {event.tool} (tier {tier})"
    if isinstance(event, ToolFinished):
        if event.status == "rejected":
            return f"  ✗ {event.tool}: onaylanmadı"
        mark = "✓" if event.status == "ok" else "✗"
        return f"  {mark} {event.tool}: {event.summary}"
    if isinstance(event, Notice):
        return f"  ℹ {event.text}"
    return None


# -- slash commands --------------------------------------------------------------------------


async def cmd_devam(state: ReplState, arg: str) -> None:
    """``/devam [n|id]``: list recent sessions and resume one (issue 007)."""
    state.console.print(NOT_YET_SESSIONS)


async def cmd_yeni(state: ReplState, arg: str) -> None:
    """``/yeni``: start a fresh session (issue 007)."""
    state.console.print(NOT_YET_SESSIONS)


async def cmd_oturum(state: ReplState, arg: str) -> None:
    """``/oturum``: show the current session id and store backend (issue 007)."""
    state.console.print(NOT_YET_SESSIONS)


async def cmd_araclar(state: ReplState, arg: str) -> None:
    """``/araçlar``: the registered tools with their tiers."""
    tools = state.agent.catalog.tools()
    if not tools:
        state.console.print("Kayıtlı araç yok.")
        return
    state.console.print(f"Araçlar ({len(tools)}):")
    for tool in tools:
        tier = tier_of(tool)
        description = (tool.tool_spec.get("description") or "").strip().splitlines()
        first_line = description[0] if description else ""
        state.console.print(
            f"  {tool.tool_name}  tier {int(tier)} · {TIER_LABELS[tier]}"
            + (f" — {first_line}" if first_line else "")
        )


async def cmd_cik(state: ReplState, arg: str) -> None:
    """``/çık``: leave the REPL."""
    state.running = False


SLASH_COMMANDS: dict[str, SlashCommand] = {
    "devam": cmd_devam,
    "yeni": cmd_yeni,
    "oturum": cmd_oturum,
    "araçlar": cmd_araclar,
    "araclar": cmd_araclar,
    "çık": cmd_cik,
    "cik": cmd_cik,
}
COMMAND_HINT = "/devam, /yeni, /oturum, /araçlar, /çık"


def _turkish_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


async def dispatch_slash(state: ReplState, line: str) -> None:
    name, _, arg = line[1:].strip().partition(" ")
    handler = SLASH_COMMANDS.get(_turkish_lower(name))
    if handler is None:
        state.console.print(f"Bilinmeyen komut: /{name}. Komutlar: {COMMAND_HINT}")
        return
    await handler(state, arg.strip())


# -- turns and the loop ----------------------------------------------------------------------


async def run_turn(state: ReplState, prompt: str) -> None:
    console = state.console
    in_text = False
    async for event in state.agent.stream(prompt):
        if isinstance(event, TextDelta):
            if not in_text:
                console.print(REPLY_PREFIX, end="", style="bold")
                in_text = True
            console.print(event.text, end="")
            continue
        if isinstance(event, TurnEnd):
            continue
        line = render_turn_event(event)
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
    """Read lines until ``/çık``, Ctrl-D or Ctrl-C."""
    console = state.console
    console.print(
        f"tau hazır. Profil: {state.config.profile}, oturum: {state.agent.session_id}. "
        f"Komutlar: {COMMAND_HINT} (Ctrl-D ile de çıkabilirsiniz)."
    )
    loop = asyncio.new_event_loop()
    try:
        if resume is not None:
            loop.run_until_complete(cmd_devam(state, resume))
        while state.running:
            try:
                line = input_func(PROMPT)
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
                console.print("  ℹ Kesildi.", style="dim")
                if getattr(state.approver, "pending", False):
                    # An approval prompt is still blocking on stdin in a worker thread;
                    # waiting for it would hang the exit.
                    sys.stdout.flush()
                    os._exit(130)
                break
    finally:
        state.agent.close()
        _shutdown(loop)
    console.print("Hoşça kalın.")


@click.command(name="chat", help="Terminalde tau ile sohbet eder.")
@click.option("--role", default="brain", show_default=True, help="Kullanılacak model rolü.")
@click.option(
    "--resume",
    is_flag=False,
    flag_value="",
    default=None,
    metavar="[ID]",
    help="Önceki bir oturuma devam eder (/devam ile aynı).",
)
@click.option("--session", "session_id", metavar="ID", help="Bu oturum kimliğiyle başlar.")
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
        approver = TerminalApprover()
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
        config=config, store=store, approver=approver, agent=agent, console=console, role=role
    )
    run_repl(state, resume=resume)
