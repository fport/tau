"""``tau tui``: mounted into the ``tau`` command through the ``tau.commands`` entry point.

Three starts: with a loadable config and credentials the app opens as usual; with a config
whose role has no credentials the app opens without an agent on the settings screen
(``build_app`` handles that); with no ``tau.toml`` at all the setup screen creates one (the
same code as ``tau init``) and the command continues on that home. A broken ``tau.toml`` and
an unknown ``--resume`` id still end with a plain English message and exit code 2.

With an owner guard active (ADR 0008) the app opens on its lock screen. The setup screen never
opens while a guard is enrolled for the data directory the new home would use: there is no
configuration to unlock with yet, so the command says so and exits 2 (``tau init`` creates the
configuration).
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from tau_core import (
    Config,
    ConfigError,
    ConfigNotFound,
    configure_logging,
    open_session_store,
)
from tau_core.builder import env_with_dotenv
from tau_core.config import DEFAULT_DATA_DIR, DEFAULT_HOME
from tau_core.guard import ENROLLED_MARKER
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES

from tau_tui.app import SessionNotFound, build_app, resolve_resume
from tau_tui.setup import SetupResult, run_setup

HELP_TEXT = "Show this help and exit."
SETUP_CANCELLED = "Setup cancelled. Run `tau tui` again, or `tau init`, to create a configuration."
SETUP_GUARDED = (
    "The owner guard is enrolled for this data directory, so the setup screen stays closed "
    "while tau is locked. Create the configuration with `tau init`, then run `tau tui` again."
)


def _shown_home(home: Path) -> str:
    """``~/.tau`` for the default, else the resolved path as typed-friendly text."""
    default = Path(DEFAULT_HOME).expanduser().resolve()
    if home == default:
        return DEFAULT_HOME
    try:
        return f"~/{home.relative_to(Path.home())}"
    except ValueError:
        return str(home)


def _guard_enrolled(home: Path) -> bool:
    """A guard marker in the data directory a configuration at ``home`` would use (the
    ``TAU_DATA_DIR`` of the environment or ``home/.env``, else the default)."""
    env = env_with_dotenv(home, os.environ)
    data_dir = Path(env.get("TAU_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
    return (data_dir / ENROLLED_MARKER).exists()


def _setup(exc: ConfigNotFound) -> SetupResult | None:
    language = os.environ.get("TAU_LANG") or DEFAULT_LANGUAGE
    return run_setup(
        default_home=_shown_home(exc.home),
        language=language if language in LANGUAGES else DEFAULT_LANGUAGE,
    )


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
    home = obj.get("home")
    try:
        config = Config.load(home)
    except ConfigNotFound as exc:
        if _guard_enrolled(exc.home):
            click.echo(str(exc), err=True)
            click.echo(SETUP_GUARDED, err=True)
            ctx.exit(2)
            return
        result = _setup(exc)
        if result is None:
            click.echo(str(exc), err=True)
            click.echo(SETUP_CANCELLED, err=True)
            ctx.exit(2)
            return
        home = result.home
        try:
            config = Config.load(home)
        except ConfigError as inner:
            click.echo(str(inner), err=True)
            ctx.exit(2)
            return
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
        app = build_app(
            config, profile=profile, session_store=store, session_id=session_id, notice=notice
        )
    except (ConfigError, SessionNotFound) as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        return
    try:
        app.run()
    finally:
        if app.agent is not None:
            app.agent.close()
    click.echo("Goodbye.")
