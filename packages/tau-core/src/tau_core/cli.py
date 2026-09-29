"""The ``tau`` command.

Subcommands come from the ``tau.commands`` entry point group (``chat`` and ``hub`` from
tau-core, ``tui`` from tau-tui, anything a plugin adds) plus the built-in ``version``.
Global ``--home``/``--profile`` are exported as ``TAU_HOME``/``TAU_PROFILE`` for the duration of
the command, so every subcommand's ``Config.load()`` sees them without extra plumbing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar

import click

from tau_core.logs import configure_logging, reset_logging
from tau_core.plugins import command_names, load_command

F = TypeVar("F", bound=Callable[..., Any])

HELP_TEXT = "Bu yardımı gösterir ve çıkar."


def help_option() -> Callable[[F], F]:
    """``-h/--help`` with Turkish help text, for tau's own commands."""
    return click.help_option("-h", "--help", help=HELP_TEXT)


HELP = (
    "tau — kişisel akıllı gövde ajanı.\n\n"
    "Alt komutlar eklentilerden (tau.commands giriş noktası) gelir."
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
@click.option("--profile", metavar="AD", help="Etkin profil (varsayılan: TAU_PROFILE, yoksa 'ev').")
@click.option(
    "--home",
    type=click.Path(file_okay=False, path_type=Path),
    metavar="DİZİN",
    help="Yapılandırma kökü: tau.toml, persona/, tools/ (varsayılan: TAU_HOME).",
)
@click.option("-v", "--verbose", is_flag=True, help="Ayrıntılı günlük çıktısı.")
@click.pass_context
def cli(ctx: click.Context, profile: str | None, home: Path | None, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj.update(profile=profile, home=home, verbose=verbose)
    exported: dict[str, str] = {}
    if home is not None:
        exported["TAU_HOME"] = str(home.expanduser().resolve())
    if profile:
        exported["TAU_PROFILE"] = profile
    if exported:
        _export_env(ctx, exported)
    configure_logging(None, verbose=verbose)
    ctx.call_on_close(reset_logging)


@cli.command(name="version", help="Kurulu tau paketlerinin sürümlerini gösterir.")
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
