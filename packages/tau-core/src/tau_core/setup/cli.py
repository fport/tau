"""``tau setup``: pick the features, install and configure them (ADR 0014, issue 169).

Mounted through the ``tau.commands`` entry point ``setup``. Tests pass a fake
:class:`~tau_core.setup.host.Host` as ``obj["setup_host"]``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from tau_core.cli import help_option
from tau_core.setup.catalog import Catalog, CatalogError, load_catalog
from tau_core.setup.engine import parse_ids
from tau_core.setup.host import Host, SystemHost
from tau_core.setup.protocol import emitter, install_json, run_json, status_payload
from tau_core.setup.state import take_snapshot
from tau_core.setup.wizard import Wizard

__all__ = ["setup"]


def _host(ctx: click.Context) -> Host:
    obj: dict[str, Any] = ctx.find_object(dict) or {}
    injected = obj.get("setup_host")
    return injected if isinstance(injected, Host) else SystemHost()


def _catalog(ctx: click.Context) -> Catalog:
    try:
        return load_catalog()
    except CatalogError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)


@click.group(
    name="setup",
    invoke_without_command=True,
    help="Pick tau's features, install their packages and set them up: an interactive "
    "checklist, then one `uv tool install` pinned to this tau-core, then `tau init` when "
    "there is no configuration, a short 'about you', each chosen feature's steps and "
    "`tau doctor`. Run it again to add a feature; what is set up is never asked again. "
    "--yes --features tui,sub asks nothing. `tau setup status|install|run --json` is the "
    "line protocol of the Mac app (docs/reference/setup.md).",
    short_help="Pick, install and set up tau's features.",
)
@help_option()
@click.option(
    "--features",
    "features",
    multiple=True,
    metavar="IDS",
    help="Comma-separated feature ids to set up (see `tau setup status`); skips the checklist.",
)
@click.option("-y", "--yes", is_flag=True, help="Ask nothing: defaults, no optional steps.")
@click.option(
    "--no-install", "no_install", is_flag=True, help="Install nothing; set up what is installed."
)
@click.option(
    "--remove",
    "remove",
    metavar="FEATURE",
    help="Uninstall a feature's package (its settings and data stay).",
)
@click.option(
    "--upgrade",
    is_flag=True,
    help="Reinstall tau-core and the installed feature packages at their newest releases.",
)
@click.option(
    "--resume",
    type=click.Path(dir_okay=False, path_type=Path),
    hidden=True,
    help="Continue after the re-execution in the new environment (internal).",
)
@click.pass_context
def setup(
    ctx: click.Context,
    features: tuple[str, ...],
    yes: bool,
    no_install: bool,
    remove: str | None,
    upgrade: bool,
    resume: Path | None,
) -> None:
    if ctx.invoked_subcommand is not None:
        if features or yes or no_install or remove or upgrade or resume:
            raise click.UsageError("Options of the wizard go without a subcommand.")
        return
    wizard = Wizard(
        _host(ctx),
        _catalog(ctx),
        features=parse_ids(features),
        yes=yes,
        no_install=no_install,
        resume=resume,
        remove=remove,
        upgrade=upgrade,
    )
    ctx.exit(wizard.run())


@setup.command(
    name="status",
    help="Show every feature: whether this platform has it, whether its package is installed "
    "and whether it is set up. --json prints the object the Mac app reads.",
    short_help="Show the features and their state.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Print one JSON object.")
@click.pass_context
def status_command(ctx: click.Context, as_json: bool) -> None:
    host = _host(ctx)
    catalog = _catalog(ctx)
    snapshot = take_snapshot(host, catalog)
    payload = status_payload(host, catalog, snapshot)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    wizard = Wizard(host, catalog)
    wizard.language = payload["language"]
    wizard.header(snapshot)
    for line in wizard.checklist_lines(snapshot, set(), ids=True):
        click.echo(line)


@setup.command(
    name="install",
    help="Install the packages of the given features with one `uv tool install` (pinned to "
    "this tau-core) and configure nothing. --json streams JSON lines.",
    short_help="Install the packages of features.",
)
@help_option()
@click.option(
    "--features",
    "features",
    multiple=True,
    required=True,
    metavar="IDS",
    help="Comma-separated feature ids; what they require is added.",
)
@click.option("--json", "as_json", is_flag=True, help="Stream JSON lines.")
@click.pass_context
def install_command(ctx: click.Context, features: tuple[str, ...], as_json: bool) -> None:
    host = _host(ctx)
    catalog = _catalog(ctx)
    emit = emitter() if as_json else _plain_emitter()
    ctx.exit(install_json(host, catalog, features, emit))


@setup.command(
    name="run",
    help="Run the steps of one feature, or of init, about or doctor. With --json the inputs "
    'come as one JSON object on stdin ({"steps": [...], "inputs": {...}}), never in argv, and '
    "a step that needs its own UI is reported as needs_ui instead of run. Without --json the "
    "wizard's steps run for that feature.",
    short_help="Run the steps of one feature.",
)
@help_option()
@click.argument("feature")
@click.option("--json", "as_json", is_flag=True, help="JSON input on stdin, JSON lines out.")
@click.pass_context
def run_command(ctx: click.Context, feature: str, as_json: bool) -> None:
    host = _host(ctx)
    catalog = _catalog(ctx)
    if as_json:
        ctx.exit(run_json(host, catalog, feature, emitter()))
    if feature in ("init", "about", "doctor"):
        raise click.UsageError("init, about and doctor run through `tau setup` or with --json.")
    if catalog.get(feature) is None:
        known = ", ".join(catalog.ids())
        raise click.UsageError(f"Unknown feature: {feature}. Known: {known}.")
    wizard = Wizard(host, catalog, features=[feature], no_install=True)
    ctx.exit(wizard.run_feature(feature))


def _plain_emitter() -> Callable[..., None]:
    """The events of ``install`` as plain lines, for a person at a terminal."""

    def emit(event: str, /, **fields: Any) -> None:
        if event == "log":
            click.echo(fields.get("line", ""))
        elif event == "error":
            click.echo(fields.get("message", ""), err=True)
        elif event == "progress" and fields.get("phase") == "install":
            click.echo(" ".join(fields.get("argv", [])[1:]))

    return emit
