"""``tau tui``: mounted into the ``tau`` command through the ``tau.commands`` entry point."""

from __future__ import annotations

import click
from tau_core import (
    Config,
    ConfigError,
    MissingCredentials,
    configure_logging,
    open_session_store,
)

from tau_tui.app import SessionNotFound, build_app, resolve_resume

HELP_TEXT = "Show this help and exit."


@click.command(name="tui", help="Open tau in the Textual interface.")
@click.help_option("-h", "--help", help=HELP_TEXT)
@click.option(
    "--profile", metavar="NAME", help="Active profile (default: TAU_PROFILE, else 'home')."
)
@click.option(
    "--resume",
    is_flag=False,
    flag_value="",
    default=None,
    metavar="[ID]",
    help="Resume an earlier session (the most recent one when ID is omitted).",
)
@click.pass_context
def tui(ctx: click.Context, profile: str | None, resume: str | None) -> None:
    obj = ctx.find_object(dict) or {}
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        return
    profile = profile or obj.get("profile")
    if profile:
        config = config.with_overrides(profile=profile)
    # The terminal belongs to Textual while the app runs: details go to <data_dir>/logs/tau.log
    # and nothing reaches stderr. The ``tau`` group resets logging when the command closes.
    configure_logging(config.logs_dir, verbose=bool(obj.get("verbose")), console=False)
    try:
        store = open_session_store(config)
        session_id, notice = resolve_resume(store, resume, language=config.ui.language)
        app = build_app(config, session_store=store, session_id=session_id, notice=notice)
    except (MissingCredentials, ConfigError, SessionNotFound) as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        return
    try:
        app.run()
    finally:
        app.agent.close()
    click.echo("Goodbye.")
