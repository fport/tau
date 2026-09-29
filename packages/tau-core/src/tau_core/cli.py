"""The ``tau`` command.

Subcommands come from the ``tau.commands`` entry point group (``chat`` and ``hub`` from
tau-core, ``tui`` from tau-tui, anything a plugin adds) plus the built-in ``version``.
Global ``--home``/``--profile``/``--lang`` are exported as ``TAU_HOME``/``TAU_PROFILE``/``TAU_LANG``
for the duration of the command, so every subcommand's ``Config.load()`` sees them without extra
plumbing. Help texts are English; the channels' chrome follows ``Config.ui.language``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar

import click

from tau_core.config import DEFAULT_PROFILE, PROFILES
from tau_core.i18n import LANGUAGES
from tau_core.logs import configure_logging, reset_logging
from tau_core.plugins import command_names, load_command

F = TypeVar("F", bound=Callable[..., Any])

HELP_TEXT = "Show this help and exit."


def help_option() -> Callable[[F], F]:
    """``-h/--help`` with tau's own wording, for tau's own commands."""
    return click.help_option("-h", "--help", help=HELP_TEXT)


HELP = (
    "tau — a personal smart-body agent.\n\n"
    "Subcommands come from plugins (the tau.commands entry point group)."
)


class TauCLI(click.Group):
    """A group that also mounts every ``tau.commands`` entry point, loaded on demand."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(set(super().list_commands(ctx)) | set(command_names()))

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        return load_command(cmd_name)


def _export_env(ctx: click.Context, values: dict[str, str]) -> None:
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)

    def restore() -> None:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    ctx.call_on_close(restore)


@click.group(cls=TauCLI, help=HELP, context_settings={"help_option_names": ["-h", "--help"]})
@help_option()
@click.option(
    "--profile",
    metavar="NAME",
    help=f"Active profile, e.g. {' | '.join(PROFILES)} (default: TAU_PROFILE, else "
    f"'{DEFAULT_PROFILE}').",
)
@click.option(
    "--home",
    type=click.Path(file_okay=False, path_type=Path),
    metavar="DIR",
    help="Configuration root: tau.toml, persona/, tools/ (default: TAU_HOME).",
)
@click.option(
    "--lang",
    type=click.Choice(LANGUAGES),
    metavar="LANG",
    help=f"UI language, {' | '.join(LANGUAGES)} (default: TAU_LANG, else [ui] in tau.toml).",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose log output.")
@click.pass_context
def cli(
    ctx: click.Context, profile: str | None, home: Path | None, lang: str | None, verbose: bool
) -> None:
    ctx.ensure_object(dict)
    ctx.obj.update(profile=profile, home=home, lang=lang, verbose=verbose)
    exported: dict[str, str] = {}
    if home is not None:
        exported["TAU_HOME"] = str(home.expanduser().resolve())
    if profile:
        exported["TAU_PROFILE"] = profile
    if lang:
        exported["TAU_LANG"] = lang
    if exported:
        _export_env(ctx, exported)
    configure_logging(None, verbose=verbose)
    ctx.call_on_close(reset_logging)


@cli.command(name="version", help="Show the versions of the installed tau packages.")
@help_option()
def version() -> None:
    names = sorted(
        {
            dist.metadata["Name"]
            for dist in metadata.distributions()
            if (dist.metadata["Name"] or "").startswith("tau-")
        }
    )
    if "tau-core" in names:
        names.remove("tau-core")
    for name in ["tau-core", *names]:
        try:
            click.echo(f"{name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            continue


def main() -> None:
    cli(prog_name="tau")
