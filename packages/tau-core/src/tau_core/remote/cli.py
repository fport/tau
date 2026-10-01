"""``tau remote``: check remote access and say what to do (issue 173).

``tau remote tailscale|ssh|phone`` are the check steps of ``tau setup`` → Remote access, and
``tau remote status`` is all of them: remote access counts as set up when it exits 0. With
``--json`` each prints one check object (:mod:`tau_core.setup.checks`). Nothing here runs
``sudo`` or a script: the command that needs ``sudo`` is shown for the owner to run.

Mounted through the ``tau.commands`` entry point ``remote``. Tests pass a fake
:class:`~tau_core.remote.system.System` as ``obj["remote_system"]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from tau_core.cli import help_option
from tau_core.config import resolve_home
from tau_core.i18n import DEFAULT_LANGUAGE, t
from tau_core.remote.checks import (
    Kit,
    phone_check,
    ssh_check,
    status_parts,
    status_result,
    tailscale_check,
)
from tau_core.remote.scripts import kit_dir
from tau_core.remote.system import LocalSystem, System
from tau_core.setup.checks import CheckResult, render_action, render_checks
from tau_core.setup.state import configured_language, data_dir

__all__ = ["remote"]

JSON_HELP = "Print one check object (docs/reference/setup.md)."


def _system(ctx: click.Context) -> System:
    obj: dict[str, Any] = ctx.find_object(dict) or {}
    injected = obj.get("remote_system")
    return injected if isinstance(injected, System) else LocalSystem()


def _language(system: System) -> str:
    home = resolve_home(None, system.environ)
    return configured_language(home, system.environ) or DEFAULT_LANGUAGE


def _kit(system: System) -> Kit:
    def build() -> Path:
        home = resolve_home(None, system.environ)
        return kit_dir(system, data_dir(home, system.environ))

    return build


def _show(result: CheckResult, *, as_json: bool, language: str, title: str) -> int:
    if as_json:
        click.echo(result.dumps())
        return 0 if result.ok else 1
    click.echo(title)
    for line in render_checks(result.checks):
        click.echo(line)
    if result.action is not None:
        for line in render_action(result.action, language):
            click.echo(line)
    click.echo()
    click.echo(f"{'✓' if result.ok else '✗'} {result.summary}")
    return 0 if result.ok else 1


@click.group(
    name="remote",
    help="Remote access: reach this machine from your phone over Tailscale, SSH, mosh and tmux. "
    "These commands check it and say what to do; the one command that needs sudo is shown for "
    "you to run, never run by tau. `tau setup` → Remote access walks through them.",
    short_help="Check remote access: Tailscale, SSH, mosh, the phone.",
)
@help_option()
def remote() -> None:
    pass


@remote.command(
    name="status",
    help="Every remote access check: Tailscale, sshd with tau's drop-in, a password login "
    "probe, mosh, tmux and the phone's key. Exit 0 when remote access is ready, else 1. It "
    "changes nothing.",
    short_help="Check everything; exit 0 when remote access is ready.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def status_command(ctx: click.Context, as_json: bool) -> None:
    system = _system(ctx)
    language = _language(system)
    result = status_result(system, language)
    if as_json:
        click.echo(result.dumps())
        ctx.exit(0 if result.ok else 1)
    titles = {
        "tailscale": "setup.step.remote.tailscale",
        "ssh": "setup.step.remote.ssh",
        "phone": "setup.step.remote.phone",
    }
    for group, part in status_parts(system, language):
        if group in titles:
            click.echo(t(titles[group], language))
        for line in render_checks(part.checks):
            click.echo(line)
        click.echo()
    click.echo(f"{'✓' if result.ok else '✗'} {result.summary}")
    ctx.exit(0 if result.ok else 1)


@remote.command(
    name="tailscale",
    help="Check that Tailscale is installed and logged in, with this machine's MagicDNS name "
    "and 100.x address; otherwise say how to install it or log in. Exit 0 when it is "
    "connected, else 1.",
    short_help="Check Tailscale.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def tailscale_command(ctx: click.Context, as_json: bool) -> None:
    system = _system(ctx)
    language = _language(system)
    title = t("setup.step.remote.tailscale", language)
    result = tailscale_check(system, language)
    ctx.exit(_show(result, as_json=as_json, language=language, title=title))


@remote.command(
    name="ssh",
    help="Check sshd, tau's drop-in (keys only, only you from the tailnet and localhost), "
    "password login, mosh and tmux. Otherwise show the one command to run in your own "
    "terminal (it asks for your password with sudo) and what it changes; tau never runs it. "
    "Without a checkout it first writes the scripts to $TAU_DATA_DIR/remote. Exit 0 when "
    "everything holds, else 1.",
    short_help="Check SSH and mosh; show the one command to fix them.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def ssh_command(ctx: click.Context, as_json: bool) -> None:
    system = _system(ctx)
    language = _language(system)
    title = t("setup.step.remote.ssh", language)
    result = ssh_check(system, language, kit=_kit(system))
    ctx.exit(_show(result, as_json=as_json, language=language, title=title))


@remote.command(
    name="phone",
    help="Print what to enter in Termius: this machine's MagicDNS name, your user, port 22, "
    "mosh and the tau-attach startup snippet, from the live Tailscale state (printed only, "
    "never written). Exit 0 when Tailscale is connected and a key is in "
    "~/.ssh/authorized_keys, else 1 with how to add one.",
    short_help="What to enter in Termius on the phone.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def phone_command(ctx: click.Context, as_json: bool) -> None:
    system = _system(ctx)
    language = _language(system)
    title = t("setup.step.remote.phone", language)
    result = phone_check(system, language, kit=_kit(system))
    ctx.exit(_show(result, as_json=as_json, language=language, title=title))
