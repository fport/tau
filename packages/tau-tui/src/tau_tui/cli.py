"""``tau tui``: mounted into the ``tau`` command through the ``tau.commands`` entry point."""

from __future__ import annotations

import click


@click.command(name="tui", help="tau'yu Textual arayüzünde açar.")
def tui() -> None:
    click.echo("Henüz yok (issue 008).")
